"""Esquema inicial: usuários, parâmetros, projetos e estimativas, com regras de imutabilidade.

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("profile", sa.Text, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("profile IN ('product_owner', 'tech_leader', 'admin')", name="ck_users_profile"),
    )
    op.create_table(
        "parameter_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version", sa.Text, nullable=False, unique=True),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("effective_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_parameter_sets_effective_at", "parameter_sets", ["effective_at"])
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("objective", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_projects_status"),
    )
    op.create_table(
        "estimates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("project_revision", sa.Integer, nullable=False),
        sa.Column("project_snapshot", JSONB, nullable=False),
        sa.Column("parameter_set_id", UUID(as_uuid=True), sa.ForeignKey("parameter_sets.id"), nullable=False),
        sa.Column("engine_version", sa.Text, nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.Column("base_total_hours", sa.Numeric(12, 2), nullable=False),
        sa.Column("ai_total_hours", sa.Numeric(12, 2), nullable=False),
        sa.Column("base_total_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("ai_total_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("approved_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("approved_at", TIMESTAMP),
        sa.UniqueConstraint("project_id", "version", name="uq_estimates_project_version"),
        sa.CheckConstraint("status IN ('draft', 'approved')", name="ck_estimates_status"),
        sa.CheckConstraint("status = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
                           name="ck_estimates_approval"),
    )

    # RN-07: parâmetros são versões imutáveis; uma mudança gera um novo conjunto.
    op.execute("""
        CREATE FUNCTION forbid_parameter_set_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Conjuntos de parâmetros são imutáveis; crie uma nova versão.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER parameter_sets_immutable BEFORE UPDATE ON parameter_sets
        FOR EACH ROW EXECUTE FUNCTION forbid_parameter_set_update();
    """)

    # RN-07: o cálculo registrado nunca muda; em rascunho só a aprovação pode ser gravada,
    # e uma estimativa aprovada não pode ser alterada nem excluída.
    op.execute("""
        CREATE FUNCTION protect_estimate() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'approved' THEN
                RAISE EXCEPTION 'Estimativa aprovada é imutável (id %).', OLD.id;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            IF (NEW.project_id, NEW.version, NEW.project_revision, NEW.project_snapshot, NEW.parameter_set_id,
                NEW.engine_version, NEW.result, NEW.base_total_hours, NEW.ai_total_hours,
                NEW.base_total_cost, NEW.ai_total_cost, NEW.created_by, NEW.created_at)
               IS DISTINCT FROM
               (OLD.project_id, OLD.version, OLD.project_revision, OLD.project_snapshot, OLD.parameter_set_id,
                OLD.engine_version, OLD.result, OLD.base_total_hours, OLD.ai_total_hours,
                OLD.base_total_cost, OLD.ai_total_cost, OLD.created_by, OLD.created_at) THEN
                RAISE EXCEPTION 'O cálculo de uma estimativa não pode ser alterado; gere uma nova versão.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER estimates_protected BEFORE UPDATE OR DELETE ON estimates
        FOR EACH ROW EXECUTE FUNCTION protect_estimate();
    """)


def downgrade() -> None:
    op.drop_table("estimates")
    op.execute("DROP FUNCTION protect_estimate()")
    op.drop_table("projects")
    op.drop_table("parameter_sets")
    op.execute("DROP FUNCTION forbid_parameter_set_update()")
    op.drop_table("users")
