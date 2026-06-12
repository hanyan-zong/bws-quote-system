"""GET /quotes/stats — APP 工作台状态分布统计.

Session 共享 tmp DB (其他测试会建单), 所以一律相对断言: 先取快照再比增量.
"""
from __future__ import annotations

STATUSES = ("draft", "sent", "accepted", "lost")


def _get_stats(client) -> dict:
    r = client.get("/api/v1/quotes/stats")
    assert r.status_code == 200, f"stats failed: {r.status_code} {r.text}"
    return r.json()


def _create_draft(client, agency_name: str) -> int:
    r = client.post(
        "/api/v1/quotes",
        json={"agency_name": agency_name, "pax_adult": 2, "customer_type": "family"},
    )
    assert r.status_code == 200, f"create failed: {r.text}"
    return r.json()["id"]


def test_stats_shape_and_total_consistency(admin_client):
    data = _get_stats(admin_client)
    assert set(data.keys()) == {"total", "by_status"}
    assert set(data["by_status"].keys()) == set(STATUSES)
    for v in data["by_status"].values():
        assert isinstance(v, int) and v >= 0
    assert data["total"] == sum(data["by_status"].values())


def test_stats_increments_after_create(admin_client):
    before = _get_stats(admin_client)

    _create_draft(admin_client, "TestStatsAgency")

    after = _get_stats(admin_client)
    assert after["total"] == before["total"] + 1
    assert after["by_status"]["draft"] == before["by_status"]["draft"] + 1


def test_stats_reflects_status_change(admin_client):
    qid = _create_draft(admin_client, "TestStatsFlowAgency")
    before = _get_stats(admin_client)

    r = admin_client.put(f"/api/v1/quotes/{qid}/status", json={"status": "sent"})
    assert r.status_code == 200

    after = _get_stats(admin_client)
    assert after["by_status"]["sent"] == before["by_status"]["sent"] + 1
    assert after["by_status"]["draft"] == before["by_status"]["draft"] - 1
    assert after["total"] == before["total"]


def test_stats_agent_only_sees_own_quotes(admin_client, agent_client):
    """scope 过滤: agent 只统计自己创建的单, admin 建单不影响 agent 视图."""
    agent_before = _get_stats(agent_client)

    _create_draft(admin_client, "TestStatsAdminOnly")
    assert _get_stats(agent_client) == agent_before

    _create_draft(agent_client, "TestStatsAgentOwn")
    agent_after = _get_stats(agent_client)
    assert agent_after["total"] == agent_before["total"] + 1
    assert agent_after["by_status"]["draft"] == agent_before["by_status"]["draft"] + 1


def test_stats_requires_auth(web_client):
    r = web_client.get("/api/v1/quotes/stats")
    assert r.status_code == 401
