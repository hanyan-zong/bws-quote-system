"""v0.9.4: 暑期/寒假/国庆 端到端集成测试.

真实建数据 (HTTP POST) → 创建 Quote → POST /calculate → 直接读 DB 跑 pricing_engine
拿完整 PricingBreakdown 验证:
- 日期落进 SeasonCalendar 区间 → 取 RoomRate.peak (4M, 非老 cost_idr_high)
- 暑期日期 (2026-07-15) → 政府税 21% + 暑期附加 IDR 200k/人/晚 应用; 寒假/国庆**不应用**
- 国庆日期 (2026-10-03) → 政府税 + 国庆 20%; 暑期/寒假不应用
- 寒假日期 (2027-02-01) → 政府税 + 寒假 IDR 150k/人/晚
- 普通日期 (2026-03-15) → SeasonCalendar 不命中 → fallback quote.season=shoulder → RoomRate.shoulder (2M), 仅政府税

每场景前后清理 (pytest-holiday-e2e) 命名前缀的数据避免干扰其他测试.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app import models
from app.utils import pricing_engine


PREFIX = "pytest-holiday-e2e"


@pytest.fixture
def seeded_world(admin_client):
    """建一个酒店 + 4 档房价 + 3 段假期日历 + 3 条假期附加费 + 1 条全局政府税.
    返回 ids dict, 测试用. teardown 自动清理.
    """
    # ---- 建酒店 + 1 房型 ----
    r = admin_client.post("/api/v1/resources/hotels", json={
        "destination_id": 1,
        "name_zh": f"{PREFIX} 测试酒店",
        "rooms": [{
            "room_type": "Deluxe (e2e)",
            "max_occupancy": 2,
            "breakfast_included": True,
            "cost_idr_low": 1_000_000,
            "cost_idr_high": 3_000_000,
        }],
    })
    assert r.status_code == 200, r.text
    hid = r.json()["id"]

    # 取该酒店下房型 id
    hotels = admin_client.get("/api/v1/resources/hotels").json()
    h = next(x for x in hotels if x["id"] == hid)
    room_id = h["rooms"][0]["id"]

    # ---- 4 档 RoomRate ----
    rate_ids = []
    for band, cost in [
        ("low", 1_000_000), ("shoulder", 2_000_000),
        ("high", 3_000_000), ("peak", 4_000_000),
    ]:
        r = admin_client.post("/api/v1/resources/room-rates", json={
            "room_id": room_id, "season_band": band, "cost_idr": cost,
        })
        assert r.status_code == 200, f"room_rate {band}: {r.text}"
        rate_ids.append(r.json()["id"])

    # ---- 3 段假期日历 ----
    cal_ids = []
    for name, band, df, dt, prio in [
        (f"{PREFIX} 2026 暑期",  "peak", "2026-07-01", "2026-08-31", 8),
        (f"{PREFIX} 2026 国庆",  "peak", "2026-10-01", "2026-10-07", 9),
        (f"{PREFIX} 2027 寒假",  "peak", "2027-01-20", "2027-02-20", 8),
    ]:
        r = admin_client.post("/api/v1/resources/season-calendars", json={
            "name": name, "season_band": band,
            "date_from": df, "date_to": dt, "priority": prio,
        })
        assert r.status_code == 200, r.text
        cal_ids.append(r.json()["id"])

    # ---- 全局政府税 + 3 条假期附加费 ----
    sur_ids = []
    for payload in [
        # 全局政府税 21% (所有日期, 所有酒店)
        {"name": f"{PREFIX} Gov Tax 21%",       "charge_type": "tax",
         "calc_method": "percent",              "amount": 21},
        # 暑期 IDR 200k/人/晚, 限定 2026-07-01 ~ 08-31
        {"name": f"{PREFIX} Summer Break",      "charge_type": "summer_break",
         "calc_method": "fixed_per_pax_night",  "amount": 200000,
         "valid_from": "2026-07-01", "valid_to": "2026-08-31"},
        # 寒假 IDR 150k/人/晚, 限定 2027-01-20 ~ 02-20
        {"name": f"{PREFIX} Winter Break",      "charge_type": "winter_break",
         "calc_method": "fixed_per_pax_night",  "amount": 150000,
         "valid_from": "2027-01-20", "valid_to": "2027-02-20"},
        # 国庆 20%, 限定 2026-10-01 ~ 10-07
        {"name": f"{PREFIX} National Day 20%",  "charge_type": "national_day_break",
         "calc_method": "percent",              "amount": 20,
         "valid_from": "2026-10-01", "valid_to": "2026-10-07"},
    ]:
        r = admin_client.post("/api/v1/resources/surcharges", json=payload)
        assert r.status_code == 200, r.text
        sur_ids.append(r.json()["id"])

    yield {
        "hotel_id": hid, "room_id": room_id,
        "rate_ids": rate_ids, "cal_ids": cal_ids, "sur_ids": sur_ids,
    }

    # ---- teardown: 清干净, 避免污染其他测试 ----
    # SQLite 默认不开 PRAGMA foreign_keys=ON, FK CASCADE 不生效 → 必须主动删 RoomRate
    for rid in rate_ids:
        admin_client.delete(f"/api/v1/resources/room-rates/{rid}")
    for sid in sur_ids:
        admin_client.delete(f"/api/v1/resources/surcharges/{sid}")
    for cid in cal_ids:
        admin_client.delete(f"/api/v1/resources/season-calendars/{cid}")
    admin_client.delete(f"/api/v1/resources/hotels/{hid}")


def _create_quote_and_calc(admin_client, *, day_date: str, room_id: int, hotel_id: int,
                           season_hint: str = "shoulder"):
    """建 1 日 quote (含 hotel + room + date), 立即 POST /calculate.
    返回 (quote_id, calc_json)."""
    r = admin_client.post("/api/v1/quotes", json={
        "agency_name": f"{PREFIX} agency",
        "pax_adult": 2,
        "pax_child": 0,
        "destination_codes": ["DPS"],
        "season": season_hint,
        "customer_type": "family",
        "total_days": 1,
        "days": [{
            "day_index": 1,
            "date": day_date,
            "is_free": False,
            "day_type": "full",
            "hotel_id": hotel_id,
            "hotel_room_id": room_id,
            "breakfast_included": True,
        }],
    })
    assert r.status_code == 200, f"create quote: {r.text}"
    qid = r.json()["id"]
    r = admin_client.post(f"/api/v1/quotes/{qid}/calculate")
    assert r.status_code == 200, f"calculate: {r.text}"
    return qid, r.json()


def _direct_breakdown(quote_id: int):
    """直接读 DB + 跑 pricing_engine, 拿完整 PricingBreakdown (含 surcharge/package 明细)."""
    db = SessionLocal()
    try:
        from sqlalchemy.orm import joinedload
        q = (
            db.query(models.Quote)
            .options(joinedload(models.Quote.days).joinedload(models.QuoteDay.items))
            .filter_by(id=quote_id)
            .first()
        )
        assert q is not None
        return pricing_engine.calculate(q, db)
    finally:
        db.close()


# ============================================================
# 场景 A: 暑期 (2026-07-15) — peak 房价 + 政府税 + 暑期附加; 寒假/国庆不命中
# ============================================================
def test_summer_break_2026_07_15(admin_client, seeded_world):
    qid, calc = _create_quote_and_calc(
        admin_client, day_date="2026-07-15",
        room_id=seeded_world["room_id"], hotel_id=seeded_world["hotel_id"],
    )
    # HTTP 返回的 cost_idr_total 应为: peak 房 4M + 21% 税 (840k) + 暑期 200k×2 (400k) = 5,240,000
    expected = Decimal(5_240_000)
    assert Decimal(str(calc["cost_idr_total"])) == expected, (
        f"暑期日期总成本期望 {expected}, 实得 {calc['cost_idr_total']}"
    )

    # 直接读 DB 拿明细做更细的断言
    b = _direct_breakdown(qid)
    assert b.cost_idr_total == expected
    assert b.surcharge_idr_total == Decimal(1_240_000), (
        f"surcharge 应为 21%×4M (840k) + 暑期 400k = 1.24M, 实得 {b.surcharge_idr_total}"
    )
    # per_day[0].season_band 应为 peak (SeasonCalendar 命中)
    assert b.per_day[0]["season_band"] == "peak"


# ============================================================
# 场景 B: 国庆 (2026-10-03) — peak 房价 + 政府税 + 国庆 20%; 暑期/寒假不命中
# ============================================================
def test_national_day_2026_10_03(admin_client, seeded_world):
    qid, calc = _create_quote_and_calc(
        admin_client, day_date="2026-10-03",
        room_id=seeded_world["room_id"], hotel_id=seeded_world["hotel_id"],
    )
    # 总成本: 4M + 21% (840k) + 国庆 20% (800k) = 5,640,000
    expected = Decimal(5_640_000)
    assert Decimal(str(calc["cost_idr_total"])) == expected, (
        f"国庆日期总成本期望 {expected}, 实得 {calc['cost_idr_total']}"
    )

    b = _direct_breakdown(qid)
    assert b.surcharge_idr_total == Decimal(1_640_000), (
        f"surcharge 应为 21%×4M (840k) + 国庆 20%×4M (800k) = 1.64M, 实得 {b.surcharge_idr_total}"
    )
    assert b.per_day[0]["season_band"] == "peak"


# ============================================================
# 场景 C: 寒假 (2027-02-01) — peak 房价 + 政府税 + 寒假 150k/人/晚
# ============================================================
def test_winter_break_2027_02_01(admin_client, seeded_world):
    qid, calc = _create_quote_and_calc(
        admin_client, day_date="2027-02-01",
        room_id=seeded_world["room_id"], hotel_id=seeded_world["hotel_id"],
    )
    # 总成本: 4M + 21% (840k) + 寒假 150k×2 (300k) = 5,140,000
    expected = Decimal(5_140_000)
    assert Decimal(str(calc["cost_idr_total"])) == expected, (
        f"寒假日期总成本期望 {expected}, 实得 {calc['cost_idr_total']}"
    )

    b = _direct_breakdown(qid)
    assert b.surcharge_idr_total == Decimal(1_140_000)
    assert b.per_day[0]["season_band"] == "peak"


# ============================================================
# 场景 D: 普通平日 (2026-03-15) — SeasonCalendar 不命中 → fallback shoulder; 仅政府税, 无任何假期附加
# ============================================================
def test_normal_shoulder_2026_03_15(admin_client, seeded_world):
    qid, calc = _create_quote_and_calc(
        admin_client, day_date="2026-03-15",
        room_id=seeded_world["room_id"], hotel_id=seeded_world["hotel_id"],
        season_hint="shoulder",  # quote.season 兜底
    )
    # 总成本: shoulder 房 2M + 21% 税 (420k) = 2,420,000 (无任何假期附加)
    expected = Decimal(2_420_000)
    assert Decimal(str(calc["cost_idr_total"])) == expected, (
        f"普通日期总成本期望 {expected} (无任何假期附加), 实得 {calc['cost_idr_total']}"
    )

    b = _direct_breakdown(qid)
    assert b.surcharge_idr_total == Decimal(420_000), (
        f"普通日期 surcharge 只该有政府税 420k, 实得 {b.surcharge_idr_total}"
    )
    # 应 fallback 到 quote.season=shoulder, 不是 SeasonCalendar 命中的 peak
    assert b.per_day[0]["season_band"] == "shoulder"


# ============================================================
# 场景 E: 假期边界精确性 — 2026-08-31 (暑期最后一天) 还应触发暑期附加费,
#                           2026-09-01 不应触发
# ============================================================
def test_summer_break_boundary_inclusive(admin_client, seeded_world):
    # 8/31 应触发暑期附加
    _, calc_in = _create_quote_and_calc(
        admin_client, day_date="2026-08-31",
        room_id=seeded_world["room_id"], hotel_id=seeded_world["hotel_id"],
    )
    assert Decimal(str(calc_in["cost_idr_total"])) == Decimal(5_240_000), (
        f"8/31 边界 (最后一天) 应触发暑期附加费, 实得 {calc_in['cost_idr_total']}"
    )

    # 9/1 不应触发暑期附加; SeasonCalendar 也不命中, 走 shoulder = 2M + 21% = 2.42M
    _, calc_out = _create_quote_and_calc(
        admin_client, day_date="2026-09-01",
        room_id=seeded_world["room_id"], hotel_id=seeded_world["hotel_id"],
        season_hint="shoulder",
    )
    assert Decimal(str(calc_out["cost_idr_total"])) == Decimal(2_420_000), (
        f"9/1 应回到普通价 2.42M (无暑期/无 peak), 实得 {calc_out['cost_idr_total']}"
    )
