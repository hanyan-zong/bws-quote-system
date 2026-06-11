"""v0.10 APP 端双 token 认证测试 — /auth/token /auth/refresh /auth/logout + Bearer 通道.

设计依据: docs/APP版本设计方案_2026-06-11.md 3.1 节.
"""
from __future__ import annotations

import hashlib
import time


ADMIN = {"username": "admin", "password": "admin123"}


def _issue_pair(client) -> dict:
    r = client.post("/api/v1/auth/token", json=ADMIN)
    assert r.status_code == 200, f"token issue failed: {r.status_code} {r.text}"
    return r.json()


# ============================================================
#  签发
# ============================================================
def test_token_returns_pair_for_valid_credentials(web_client):
    data = _issue_pair(web_client)

    assert data["token_type"] == "bearer"
    assert data["access_token"].count(".") == 2
    assert len(data["refresh_token"]) > 40
    assert data["expires_in"] == 30 * 60
    assert data["refresh_expires_in"] == 14 * 86400
    assert data["user"]["username"] == "admin"


def test_token_rejects_wrong_password(web_client):
    r = web_client.post("/api/v1/auth/token", json={"username": "admin", "password": "wrong-pass"})
    assert r.status_code == 401


def test_refresh_token_stored_as_sha256_not_plaintext(web_client):
    from app.database import SessionLocal
    from app import models

    data = _issue_pair(web_client)
    plain = data["refresh_token"]

    db = SessionLocal()
    try:
        expected_hash = hashlib.sha256(plain.encode()).hexdigest()
        row = db.query(models.RefreshToken).filter_by(token_hash=expected_hash).first()
        assert row is not None, "库里应存 sha256(token)"
        assert db.query(models.RefreshToken).filter_by(token_hash=plain).first() is None, "不允许存原文"
        assert row.expires_at is not None and row.revoked_at is None
    finally:
        db.close()


# ============================================================
#  Bearer 通道
# ============================================================
def test_bearer_access_token_grants_api_access(web_client):
    data = _issue_pair(web_client)

    r = web_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_garbage_bearer_token_rejected(web_client):
    r = web_client.get("/api/v1/quotes", headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 401


def test_expired_access_token_rejected(web_client):
    from app.routers.auth import _sign

    expired_payload = f"1.{int(time.time()) - 10}"
    expired_token = f"{expired_payload}.{_sign(expired_payload)}"

    r = web_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert r.status_code == 401


# ============================================================
#  旋转刷新 + 重放防护
# ============================================================
def test_refresh_rotates_token_pair(web_client):
    old = _issue_pair(web_client)

    r = web_client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != old["refresh_token"]

    # 新 access 可用
    r2 = web_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new['access_token']}"},
    )
    assert r2.status_code == 200

    # 旧 refresh 已作废
    r3 = web_client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert r3.status_code == 401


def test_revoked_refresh_reuse_revokes_all_sessions(web_client):
    pair_a = _issue_pair(web_client)
    refreshed = web_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": pair_a["refresh_token"]}
    ).json()

    # 重放已作废的旧 refresh → 该用户全部 refresh 被撤销
    r = web_client.post("/api/v1/auth/refresh", json={"refresh_token": pair_a["refresh_token"]})
    assert r.status_code == 401

    r2 = web_client.post("/api/v1/auth/refresh", json={"refresh_token": refreshed["refresh_token"]})
    assert r2.status_code == 401, "重放后同用户后发的 refresh 也应被连坐撤销"


def test_unknown_refresh_token_rejected(web_client):
    r = web_client.post("/api/v1/auth/refresh", json={"refresh_token": "x" * 64})
    assert r.status_code == 401


# ============================================================
#  Logout 撤销
# ============================================================
def test_logout_revokes_refresh_token(web_client):
    data = _issue_pair(web_client)

    r = web_client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 200

    r2 = web_client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r2.status_code == 401


def test_logout_without_body_still_works(web_client):
    """web 端 logout (无 body) 不能因新增 body 参数而破."""
    r = web_client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    assert r.json()["ok"] is True
