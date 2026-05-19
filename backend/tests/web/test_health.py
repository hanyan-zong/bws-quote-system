"""Smoke: web app 起得来 + 健康检查."""
from __future__ import annotations


def test_health_returns_v0_9(web_client):
    r = web_client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["version"].startswith("0.9.")
    assert data["version_label"].startswith("v0.9")


def test_health_no_auth_required(web_client):
    """健康检查不应需要登录."""
    r = web_client.get("/api/v1/health")
    assert r.status_code == 200
