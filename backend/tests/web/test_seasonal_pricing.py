"""v0.9.4: 季节多档定价 / 附加费 / 节日捆绑包 CRUD HTTP 集成测试.

走 admin_client (admin/admin123 session cookie), 端到端 POST/GET/DELETE 三类资源.
"""
from __future__ import annotations


def test_season_calendar_crud(admin_client):
    # 1. POST
    r = admin_client.post("/api/v1/resources/season-calendars", json={
        "name": "2026 圣诞新年(测试)",
        "season_band": "holiday",
        "date_from": "2026-12-20",
        "date_to": "2027-01-05",
        "priority": 10,
        "note": "pytest 写入",
    })
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert cid > 0

    # 2. LIST 能看到
    r = admin_client.get("/api/v1/resources/season-calendars")
    assert r.status_code == 200
    rows = r.json()
    target = [c for c in rows if c["id"] == cid]
    assert target, f"刚 POST 的 id={cid} 不在列表"
    assert target[0]["season_band"] == "holiday"
    assert target[0]["priority"] == 10

    # 3. DELETE
    r = admin_client.delete(f"/api/v1/resources/season-calendars/{cid}")
    assert r.status_code == 200


def test_surcharge_global_then_filter(admin_client):
    # 全局政府税
    r = admin_client.post("/api/v1/resources/surcharges", json={
        "name": "Government Tax 21% (pytest)",
        "charge_type": "tax",
        "calc_method": "percent",
        "amount": 21,
    })
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # 旅游税 (定额/人/晚)
    r = admin_client.post("/api/v1/resources/surcharges", json={
        "name": "Tourist Tax (pytest)",
        "charge_type": "tourist_tax",
        "calc_method": "fixed_per_pax_night",
        "amount": 150000,
    })
    assert r.status_code == 200, r.text

    r = admin_client.get("/api/v1/resources/surcharges")
    rows = r.json()
    pytest_rows = [s for s in rows if "(pytest)" in s["name"]]
    assert len(pytest_rows) >= 2
    # 清理
    for s in pytest_rows:
        admin_client.delete(f"/api/v1/resources/surcharges/{s['id']}")


