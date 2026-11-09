"""API HTTP do motor de estimativa.

Uso:
  uvicorn api:app --reload

Autenticação: delegada ao UNE AI SSO. /auth/login, /auth/refresh e /auth/logout repassam ao SSO
no domínio do app (SSO_DOMAIN_SLUG); as demais rotas exigem "Authorization: Bearer <access_token>",
validado no SSO (GET /users/me) com cache curto. O perfil do app vem das roles do usuário no SSO.
"""
from __future__ import annotations
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

import ai
import services
import sso
from db import get_session
from engine import ENGINE_VERSION
from models import EstimateResult, Parameters, Project
from schemas import (ActualOut, ActualsUpdate, CalibrationReport, DecompositionOut, EstimateBrief, EstimateOut, LoginRequest, LogoutRequest, MeOut, ParameterSetBrief,
                     ParameterSetCreate, ParameterSetOut, ProjectCreate, ProjectListItem, ProjectOut,
                     ProjectUpdate, RefreshRequest, ReproductionCheck, TokenResponse)

app = FastAPI(title="Motor de estimativa de esforço e custos", version=ENGINE_VERSION)

SessionDep = Annotated[Session, Depends(get_session)]
SSODep = Annotated[sso.SSOClient, Depends(sso.get_sso_client)]
bearer = HTTPBearer(auto_error=False, description="Access token emitido pelo UNE AI SSO (POST /auth/login)")
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


@app.exception_handler(services.ServiceError)
def service_error_handler(_: Request, exc: services.ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(sso.SSOError)
def sso_error_handler(_: Request, exc: sso.SSOError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message}, headers=headers)


def bearer_token(credentials: CredentialsDep) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Informe o access token (Authorization: Bearer).",
                            headers={"WWW-Authenticate": "Bearer"})
    return credentials.credentials


TokenDep = Annotated[str, Depends(bearer_token)]


def current_user(session: SessionDep, client: SSODep, token: TokenDep) -> sso.Identity:
    return client.authenticate(token, on_new=lambda identity: services.upsert_user(session, identity))


UserDep = Annotated[sso.Identity, Depends(current_user)]


class EstimateRequest(BaseModel):
    project: Project
    parameters: Parameters | None = None  # omitido: usa os parâmetros vigentes; informado: simulação


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine_version": ENGINE_VERSION}


# Autenticação

@app.post("/auth/login", response_model=TokenResponse, summary="Login com e-mail e senha no SSO")
def login(data: LoginRequest, client: SSODep):
    return client.login(data.email, data.password)


@app.post("/auth/refresh", response_model=TokenResponse, summary="Renovar o access token (o SSO rotaciona o refresh)")
def refresh(data: RefreshRequest, client: SSODep):
    return client.refresh(data.refresh_token)


@app.post("/auth/logout", status_code=204, summary="Encerrar a sessão no SSO")
def logout(client: SSODep, token: TokenDep, data: LogoutRequest | None = None) -> Response:
    client.logout(token, data.refresh_token if data else None)
    return Response(status_code=204)


@app.post("/estimate", response_model=EstimateResult, summary="Simular uma estimativa sem registrá-la")
def estimate(request: EstimateRequest, session: SessionDep, _: UserDep) -> EstimateResult:
    return EstimateResult.model_validate(services.simulate(session, request.project, request.parameters))


# Usuários

@app.get("/users/me", response_model=MeOut)
def get_me(user: UserDep) -> sso.Identity:
    return user


# Parâmetros

@app.get("/parameter-sets", response_model=list[ParameterSetBrief])
def list_parameter_sets(session: SessionDep, _: UserDep):
    return services.list_parameter_sets(session)


@app.get("/parameter-sets/current", response_model=ParameterSetOut)
def get_current_parameter_set(session: SessionDep, _: UserDep):
    return services.require_current_parameter_set(session)


@app.post("/parameter-sets", response_model=ParameterSetOut, status_code=201)
def create_parameter_set(data: ParameterSetCreate, session: SessionDep, user: UserDep):
    return services.create_parameter_set(session, user, data)


