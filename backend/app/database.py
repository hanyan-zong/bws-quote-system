"""SQLAlchemy 引擎与会话工厂."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类."""


engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """命令行脚本用 — 自动提交+回滚."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """建表(不删数据)+ 兼容性 ALTER TABLE 加新列(SQLite v0.2 没有 Alembic)."""
    from . import models  # noqa: F401  确保模型都注册

    Base.metadata.create_all(bind=engine)

    # 增量加列(已存在会忽略错误)— v0.3+ 上 Alembic 后删除
    additive_columns = [
        ("quotes", "arrival_at",         "DATETIME"),
        ("quotes", "departure_at",       "DATETIME"),
        ("quotes", "arrival_airport",    "VARCHAR(8)"),
        ("quotes", "departure_airport",  "VARCHAR(8)"),
        # v0.4 多用户:
        ("quotes", "created_by_user_id", "INTEGER"),
        ("quotes", "agency_id",          "INTEGER"),
        # v0.5 赌自费回写闭环:
        ("gamble_history", "strategy_id",     "INTEGER"),
        ("gamble_history", "feedback_notes",  "TEXT"),
        ("gamble_history", "feedback_at",     "DATETIME"),
        ("gamble_history", "feedback_by",     "INTEGER"),
        # v0.5.1 简化策略 — skip 命中后反向加利润:
        ("gamble_strategies", "extra_profit_cny", "NUMERIC(10,2) DEFAULT 0"),
        # v0.5.2 赌自费 5 维度细分 — 老年人字段:
        ("quotes", "pax_senior", "INTEGER DEFAULT 0"),
        # v0.8 自助注册 + 审核
        ("users", "application_note",     "TEXT"),
        ("users", "requested_agency_name","VARCHAR(120)"),
        ("users", "review_note",          "TEXT"),
        ("users", "reviewed_by_user_id",  "INTEGER"),
        ("users", "reviewed_at",          "DATETIME"),
    ]
    with engine.begin() as conn:
        for table, col, sql_type in additive_columns:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}"))
            except Exception:
                pass  # 列已存在

    # v0.8.1 — 启动时确保至少存在一个 super_admin (从 .env 兜底)
    _ensure_bootstrap_admin()


def _ensure_bootstrap_admin() -> None:
    """v0.8.1: 启动时检查 users 表; 没有 super_admin 就用 .env 自动创建一个.

    幂等: 已有 super_admin 就跳过. 这样首次启动一定有可登录账号.
    """
    from . import models
    from .config import settings as _settings
    db = SessionLocal()
    try:
        existing = db.query(models.User).filter_by(role="super_admin").first()
        if existing is not None:
            return  # 已有, 跳过

        # 建一家 default agency
        agency = db.query(models.Agency).filter_by(name="本社").first()
        if not agency:
            agency = models.Agency(name="本社", short_name="HOME", status="active")
            db.add(agency)
            db.flush()

        # 建 super_admin
        from .routers.auth import _hash_password
        username = _settings.auth_username or "admin"
        password = _settings.auth_password or "admin123"
        # 防止用户名冲突 (如有同名 disabled 用户)
        if db.query(models.User).filter_by(username=username).first():
            return
        user = models.User(
            username=username,
            password_hash=_hash_password(password),
            display_name="超级管理员",
            role="super_admin",
            agency_id=agency.id,
            status="active",
            force_password_change=True,  # 首次登录强制改密
        )
        db.add(user)
        db.flush()

        # 配额初始化 (无限)
        from .utils.feature_permissions import init_quotas_for_user
        init_quotas_for_user(db, user)
        db.commit()

        import logging
        logging.getLogger("bws.bootstrap").warning(
            "✓ 已自动创建初始 super_admin 账号: username=%s password=%s "
            "(请首次登录后立即改密!)", username, password,
        )
    finally:
        db.close()
