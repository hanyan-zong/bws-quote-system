"""Add quote_days.day_type column

Revision ID: 0001_quote_day_day_type
Revises: 0000_baseline
Create Date: 2026-05-19

v0.9.3: QuoteDay 加 day_type 字段 (full/half/arrival/departure).
half/arrival/departure 三种: pricing 引擎按 0.5 天算车导成本.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_quote_day_day_type"
down_revision = "0000_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: init_db (Base.metadata.create_all) 对新 DB 已经按模型建好含 day_type 的表,
    # alembic 跑到这里会发现列已存在 — 跳过避免 "duplicate column" 错误.
    # 老 DB (init_db 在 v0.9.3 之前跑过, 表没有 day_type) 才真正执行 ADD COLUMN.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("quote_days")]
    if "day_type" in cols:
        return
    with op.batch_alter_table("quote_days", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("day_type", sa.String(length=20), nullable=False, server_default="full")
        )


def downgrade() -> None:
    with op.batch_alter_table("quote_days", schema=None) as batch_op:
        batch_op.drop_column("day_type")
