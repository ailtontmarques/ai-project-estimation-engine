"""Regras de fluxo e permissão sobre a persistência.

As regras de cálculo continuam no motor (engine.py); aqui ficam quem pode fazer o quê,
versionamento dos requisitos, registro das estimativas e aprovação técnica. O "actor" é a
identidade validada no SSO (sso.Identity); usuários e roles são administrados no SSO.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import ActualHours, Estimate, ParameterSet, Project, User
from engine import ENGINE_VERSION, calculate_project
from models import Parameters, Project as ProjectInput
from schemas import ActualsUpdate, ParameterSetCreate, ProjectCreate, ProjectUpdate
from sso import Identity as Actor

APPROVERS = ("tech_leader", "admin")


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    status_code = 404


class Forbidden(ServiceError):
    status_code = 403


class Conflict(ServiceError):
    status_code = 409


class BusinessRuleError(ServiceError):
    status_code = 422


def require_profile(actor: Actor, profiles: tuple[str, ...], action: str) -> None:
    if actor.profile not in profiles:
        raise Forbidden(f"O perfil {actor.profile} não pode {action}.")


def _get(session: Session, model, entity_id: uuid.UUID, label: str):
    entity = session.get(model, entity_id)
    if entity is None:
        raise NotFound(f"{label} não encontrado(a): {entity_id}")
    return entity


def _commit_or_conflict(session: Session, message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(message) from exc


# Usuários

def upsert_user(session: Session, identity: Actor) -> None:
    """Espelha no banco local o usuário validado no SSO (necessário para created_by/approved_by)."""
    values = {"id": identity.id, "name": identity.name, "email": identity.email}
    session.execute(insert(User).values(**values).on_conflict_do_update(
        index_elements=[User.id], set_={"name": identity.name, "email": identity.email, "last_seen_at": func.now()}))
    session.commit()


# Parâmetros

def current_parameter_set(session: Session) -> ParameterSet | None:
    return session.scalars(
        select(ParameterSet).where(ParameterSet.effective_at <= func.now())
        .order_by(ParameterSet.effective_at.desc()).limit(1)
    ).first()


def require_current_parameter_set(session: Session) -> ParameterSet:
    parameter_set = current_parameter_set(session)
    if parameter_set is None:
        raise Conflict("Nenhum conjunto de parâmetros vigente; um administrador precisa cadastrar um.")
    return parameter_set


def list_parameter_sets(session: Session) -> list[ParameterSet]:
    return list(session.scalars(select(ParameterSet).order_by(ParameterSet.effective_at.desc())))


def create_parameter_set(session: Session, actor: Actor, data: ParameterSetCreate) -> ParameterSet:
    require_profile(actor, ("admin",), "administrar parâmetros")
    parameter_set = ParameterSet(
        version=data.content.config_version,
        content=data.content.model_dump(mode="json", exclude_none=True),
        created_by=actor.id,
    )
    if data.effective_at is not None:
        parameter_set.effective_at = data.effective_at
    session.add(parameter_set)
    _commit_or_conflict(session, f"Já existe um conjunto de parâmetros na versão {data.content.config_version}; "
                                 "altere config_version.")
    return parameter_set


# Projetos

def get_project(session: Session, project_id: uuid.UUID) -> Project:
    return _get(session, Project, project_id, "Projeto")


# Revisão técnica (Tela 4): o PO cadastra funcionalidades e critérios de aceite e só visualiza a
# parte técnica do escopo, que é definida pelo Tech Leader (ou administrador).
TECHNICAL_EDITORS = ("tech_leader", "admin")


def _technical_scope(content: dict) -> dict:
    """Parte técnica do escopo: tarefas/atividades de cada funcionalidade, transversais e contingência."""
    return {
        "tasks": {feature["id"]: feature.get("tasks", []) for feature in content.get("features", [])},
        "transversal_tasks": content.get("transversal_tasks", []),
        "contingency_rate": content.get("contingency_rate"),
    }


def check_technical_changes(actor: Actor, before: dict, after: dict) -> None:
    if actor.profile in TECHNICAL_EDITORS:
        return
    old, new = _technical_scope(before), _technical_scope(after)
    if old["transversal_tasks"] != new["transversal_tasks"]:
        raise Forbidden(f"O perfil {actor.profile} só visualiza as atividades transversais; "
                        "elas são definidas na revisão técnica.")
    if old["contingency_rate"] != new["contingency_rate"]:
        raise Forbidden(f"O perfil {actor.profile} só consulta a contingência; ela é um parâmetro técnico.")
    for feature_id in old["tasks"].keys() | new["tasks"].keys():
        if old["tasks"].get(feature_id, []) != new["tasks"].get(feature_id, []):
            raise Forbidden(f"O perfil {actor.profile} cadastra e edita funcionalidades, mas tarefas e atividades "
                            f"(funcionalidade {feature_id}) são definidas na revisão técnica.")


def create_project(session: Session, actor: Actor, data: ProjectCreate) -> Project:
    content = data.content.model_dump(mode="json", exclude_none=True)
    check_technical_changes(actor, {}, content)
    project = Project(name=data.name, objective=data.objective, created_by=actor.id, content=content)
    session.add(project)
    session.commit()
    return project


def update_project(session: Session, actor: Actor, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
    project = get_project(session, project_id)
    changes = data.model_dump(exclude_unset=True, exclude={"content"})
    for field, value in changes.items():
        setattr(project, field, value)
    if data.content is not None:
        content = data.content.model_dump(mode="json", exclude_none=True)
        if content != project.content:
            check_technical_changes(actor, project.content, content)
            project.content = content
            project.revision += 1
    session.commit()
    return project


def list_projects(session: Session) -> list[tuple[Project, Estimate | None, Estimate | None]]:
    """Projetos com a última estimativa e a última aprovada (painel de projetos)."""
    projects = list(session.scalars(select(Project).order_by(Project.updated_at.desc())))
    last_per_project = (select(Estimate).ext(distinct_on(Estimate.project_id))
                        .order_by(Estimate.project_id, Estimate.version.desc()))
    latest = {e.project_id: e for e in session.scalars(last_per_project)}
    approved = {e.project_id: e for e in session.scalars(last_per_project.where(Estimate.status == "approved"))}
    return [(p, latest.get(p.id), approved.get(p.id)) for p in projects]


def engine_input(project: Project) -> dict:
    """Entrada do motor para o projeto, validada pelo contrato."""
    payload = {"project_id": str(project.id), "name": project.name, **project.content}
    return ProjectInput.model_validate(payload).model_dump(mode="json", exclude_none=True)


# Estimativas

def _calculate(snapshot: dict, parameters: dict) -> dict:
    try:
        return calculate_project(snapshot, parameters)
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc


def simulate(session: Session, project: ProjectInput, parameters: Parameters | None) -> dict:
    """Cálculo sem registro; sem parâmetros informados, usa os vigentes."""
    content = (parameters.model_dump(mode="json", exclude_none=True) if parameters
               else require_current_parameter_set(session).content)
    return _calculate(project.model_dump(mode="json", exclude_none=True), content)


def get_estimate(session: Session, estimate_id: uuid.UUID) -> Estimate:
    return _get(session, Estimate, estimate_id, "Estimativa")


def list_estimates(session: Session, project_id: uuid.UUID) -> list[Estimate]:
    return get_project(session, project_id).estimates


def create_estimate(session: Session, actor: Actor, project_id: uuid.UUID) -> Estimate:
    # Bloqueia o projeto para que duas requisições simultâneas não disputem o mesmo número de versão.
    project = session.scalars(select(Project).where(Project.id == project_id).with_for_update()).first()
    if project is None:
        raise NotFound(f"Projeto não encontrado(a): {project_id}")
    if project.status == "archived":
        raise Conflict("Projeto arquivado não recebe novas estimativas.")
    parameter_set = require_current_parameter_set(session)
    snapshot = engine_input(project)
    result = _calculate(snapshot, parameter_set.content)
    last_version = session.scalar(select(func.max(Estimate.version)).where(Estimate.project_id == project.id))
    summary = result["summary"]
    estimate = Estimate(
        project_id=project.id, version=(last_version or 0) + 1, project_revision=project.revision,
        project_snapshot=snapshot, parameter_set_id=parameter_set.id, engine_version=ENGINE_VERSION,
        result=result, created_by=actor.id,
        base_total_hours=summary["base_total_hours"], ai_total_hours=summary["ai_total_hours"],
        base_total_cost=summary["base_total_cost"], ai_total_cost=summary["ai_total_cost"],
    )
    session.add(estimate)
    session.commit()
    return estimate


def approve_estimate(session: Session, actor: Actor, estimate_id: uuid.UUID) -> Estimate:
    require_profile(actor, APPROVERS, "aprovar estimativas")
    estimate = get_estimate(session, estimate_id)
    if estimate.status == "approved":
        raise Conflict("A estimativa já está aprovada.")
    if estimate.project_revision != estimate.project.revision:
        raise Conflict(f"Os requisitos mudaram desde esta estimativa (revisão {estimate.project_revision}, "
                       f"atual {estimate.project.revision}); gere uma nova estimativa antes de aprovar.")
    estimate.status = "approved"
    estimate.approved_by = actor.id
    estimate.approved_at = datetime.now(timezone.utc)
    session.commit()
    return estimate


def check_reproduction(session: Session, estimate_id: uuid.UUID) -> dict:
    """Recalcula o snapshot com os parâmetros registrados e compara com o resultado guardado."""
    estimate = get_estimate(session, estimate_id)
    try:
        recalculated = calculate_project(estimate.project_snapshot, estimate.parameter_set.content)
    except ValueError:
        recalculated = None
    return {
        "estimate_id": estimate.id,
        "engine_version_recorded": estimate.engine_version,
        "engine_version_current": ENGINE_VERSION,
        "reproducible": recalculated == estimate.result,
    }


# Horas realizadas e calibração (Módulo 5)

SMALL_SAMPLE = 10


def list_actuals(session: Session, estimate_id: uuid.UUID) -> list[ActualHours]:
    get_estimate(session, estimate_id)
    return list(session.scalars(select(ActualHours).where(ActualHours.estimate_id == estimate_id)
                                .order_by(ActualHours.task_id, ActualHours.activity_id)))


def save_actuals(session: Session, actor: Actor, estimate_id: uuid.UUID, data: ActualsUpdate) -> list[ActualHours]:
    """Registra/atualiza as horas realizadas de atividades de uma estimativa aprovada."""
    require_profile(actor, APPROVERS, "registrar horas realizadas")
    estimate = get_estimate(session, estimate_id)
    if estimate.status != "approved":
        raise Conflict("Horas realizadas só podem ser registradas em estimativas aprovadas.")
    known = {(row["task_id"], row["activity_id"]) for row in estimate.result["activities"]}
    for item in data.items:
        if (item.task_id, item.activity_id) not in known:
            raise BusinessRuleError(f"Atividade {item.task_id}/{item.activity_id} não existe nesta estimativa.")
    for item in data.items:
        values = {"actual_hours": item.actual_hours, "ai_used": item.ai_used, "notes": item.notes,
                  "recorded_by": actor.id}
        session.execute(insert(ActualHours).values(
            id=uuid.uuid4(), estimate_id=estimate_id, task_id=item.task_id, activity_id=item.activity_id, **values,
        ).on_conflict_do_update(constraint="uq_actual_hours_activity", set_={**values, "updated_at": func.now()}))
    session.commit()
    return list_actuals(session, estimate_id)


def _group(key: str, pairs: list[tuple[float, float]]) -> dict:
    estimated = sum(e for e, _ in pairs)
    actual = sum(a for _, a in pairs)
    errors = [abs(a - e) / e * 100 for e, a in pairs if e > 0]
    return {"key": key, "count": len(pairs), "estimated_hours": round(estimated, 2), "actual_hours": round(actual, 2),
            "ratio": round(actual / estimated, 3) if estimated > 0 else None,
            "mean_abs_pct_error": round(sum(errors) / len(errors), 1) if errors else None}


def calibration_report(session: Session) -> dict:
    """Estimado × realizado por tipo de atividade e por modalidade de IA efetivamente usada."""
    rows = session.execute(select(ActualHours, Estimate).join(Estimate, ActualHours.estimate_id == Estimate.id)).all()
    by_type: dict[str, list[tuple[float, float]]] = {}
    by_modality: dict[str, list[tuple[float, float]]] = {}
    overall: list[tuple[float, float]] = []
    estimates: set[uuid.UUID] = set()
    for actual, estimate in rows:
        activity = next((r for r in estimate.result["activities"]
                         if r["task_id"] == actual.task_id and r["activity_id"] == actual.activity_id), None)
        if activity is None:
            continue
        # Compara com o cenário executado: horas com IA se a IA foi usada, senão horas sem IA.
        estimated = activity["ai_hours"] if actual.ai_used else activity["base_hours"]
        modality = activity["ai_modality"] if actual.ai_used and activity["ai_applied"] else "sem_ia"
        pair = (float(estimated), float(actual.actual_hours))
        by_type.setdefault(activity["activity_type"], []).append(pair)
        by_modality.setdefault(modality, []).append(pair)
        overall.append(pair)
        estimates.add(estimate.id)
    return {
        "overall": _group("geral", overall),
        "by_activity_type": [_group(k, v) for k, v in sorted(by_type.items())],
        "by_ai_modality": [_group(k, v) for k, v in sorted(by_modality.items())],
        "estimates_count": len(estimates),
        "small_sample": len(overall) < SMALL_SAMPLE,
    }
