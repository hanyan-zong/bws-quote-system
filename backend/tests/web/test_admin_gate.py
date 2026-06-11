"""v0.9.2: agent 角色对管理类写端点的 403 防护测试.

覆盖三大类管理 router:
  - resources (酒店/景点/餐厅/车辆/导游/自费/simple)
  - templates (一日游)
  - settings (汇率/时间预算/赌自费/区域规则/景点互斥/策略)

读端点 (GET) 对 agent 保持开放, 因为 agent 报价时需要看资源 + 模板 + 区域规则.
"""
from __future__ import annotations


# ============================================================
#  Agent 写操作 → 403
# ============================================================
def test_agent_post_hotel_403(agent_client):
    r = agent_client.post("/api/v1/resources/hotels", json={
        "name_zh": "测试酒店", "destination_id": 1, "city": "Bali",
        "star": 5, "address": "x",
    })
    assert r.status_code == 403, r.text


def test_agent_delete_hotel_403(agent_client):
    r = agent_client.delete("/api/v1/resources/hotels/1")
    assert r.status_code == 403, r.text


def test_agent_post_attraction_403(agent_client):
    r = agent_client.post("/api/v1/resources/attractions", json={
        "name_zh": "测试景点", "destination_id": 1, "category": "culture",
    })
    assert r.status_code == 403, r.text


def test_agent_post_optional_tour_403(agent_client):
    r = agent_client.post("/api/v1/resources/optional-tours", json={
        "name_zh": "测试自费", "destination_id": 1,
        "sale_price_cny": 200, "cost_idr": 200000,
    })
    assert r.status_code == 403, r.text


def test_agent_post_template_403(agent_client):
    r = agent_client.post("/api/v1/templates", json={
        "destination_id": 1, "name_zh": "测试模板",
    })
    assert r.status_code == 403, r.text


def test_agent_delete_template_403(agent_client):
    r = agent_client.delete("/api/v1/templates/1")
    assert r.status_code == 403, r.text


def test_agent_put_exchange_rate_403(agent_client):
    r = agent_client.put("/api/v1/settings/exchange-rate", json={
        "rate_cny_to_idr": 2300, "set_by": "agent",
    })
    assert r.status_code == 403, r.text


def test_agent_post_gamble_strategy_403(agent_client):
    r = agent_client.post("/api/v1/settings/gamble-strategies", json={
        "name": "agent 不该能加", "conditions": [], "action": "skip",
        "gamble_cny": 0, "extra_profit_cny": 0, "priority": 1, "active": True,
    })
    assert r.status_code == 403, r.text


def test_agent_post_area_rule_403(agent_client):
    r = agent_client.post("/api/v1/settings/area-rules", json={
        "hotel_area": "库塔", "excluded_attraction_area": "罗威纳",
        "severity": "warning", "active": True,
    })
    assert r.status_code == 403, r.text


# ============================================================
#  Agent 读操作 → 200 (报价流程需要)
# ============================================================
def test_agent_can_get_hotels(agent_client):
    r = agent_client.get("/api/v1/resources/hotels")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_agent_can_get_templates(agent_client):
    r = agent_client.get("/api/v1/templates")
    assert r.status_code == 200, r.text


def test_agent_can_get_exchange_rate(agent_client):
    r = agent_client.get("/api/v1/settings/exchange-rate")
    assert r.status_code == 200, r.text


def test_agent_can_get_gamble_strategies(agent_client):
    r = agent_client.get("/api/v1/settings/gamble-strategies")
    assert r.status_code == 200, r.text


def test_agent_can_get_condition_types(agent_client):
    """condition-types 保留, 给 GambleStrategy 编辑器复用 — agent 看不到编辑器, 但端点开放无害."""
    r = agent_client.get("/api/v1/settings/no-gamble-rules/condition-types")
    assert r.status_code == 200, r.text


# ============================================================
#  AI 资源采集链路 (2026-06-11 堵漏): agent 一律 403
#  extracted_json 含原始 cost_idr, GET 也不开放
# ============================================================
def test_agent_get_extractions_403(agent_client):
    r = agent_client.get("/api/v1/ai/extractions")
    assert r.status_code == 403, r.text


def test_agent_get_extraction_detail_403(agent_client):
    r = agent_client.get("/api/v1/ai/extractions/1")
    assert r.status_code == 403, r.text


def test_agent_confirm_extraction_403(agent_client):
    r = agent_client.post("/api/v1/ai/extractions/1/confirm", json={
        "confirmed_resources": [], "corrections": [],
    })
    assert r.status_code == 403, r.text


def test_agent_ai_parse_403(agent_client):
    r = agent_client.post(
        "/api/v1/ai/parse",
        files={"file": ("x.txt", b"dummy", "text/plain")},
    )
    assert r.status_code == 403, r.text


def test_admin_can_list_extractions(admin_client):
    r = admin_client.get("/api/v1/ai/extractions")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


# ============================================================
#  Admin 仍可写 (回归)
# ============================================================
def test_admin_can_post_attraction(admin_client):
    r = admin_client.post("/api/v1/resources/attractions", json={
        "name_zh": "回归测试景点", "destination_id": 1, "category": "culture",
    })
    # 200/201/422 都接受 — 重点是不是 403
    assert r.status_code != 403, r.text
