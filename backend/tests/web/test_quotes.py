"""Quotes endpoint 测试 — create / list / get / calculate."""
from __future__ import annotations


def test_list_quotes_requires_or_works_anon(admin_client):
    """list quotes 应当能正常工作 (admin 看全部)."""
    r = admin_client.get("/api/v1/quotes")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_minimal_quote_returns_id_and_quote_no(admin_client):
    r = admin_client.post(
        "/api/v1/quotes",
        json={
            "agency_name": "TestWebAgency",
            "customer_name": "TestCustomer",
            "pax_adult": 2,
            "destination_codes": ["DPS"],
            "season": "shoulder",
            "customer_type": "family",
        },
    )
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    data = r.json()
    assert "id" in data
    assert "quote_no" in data
    assert data["id"] > 0


def test_create_then_get_quote(admin_client):
    create = admin_client.post(
        "/api/v1/quotes",
        json={"agency_name": "TestGetAgency", "pax_adult": 3, "customer_type": "family"},
    ).json()
    qid = create["id"]

    r = admin_client.get(f"/api/v1/quotes/{qid}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == qid
    assert data["agency_name"] == "TestGetAgency"
    assert data["pax_adult"] == 3


def test_get_missing_quote_is_404(admin_client):
    r = admin_client.get("/api/v1/quotes/99999")
    assert r.status_code == 404


def test_calculate_returns_full_breakdown_schema(admin_client):
    """完整 recalc 必须返回 QuoteCalculateOut 的全部字段 (Step 9 在 CLI 侧已修, web 这边也要守住)."""
    create = admin_client.post(
        "/api/v1/quotes",
        json={
            "agency_name": "TestCalcAgency",
            "pax_adult": 2,
            "destination_codes": ["DPS"],
            "season": "shoulder",
            "customer_type": "family",
        },
    ).json()
    qid = create["id"]

    r = admin_client.post(f"/api/v1/quotes/{qid}/calculate")
    assert r.status_code == 200, f"calculate failed: {r.text}"
    data = r.json()
    # QuoteCalculateOut schema 要求全字段
    required = [
        "quote_id", "quote_no", "cost_idr_total", "cost_cny_total",
        "profit_cny_per_pax", "gamble_cny_per_pax",
        "price_cny_per_pax", "price_cny_total",
        "feasibility_status", "feasibility_report",
    ]
    for field in required:
        assert field in data, f"missing field: {field}"
    assert data["quote_id"] == qid


def test_calculate_missing_quote_is_404(admin_client):
    r = admin_client.post("/api/v1/quotes/99999/calculate")
    assert r.status_code == 404
