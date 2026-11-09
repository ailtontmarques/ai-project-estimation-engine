"""Contratos HTTP da camada de persistência (entrada e saída das rotas de cadastro e fluxo)."""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models import EstimateResult, Parameters, Project, ProjectContent, Strict

Profile = Literal["product_owner", "tech_leader", "admin"]
ProjectStatus = Literal["active", "archived"]
EstimateStatus = Literal["draft", "approved"]


class FromORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Autenticação (proxy do SSO)

class LoginRequest(Strict):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class RefreshRequest(Strict):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(Strict):
    refresh_token: str | None = Field(default=None, description="Omitido: o SSO revoga todos os refresh tokens do usuário")


class TokenResponse(Strict):
    access_token: str
    refresh_token: str | None
    expires_in: int = Field(description="Validade do access token, em segundos")
    token_type: str


class MeOut(FromORM):
    id: UUID
    email: str
    name: str
    profile: Profile = Field(description="Perfil no app, derivado das roles do usuário no SSO")
    roles: list[str] = Field(description="Roles do usuário no domínio do app no SSO")


# Parâmetros

class ParameterSetCreate(Strict):
    content: Parameters
    effective_at: datetime | None = Field(default=None, description="Início da vigência; omitido = imediato")


class ParameterSetBrief(FromORM):
    id: UUID
    version: str
    effective_at: datetime
    created_by: UUID | None
    created_at: datetime


class ParameterSetOut(ParameterSetBrief):
    content: Parameters


# Projetos

class ProjectCreate(Strict):
    name: str = Field(min_length=1)
    objective: str | None = None
    content: ProjectContent = ProjectContent()


class ProjectUpdate(Strict):
    """Campos omitidos não mudam. Alterar content gera uma nova revisão dos requisitos."""
    name: str | None = Field(default=None, min_length=1)
    objective: str | None = None
    status: ProjectStatus | None = None
    content: ProjectContent | None = None


class EstimateBrief(FromORM):
    id: UUID
    project_id: UUID
    version: int
    status: EstimateStatus
    project_revision: int
    parameter_set_id: UUID
    parameters_version: str
    engine_version: str
    base_total_hours: float
    ai_total_hours: float
    base_total_cost: float
    ai_total_cost: float
    created_by: UUID
    created_at: datetime
    approved_by: UUID | None
    approved_at: datetime | None


class EstimateOut(EstimateBrief):
    project_snapshot: Project
    result: EstimateResult


class ProjectOut(FromORM):
    id: UUID
    name: str
    objective: str | None
    status: ProjectStatus
    revision: int
    content: ProjectContent
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class ProjectListItem(Strict):
    id: UUID
    name: str
    objective: str | None
    status: ProjectStatus
    revision: int
    feature_count: int
    latest_estimate: EstimateBrief | None
    approved_estimate: EstimateBrief | None = Field(description="Última versão aprovada, se houver")
    updated_at: datetime


# Decomposição assistida por IA (sugestão; nada é salvo)

class SuggestedActivity(Strict):
    name: str
    activity_type: str
    ai_modality: str | None = None
    optimistic_hours: float
    most_likely_hours: float
    pessimistic_hours: float
    allocations: dict[str, dict[str, float]]
    rationale: str = Field(description="Justificativa da IA para a atividade e as horas sugeridas")


class SuggestedTask(Strict):
    name: str
    activities: list[SuggestedActivity]


class DecompositionOut(Strict):
    tasks: list[SuggestedTask]
    open_questions: list[str]
    risks: list[str]
    assumptions: list[str]
    warnings: list[str] = Field(description="Ajustes feitos na sugestão para respeitar os parâmetros vigentes")
    model: str


# Horas realizadas e calibração (Módulo 5)

class ActualIn(Strict):
    task_id: str
    activity_id: str
    actual_hours: float = Field(ge=0)
    ai_used: bool = Field(description="A atividade foi executada com IA? Define o cenário estimado comparado")
    notes: str | None = None


class ActualsUpdate(Strict):
    items: list[ActualIn]


class ActualOut(FromORM):
    task_id: str
    activity_id: str
    actual_hours: float
    ai_used: bool
    notes: str | None
    recorded_by: UUID
    recorded_at: datetime
    updated_at: datetime


class CalibrationGroup(Strict):
    key: str
    count: int = Field(description="Atividades com horas realizadas registradas")
    estimated_hours: float = Field(description="Soma das horas estimadas no cenário executado (com ou sem IA)")
    actual_hours: float
    ratio: float | None = Field(description="Realizado ÷ estimado; acima de 1 = estimativa otimista")
    mean_abs_pct_error: float | None = Field(description="Erro percentual absoluto médio por atividade (MAPE, %)")


class CalibrationReport(Strict):
    overall: CalibrationGroup
    by_activity_type: list[CalibrationGroup]
    by_ai_modality: list[CalibrationGroup] = Field(description='Modalidade efetivamente usada; "sem_ia" quando não usou')
    estimates_count: int
    small_sample: bool = Field(description="Menos de 10 atividades: serve para levantar hipóteses, não para recalibrar")


class ReproductionCheck(Strict):
    estimate_id: UUID
    engine_version_recorded: str
    engine_version_current: str
    reproducible: bool = Field(description="Recalcular o snapshot com os parâmetros registrados dá o mesmo resultado")
