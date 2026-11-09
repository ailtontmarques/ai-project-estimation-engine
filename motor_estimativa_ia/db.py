"""Persistência (SQLAlchemy 2 + Postgres).

Tabelas relacionais para o que exige integridade e fluxo (usuários, parâmetros, projetos,
estimativas e aprovação). O conteúdo do projeto e o resultado do motor ficam em JSONB,
validados pelos modelos de models.py. O esquema é criado pelas migrações em migrations/.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv
from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Numeric, Text, UniqueConstraint,
                        create_engine, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

load_dotenv(Path(__file__).with_name(".env"))

PROJECT_STATUSES = ("active", "archived")
ESTIMATE_STATUSES = ("draft", "approved")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), dict[str, Any]: JSONB, uuid.UUID: UUID(as_uuid=True)}


class User(Base):
    """Espelho local da identidade do SSO (id = sub do token), usado nos vínculos de auditoria.

    O perfil não é guardado: é calculado a cada requisição a partir das roles do usuário no SSO.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ParameterSet(Base):
    """Versão imutável dos parâmetros; a vigente é a de maior effective_at já alcançado."""
    __tablename__ = "parameter_sets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(Text, unique=True)
    content: Mapped[dict[str, Any]]
    effective_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint(_in("status", PROJECT_STATUSES), name="ck_projects_status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    # Versão dos requisitos: incrementa a cada alteração de content.
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    content: Mapped[dict[str, Any]]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    estimates: Mapped[list[Estimate]] = relationship(back_populates="project", order_by="Estimate.version")


class Estimate(Base):
    """Cálculo registrado: snapshot exato da entrada, parâmetros usados e resultado do motor."""
    __tablename__ = "estimates"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_estimates_project_version"),
        CheckConstraint(_in("status", ESTIMATE_STATUSES), name="ck_estimates_status"),
        CheckConstraint("status = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
                        name="ck_estimates_approval"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    version: Mapped[int]
    status: Mapped[str] = mapped_column(Text, default="draft", server_default="draft")
    project_revision: Mapped[int]
    project_snapshot: Mapped[dict[str, Any]]
    parameter_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parameter_sets.id"))
    engine_version: Mapped[str] = mapped_column(Text)
    result: Mapped[dict[str, Any]]
    # Totais desnormalizados para listagens e painel.
    base_total_hours: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    ai_total_hours: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    base_total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ai_total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None]

    project: Mapped[Project] = relationship(back_populates="estimates")
    parameter_set: Mapped[ParameterSet] = relationship()

    @property
    def parameters_version(self) -> str:
        return self.parameter_set.version


class ActualHours(Base):
    """Horas realizadas de uma atividade de estimativa aprovada (Módulo 5: histórico e calibração)."""
    __tablename__ = "actual_hours"
    __table_args__ = (
        UniqueConstraint("estimate_id", "task_id", "activity_id", name="uq_actual_hours_activity"),
        CheckConstraint("actual_hours >= 0", name="ck_actual_hours_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("estimates.id"), index=True)
    task_id: Mapped[str] = mapped_column(Text)
    activity_id: Mapped[str] = mapped_column(Text)
    actual_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Se a atividade foi de fato executada com IA: define com qual cenário estimado ela é comparada.
    ai_used: Mapped[bool]
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    estimate: Mapped[Estimate] = relationship()


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or os.environ["DATABASE_URL"], pool_pre_ping=True)


@lru_cache
def get_sessionmaker(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(get_engine(url), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependência FastAPI: uma sessão por requisição."""
    with get_sessionmaker()() as session:
        yield session
