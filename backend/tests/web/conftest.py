"""Web 后端 (FastAPI) 测试用 fixtures.

关键: 顶部 set BWS_DATABASE_URL → tmp file, 在 import app.* 之前生效.
这样 app.database.engine 这个 module-level singleton 指向 tmp DB.

整个 session 共享一个 tmp DB (test 之间数据互通) — 用唯一 quote_no/username 前缀隔离.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# ---- MUST set env BEFORE importing any app.* module ----
_TMP_DB_DIR = Path(tempfile.mkdtemp(prefix="bws_web_tests_"))
_TMP_DB_PATH = _TMP_DB_DIR / "test.db"
os.environ["BWS_DATABASE_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ.pop("ANTHROPIC_API_KEY", None)

# 防御性 reload: CLI 测试 (test_cli_data_import_json.py 顶部 `from app.cli.data_cmd import _parse_import_summary`)
# 在 pytest collect 阶段就触发了 app.config import → settings 在 class body 用 os.getenv
# 锁定 database_url 成主 DB. 这里清 sys.modules 让 app.* 重新初始化, settings 拿到 tmp DB.
# CLI 测试用 subprocess, 不受父进程 app.* state 影响, 所以清掉无副作用.
for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]

from fastapi.testclient import TestClient  # noqa: E402

from app.database import engine, init_db  # noqa: E402
from app.main import create_app  # noqa: E402

# Sanity: engine 必须指向 tmp DB, 否则后续测试会污染主 DB
assert str(engine.url).endswith("test.db"), (
    f"engine.url = {engine.url!r} — 期望 tmp DB. "
    f"sys.modules reload 没生效, 检查 app.* import 链"
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