# Projetos

@app.get("/projects", response_model=list[ProjectListItem])
def list_projects(session: SessionDep, _: UserDep) -> list[ProjectListItem]:
    return [
        ProjectListItem(
            id=p.id, name=p.name, objective=p.objective, status=p.status, revision=p.revision,
            feature_count=len(p.content.get("features", [])), updated_at=p.updated_at,
            latest_estimate=EstimateBrief.model_validate(latest) if latest else None,
            approved_estimate=EstimateBrief.model_validate(approved) if approved else None,
        )
        for p, latest, approved in services.list_projects(session)
    ]


@app.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, session: SessionDep, user: UserDep):
    return services.create_project(session, user, data)


@app.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: UUID, session: SessionDep, _: UserDep):
    return services.get_project(session, project_id)


@app.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: UUID, data: ProjectUpdate, session: SessionDep, user: UserDep):
    return services.update_project(session, user, project_id, data)


@app.post("/projects/{project_id}/features/{feature_id}/decomposition", response_model=DecompositionOut,
          summary="Sugerir tarefas e atividades técnicas com IA (não salva; revisão técnica aplica)")
def suggest_decomposition(project_id: UUID, feature_id: str, session: SessionDep, _: UserDep,
                          decomposer: Annotated[ai.Decomposer, Depends(ai.get_decomposer)]):
    project = services.get_project(session, project_id)
    feature = ai.find_feature(project.content, feature_id)
    if feature is None:
        raise services.NotFound(f"Funcionalidade {feature_id} não encontrada no escopo salvo do projeto.")
    parameters = services.require_current_parameter_set(session).content
    project_data = {"name": project.name, "objective": project.objective, "content": project.content}
    return decomposer.suggest(project_data, feature, parameters)


# Estimativas

@app.get("/projects/{project_id}/estimates", response_model=list[EstimateBrief])
def list_estimates(project_id: UUID, session: SessionDep, _: UserDep):
    return services.list_estimates(session, project_id)


@app.post("/projects/{project_id}/estimates", response_model=EstimateOut, status_code=201,
          summary="Calcular e registrar uma nova versão da estimativa (rascunho)")
def create_estimate(project_id: UUID, session: SessionDep, user: UserDep):
    return services.create_estimate(session, user, project_id)


@app.get("/estimates/{estimate_id}", response_model=EstimateOut)
def get_estimate(estimate_id: UUID, session: SessionDep, _: UserDep):
    return services.get_estimate(session, estimate_id)


@app.post("/estimates/{estimate_id}/approve", response_model=EstimateOut,
          summary="Aprovação técnica explícita (Tech Leader ou administrador)")
def approve_estimate(estimate_id: UUID, session: SessionDep, user: UserDep):
    return services.approve_estimate(session, user, estimate_id)


@app.get("/estimates/{estimate_id}/reproduction", response_model=ReproductionCheck,
         summary="Verificar se o cálculo registrado ainda é reproduzível")
def check_reproduction(estimate_id: UUID, session: SessionDep, _: UserDep):
    return services.check_reproduction(session, estimate_id)


# Horas realizadas e calibração

@app.get("/estimates/{estimate_id}/actuals", response_model=list[ActualOut])
def list_actuals(estimate_id: UUID, session: SessionDep, _: UserDep):
    return services.list_actuals(session, estimate_id)


@app.put("/estimates/{estimate_id}/actuals", response_model=list[ActualOut],
         summary="Registrar horas realizadas de atividades (estimativa aprovada; Tech Leader ou admin)")
def save_actuals(estimate_id: UUID, data: ActualsUpdate, session: SessionDep, user: UserDep):
    return services.save_actuals(session, user, estimate_id, data)


@app.get("/calibration", response_model=CalibrationReport,
         summary="Estimado × realizado por tipo de atividade e modalidade de IA")
def calibration(session: SessionDep, _: UserDep):
    return services.calibration_report(session)
