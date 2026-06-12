"""SQLAlchemy 引擎与会话工厂.

2026-06-12: engine/SessionLocal 改为**延迟创建** (get_engine/get_sessionmaker +
lru_cache) — import app.* 不再锁定 DB URL, "先 import 后设 BWS_DATABASE_URL"
也生效, 测试不需要 sys.modules reload hack. 旧名 `engine` / `SessionLocal`
通过模块级 __getattr__ (PEP 562) 兼容, 函数内 `from ..database import engine`
每次都取到当前引擎.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类."""


@lru_cache(maxsize=None)
def get_engine() -> Engine:
    url = settings.database_url
    return create_engine(
        url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )


@lru_cache(maxsize=None)
def get_sessionmaker() -> sessionmaker:
    return sessionmaker(
        bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False
    )


def __getattr__(name: str):
    # PEP 562: 兼容旧用法 `from .database import engine / SessionLocal`
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_sessionmaker()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """命令行脚本用 — 自动提交+回滚."""
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """建表 (Base.metadata.create_all, idempotent) + 自举 super_admin.

    2026-05-16 起 schema 变更**只走 alembic**:
      - 新增字段: 改 ORM 模型 → `alembic revision --autogenerate -m "..."` → `bws db migrate`
      - 老 v0.7 → v0.8 的 ALTER 兼容列表已删除. 本仓库实际使用场景是单一用户单一 DB
        (已跑过所有 ALTER), 第三方从 v0.7 升级请走 alembic baseline + 写 0001 迁移.
    """
    from . import models  # noqa: F401  确保模型都注册
    Base.metadata.create_all(bind=get_engine())
    _ensure_bootstrap_admin()
    _ensure_gamble_strategies_synced()


def _ensure_gamble_strategies_synced() -> None:
    """启动同步: seed.py 里有新策略条目时, 把缺的补上 (按 name 幂等)."""
    from .seed import _seed_gamble_strategies
    db = get_sessionmaker()()
    try:
        _seed_gamble_strategies(db)
        db.commit()
    except Exception:
        db.rollback()
        import logging
        logging.getLogger("bws.bootstrap").exception("策略同步失败 (非致命)")
    finally:
        db.close()


def _ensure_bootstrap_admin() -> None:
    """v0.8.1: 启动时检查 users 表; 没有 super_admin 就用 .env 自动创建一个.

    幂等: 已有 super_admin 就跳过. 这样首次启动一定有可登录账号.
    """
    from . import models
    from .config import settings as _settings
    db = get_sessionmaker()()
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
