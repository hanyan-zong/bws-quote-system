"""Web 后端 (FastAPI) 测试用 fixtures.

2026-06-12 起 config.Settings 的 database_url/auth_* 是 property (每次读 env),
database.get_engine 是 lru_cache 延迟创建 — 只要在**第一次建 engine 之前**把
BWS_DATABASE_URL 指到 tmp 文件即可, 不再需要老的 sys.modules reload hack
(老 hack 见 git history: Settings 用 class-level os.getenv, import 即锁定主 DB).

整个 session 共享一个 tmp DB (test 之间数据互通) — 用唯一 quote_no/username 前缀隔离.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# ---- 在任何 app.* 的 engine 被创建前设好 env (lazy 化后时序要求仅此而已) ----
_TMP_DB_DIR = Path(tempfile.mkdtemp(prefix="bws_web_tests_"))
_TMP_DB_PATH = _TMP_DB_DIR / "test.db"
os.environ["BWS_DATABASE_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ.pop("ANTHROPIC_API_KEY", None)
# config.py 的 load_dotenv 会读项目根 .env (BWS_AUTH_PASSWORD=123456 等), 污染测试预期.
# 显式钉死测试认证为默认 admin/admin123.
os.environ["BWS_AUTH_USERNAME"] = "admin"
os.environ["BWS_AUTH_PASSWORD"] = "admin123"
os.environ["BWS_AUTH_SECRET"] = "pytest-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import get_engine, init_db  # noqa: E402
from app.main import create_app  # noqa: E402

# Sanity: engine 必须指向 tmp DB, 否则后续测试会污染主 DB.
# CLI 测试在 collect 阶段 import app.* 不再锁定 URL (lazy), 但如果有人在本 conftest
# 之前就调了 get_engine() (例如未来某 conftest 顶层连库), 这里会立刻报出来.
assert str(get_engine().url).endswith("test.db"), (
    f"engine.url = {get_engine().url!r} — 期望 tmp DB. "
    f"某处在设 BWS_DATABASE_URL 之前就创建了 engine (检查 import 链/其他 conftest)"
)


@pytest.fixture(scope="session", autouse=True)
def _init_session_db():
    """Session 启动时建表 + 自举 admin (admin/admin123)."""
    init_db()
    yield


@pytest.fixture(scope="session")
def web_app():
    return create_app()


@pytest.fixture
def web_client(web_app):
    """每个测试拿一个干净的 TestClient (无 cookies)."""
    return TestClient(web_app)


@pytest.fixture
def admin_client(web_app):
    """带管理员 session cookie 的 client."""
    c = TestClient(web_app)
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return c


@pytest.fixture(scope="session")
def _agent_user():
    """Session-scoped: 直接写库创建一个 agent 角色用户. 跟 admin 同 agency."""
    from app.database import SessionLocal
    from app import models
    from app.routers.auth import _hash_password

    db = SessionLocal()
    try:
        existing = db.query(models.User).filter_by(username="pytest_agent").first()
        if existing:
            return {"username": "pytest_agent", "password": "pytest_agent_pwd"}
        agency = db.query(models.Agency).first()
        assert agency is not None, "需要至少一个 agency (admin bootstrap 应已建本社)"
        u = models.User(
            username="pytest_agent",
            password_hash=_hash_password("pytest_agent_pwd"),
            display_name="pytest agent",
            role="agent",
            agency_id=agency.id,
            status="active",
            force_password_change=False,
        )
        db.add(u)
        db.commit()
        return {"username": "pytest_agent", "password": "pytest_agent_pwd"}
    finally:
        db.close()


@pytest.fixture
def agent_client(web_app, _agent_user):
    """带 agent (普通业务员) session cookie 的 client. v0.9.2 admin gate 测试用."""
    c = TestClient(web_app)
    r = c.post("/api/v1/auth/login", json=_agent_user)
    assert r.status_code == 200, f"agent login failed: {r.status_code} {r.text}"
    return c
