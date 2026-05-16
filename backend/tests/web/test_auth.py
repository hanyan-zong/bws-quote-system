"""Auth endpoint 测试 — login / me / logout."""
from __future__ import annotations


def test_me_without_cookie_is_401(web_client):
    r = web_client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_login_wrong_password_is_401(web_client):
    r = web_client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong_password_xx"})
    assert r.status_code == 401


def test_login_unknown_user_is_401(web_client):
    r = web_client.post(
        "/api/v1/auth/login",
        json={"username": "nosuchuser_xyz_999", "password": "whatever"},
    )
    assert r.status_code == 401


def test_login_then_me_returns_admin(admin_client):
    """admin_client fixture 已经 login 了, /me 应当返回 admin 信息."""
    r = admin_client.get("/api/v1/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "admin"
    assert data["role"] == "super_admin"


def test_logout_then_me_is_401(admin_client):
    r = admin_client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # cookies 应当被清掉
    r2 = admin_client.get("/api/v1/auth/me")
    assert r2.status_code == 401


def test_status_endpoint_public(web_client):
    """/status 不需要登录, 用于前端启动检查."""
    r = web_client.get("/api/v1/auth/status")
    assert r.status_code == 200
    data = r.json()
    assert "auth_required" in data
    assert "authenticated" in data
