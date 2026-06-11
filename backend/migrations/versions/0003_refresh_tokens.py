"""Add refresh_tokens — APP 端 JWT 双 token 撤销表

Revision ID: 0003_refresh_tokens
Revises: 0002_pricing_seasonal
Create Date: 2026-06-11

v0.10: APP 版本后端增量第一步 (docs/APP版本设计方案_2026-06-11.md 3.1 节).
库里只存 sha256(token), 不存原文.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0003_refresh_tokens"
down_revision = "0002_pricing_seasonal"
branch_labels = None
depends_on = None


def _table_exists(insp, name: str) -> bool:
    return name in set(insp.get_table_names())


def upgrade() -> None:
    """Idempotent: 表存在则跳过 (init_db 已 create_all 出新表的情况)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _table_exists(insp, "refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("client_info", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
        op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("refresh_tokens")
