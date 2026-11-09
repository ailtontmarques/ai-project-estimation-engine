"""Identidade via SSO: users vira espelho local do usuário do UNE AI SSO.

- id passa a ser o sub do token do SSO (sem default gerado localmente);
- profile sai: o perfil é calculado a cada requisição a partir das roles no SSO;
- email deixa de ser único: a fonte de verdade da identidade é o SSO;
- last_seen_at registra o último acesso validado.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_users_profile", "users", type_="check")
    op.drop_column("users", "profile")
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.alter_column("users", "id", server_default=None)
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                                     server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_column("users", "last_seen_at")
    op.alter_column("users", "id", server_default=sa.text("gen_random_uuid()"))
    op.create_unique_constraint("users_email_key", "users", ["email"])
    op.add_column("users", sa.Column("profile", sa.Text, nullable=False, server_default="product_owner"))
    op.create_check_constraint("ck_users_profile", "users", "profile IN ('product_owner', 'tech_leader', 'admin')")
