"""Smoke: web app 起得来 + 健康检查."""
from __future__ import annotations


def test_health_returns_current_version(web_client):
    # 不钉死版本号: 与 canonical 的 app.__version__ 对齐, bump 后无需改测试
    from app import __version__

    r = web_client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["version"] == __version__
    assert data["version_label"].startswith(f"v{__version__}")


def test_health_no_auth_required(web_client):
    """健康检查不应需要登录."""
    r = web_client.get("/api/v1/health")
    assert r.status_code == 200
