"""baseline: 2026-05-16 接入 alembic 前的 schema 锁定为 v0 基线

Revision ID: 0000_baseline
Revises:
Create Date: 2026-05-16

策略:
本项目从 v0.1 到 v0.8.x 一直靠 `app.database.init_db()` 的 ALTER TABLE 兼容层
增量加列, 没有迁移版本控制. 2026-05-16 接入 alembic 时不重写历史 —
把当时 init_db() 能建出来的 schema 作为 "baseline (rev=0000)" 锁定,
之后所有 schema 改动走新的 alembic revision (autogenerate 或手写).

upgrade/downgrade 都是 pass:
- 新 DB:  init_db() 已经把表建好, 然后 alembic upgrade 跑空 baseline = 只标记 alembic_version=0000_baseline
- 老 DB:  生产环境一次性手动 `alembic stamp 0000_baseline`, 之后 `bws db migrate` 才会执行 0001+ 的真迁移
"""
from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0000_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