def test_hotel_package_requires_hotel(admin_client):
    # 先建酒店
    r = admin_client.post("/api/v1/resources/hotels", json={
        "destination_id": 1, "name_zh": "pytest 酒店包测试", "rooms": []
    })
    assert r.status_code == 200, r.text
    hid = r.json()["id"]

    # POST 节日包
    r = admin_client.post("/api/v1/resources/hotel-packages", json={
        "hotel_id": hid,
        "name": "Xmas Gala (pytest)",
        "valid_from": "2026-12-24",
        "valid_to": "2026-12-24",
        "mandatory": True,
        "cost_idr_per_room": 2800000,
        "cost_idr_per_pax": 500000,
        "includes": "Gala + 烟花",
        "replaces_dinner": True,
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    # LIST 按 hotel_id 筛选
    r = admin_client.get(f"/api/v1/resources/hotel-packages?hotel_id={hid}")
    rows = r.json()
    assert len(rows) == 1
    p = rows[0]
    assert p["name"] == "Xmas Gala (pytest)"
    assert p["mandatory"] is True
    assert p["replaces_dinner"] is True
    assert float(p["cost_idr_per_room"]) == 2800000.0

    # 清理
    admin_client.delete(f"/api/v1/resources/hotel-packages/{pid}")
    admin_client.delete(f"/api/v1/resources/hotels/{hid}")


def test_room_rate_attached_to_room(admin_client):
    # 建酒店带 1 房型
    r = admin_client.post("/api/v1/resources/hotels", json={
        "destination_id": 1, "name_zh": "pytest 房价测试",
        "rooms": [{
            "room_type": "Deluxe", "max_occupancy": 2,
            "breakfast_included": True,
            "cost_idr_low": 1500000, "cost_idr_high": 3500000,
        }]
    })
    assert r.status_code == 200, r.text
    hid = r.json()["id"]

    # 取该酒店下的房型 id
    r = admin_client.get(f"/api/v1/resources/hotels")
    hotels = r.json()
    h = next(x for x in hotels if x["id"] == hid)
    room_id = h["rooms"][0]["id"]

    # POST 多档房价
    for band, cost in [("low", 1500000), ("shoulder", 2200000),
                       ("high", 3500000), ("holiday", 5800000)]:
        r = admin_client.post("/api/v1/resources/room-rates", json={
            "room_id": room_id, "season_band": band, "cost_idr": cost,
        })
        assert r.status_code == 200, f"band={band}: {r.text}"

    # LIST 应有 4 档
    r = admin_client.get(f"/api/v1/resources/room-rates?room_id={room_id}")
    rates = r.json()
    assert len(rates) == 4
    bands = sorted(rt["season_band"] for rt in rates)
    assert bands == ["high", "holiday", "low", "shoulder"]
    holiday_cost = next(rt for rt in rates if rt["season_band"] == "holiday")["cost_idr"]
    assert float(holiday_cost) == 5800000.0

    # 清理
    admin_client.delete(f"/api/v1/resources/hotels/{hid}")


def test_hotel_resave_keeps_room_ids_and_rates(admin_client):
    """2026-06-11 回归: 保存酒店改为 diff upsert — 房型 id 不变, RoomRate 不丢.

    老实现是全删全建: 每次保存酒店房型 id 全变, 已录季节档价格级联丢失/变孤儿.
    """
    r = admin_client.post("/api/v1/resources/hotels", json={
        "destination_id": 1, "name_zh": "pytest 重存酒店",
        "rooms": [
            {"room_type": "Deluxe", "max_occupancy": 2,
             "cost_idr_low": 1000000, "cost_idr_high": 2000000},
            {"room_type": "Suite", "max_occupancy": 3,
             "cost_idr_low": 3000000, "cost_idr_high": 5000000},
        ],
    })
    assert r.status_code == 200, r.text
    hid = r.json()["id"]

    h = next(x for x in admin_client.get("/api/v1/resources/hotels").json() if x["id"] == hid)
    deluxe = next(rm for rm in h["rooms"] if rm["room_type"] == "Deluxe")
    suite = next(rm for rm in h["rooms"] if rm["room_type"] == "Suite")

    # Deluxe 录 2 档价
    for band, cost in [("low", 1000000), ("peak", 4200000)]:
        r = admin_client.post("/api/v1/resources/room-rates", json={
            "room_id": deluxe["id"], "season_band": band, "cost_idr": cost,
        })
        assert r.status_code == 200, r.text

    # 重存酒店: Deluxe 带 id 改名, Suite 删除, 新增 Villa
    r = admin_client.post("/api/v1/resources/hotels", json={
        "id": hid, "destination_id": 1, "name_zh": "pytest 重存酒店",
        "rooms": [
            {"id": deluxe["id"], "room_type": "Deluxe Ocean", "max_occupancy": 2,
             "cost_idr_low": 1100000, "cost_idr_high": 2100000},
            {"room_type": "Villa", "max_occupancy": 4,
             "cost_idr_low": 6000000, "cost_idr_high": 9000000},
        ],
    })
    assert r.status_code == 200, r.text

    h2 = next(x for x in admin_client.get("/api/v1/resources/hotels").json() if x["id"] == hid)
    types = sorted(rm["room_type"] for rm in h2["rooms"])
    assert types == ["Deluxe Ocean", "Villa"]
    deluxe2 = next(rm for rm in h2["rooms"] if rm["room_type"] == "Deluxe Ocean")
    assert deluxe2["id"] == deluxe["id"], "带 id 的房型重存后 id 必须不变"

    # Deluxe 的 2 档价仍在
    rates = admin_client.get(f"/api/v1/resources/room-rates?room_id={deluxe['id']}").json()
    assert sorted(rt["season_band"] for rt in rates) == ["low", "peak"]

    # 被删的 Suite 的 rate 不残留孤儿 (Suite 没录过 rate, 但端点不应报错)
    rates_suite = admin_client.get(f"/api/v1/resources/room-rates?room_id={suite['id']}").json()
    assert rates_suite == []

    # 清理
    admin_client.delete(f"/api/v1/resources/hotels/{hid}")
