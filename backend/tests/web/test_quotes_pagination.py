"""v0.10 GET /quotes 分页测试 — page 参数开关信封格式, 老裸数组行为不破.

注意: web 测试 session 共享 tmp DB, total 含其他测试建的数据 — 断言用 >= 不用 ==.
"""
from __future__ import annotations


def _create_quote(client, agency_name: str) -> dict:
    r = client.post(
        "/api/v1/quotes",
        json={"agency_name": agency_name, "pax_adult": 2, "customer_type": "family"},
    )
    assert r.status_code == 200, f"create failed: {r.text}"
    return r.json()


def test_list_without_page_keeps_legacy_array(admin_client):
    """web 前端依赖裸数组 — page 缺省时格式不能变."""
    _create_quote(admin_client, "PagLegacy")

    r = admin_client.get("/api/v1/quotes")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_with_page_returns_envelope(admin_client):
    _create_quote(admin_client, "PagEnvelope")

    r = admin_client.get("/api/v1/quotes?page=1&size=5")
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"items", "total", "page", "size", "pages"}
    assert data["page"] == 1
    assert data["size"] == 5
    assert len(data["items"]) <= 5
    assert data["total"] >= 1
    assert data["pages"] >= 1


def test_pagination_slices_without_overlap(admin_client):
    for i in range(3):
        _create_quote(admin_client, f"PagSlice{i}")

    p1 = admin_client.get("/api/v1/quotes?page=1&size=2").json()
    p2 = admin_client.get("/api/v1/quotes?page=2&size=2").json()

    assert len(p1["items"]) == 2
    assert p1["total"] >= 3
    assert p1["total"] == p2["total"]
    ids_p1 = {x["id"] for x in p1["items"]}
    ids_p2 = {x["id"] for x in p2["items"]}
    assert not ids_p1 & ids_p2, "两页之间不允许重复条目"
    # 默认排序 created_at desc — 最新建的在第一页
    assert (p1["total"] + 1) // 2 == p1["pages"] or p1["pages"] == -(-p1["total"] // 2)


def test_page_size_clamped_to_100(admin_client):
    r = admin_client.get("/api/v1/quotes?page=1&size=999")
    assert r.status_code == 200
    assert r.json()["size"] == 100


def test_page_zero_clamped_to_first_page(admin_client):
    r = admin_client.get("/api/v1/quotes?page=0&size=5")
    assert r.status_code == 200
    assert r.json()["page"] == 1


def test_bearer_token_with_pagination(web_client):
    """APP 真实场景: Bearer access token + 分页参数."""
    token = web_client.post(
        "/api/v1/auth/token", json={"username": "admin", "password": "admin123"}
    ).json()["access_token"]

    r = web_client.get(
        "/api/v1/quotes?page=1&size=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "items" in data and "total" in data
    assert len(data["items"]) <= 3
