"""v0.9.4: 季节多档定价 + 附加费 + 节日捆绑包 — 单元测试.

用 MagicMock 隔离 ORM 查询. 覆盖:
- SeasonCalendar 命中: 走多档表 (RoomRate) 取价
- SeasonCalendar 未命中: fallback 到 quote.season + cost_idr_low/high
- Surcharge percent / fixed_per_room_night / fixed_per_pax_night 三种 method
- HotelPackage mandatory 强制叠加 + replaces_dinner 跳过晚餐
- 老数据零回归: 没有 RoomRate/Surcharge/Package 时和 v0.9.3 行为一致
"""
from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from unittest.mock import MagicMock

from app.utils.pricing_engine import calculate


def _build_db(
    *,
    season_calendar_rows=None,
    room_rate_rows=None,
    surcharge_rows=None,
    package_rows=None,
    room=None,
    vehicle=None,
    guide=None,
    restaurant=None,
):
    """造一个 MagicMock db: db.get(Model, id) + db.query(Model).filter(...).all()/first()."""
    db = MagicMock()

    def _get(model, id_):
        name = getattr(model, "__name__", str(model))
        if name == "HotelRoom" and room:
            return room
        if name == "Vehicle" and vehicle:
            return vehicle
        if name == "Guide" and guide:
            return guide
        if name == "Restaurant" and restaurant:
            return restaurant
        return None
    db.get.side_effect = _get

    def _query(model):
        name = getattr(model, "__name__", str(model))
        q = MagicMock()
        if name == "SeasonCalendar":
            chain_all = MagicMock(return_value=season_calendar_rows or [])
            chain_first = MagicMock(return_value=(season_calendar_rows or [None])[0])
            q.filter.return_value.order_by.return_value.first = chain_first
            q.filter.return_value.all = chain_all
        elif name == "RoomRate":
            q.filter_by.return_value.all.return_value = room_rate_rows or []
            q.filter_by.return_value.first.return_value = (room_rate_rows or [None])[0]
        elif name == "Surcharge":
            q.filter.return_value.filter.return_value.all.return_value = surcharge_rows or []
        elif name == "HotelPackage":
            q.filter.return_value.all.return_value = package_rows or []
        else:
            q.filter.return_value.all.return_value = []
            q.filter_by.return_value.all.return_value = []
        return q
    db.query.side_effect = _query
    return db


def _make_day(*, hotel_room_id=99, hotel_id=11, day_date=None, vehicle_id=None, guide_id=None,
              lunch_id=None, dinner_id=None):
    day = MagicMock(
        day_index=1,
        is_free=False,
        day_type="full",
        date=day_date,
        vehicle_id=vehicle_id,
        guide_id=guide_id,
        hotel_id=hotel_id,
        hotel_room_id=hotel_room_id,
        lunch_restaurant_id=lunch_id,
        dinner_restaurant_id=dinner_id,
        afternoon_tea_id=None,
        spa_id=None,
        water_activity_id=None,
        items=[],
    )
    return day


def _make_quote(days, *, pax_adult=2, pax_child=0, season="shoulder"):
    return MagicMock(
        days=days,
        pax_adult=pax_adult,
        pax_child=pax_child,
        exchange_rate=Decimal(2300),
        season=season,
    )


def _room(*, low=1_000_000, high=2_000_000, hotel_id=11, room_type="豪华大床"):
    return MagicMock(
        id=99,
        hotel_id=hotel_id,
        cost_idr_low=Decimal(low),
        cost_idr_high=Decimal(high),
        room_type=room_type,
    )


# ============================================================
# 1. SeasonCalendar 命中 + RoomRate 命中 → 走新多档价
# ============================================================
def test_season_calendar_hit_uses_room_rate_band():
    """日期落进 SeasonCalendar 的 holiday 区间 → 取 RoomRate.holiday 价 (5M),
    不是 cost_idr_high (2M)."""
    room = _room(low=1_000_000, high=2_000_000)
    season_cal = MagicMock(season_band="holiday", priority=10)
    room_rate = MagicMock(
        season_band="holiday",
        cost_idr=Decimal(5_000_000),
        valid_from=None, valid_to=None,
    )
    db = _build_db(
        season_calendar_rows=[season_cal],
        room_rate_rows=[room_rate],
        room=room,
    )
    day = _make_day(day_date=_date(2026, 12, 25))
    quote = _make_quote([day])
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(5_000_000), f"应取 RoomRate.holiday=5M, 得 {b.cost_idr_total}"


def test_season_calendar_miss_falls_back_to_quote_season():
    """SeasonCalendar 未命中 → 用 quote.season (high) → 走 cost_idr_high (2M)."""
    room = _room(low=1_000_000, high=2_000_000)
    db = _build_db(season_calendar_rows=[], room_rate_rows=[], room=room)
    day = _make_day(day_date=_date(2026, 8, 1))
    quote = _make_quote([day], season="high")
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(2_000_000), f"高峰季 fallback 应取 cost_idr_high=2M, 得 {b.cost_idr_total}"


def test_no_day_date_uses_quote_season():
    """day.date 为空 → 直接 fallback 到 quote.season (low) → cost_idr_low (1M)."""
    room = _room(low=1_000_000, high=2_000_000)
    db = _build_db(season_calendar_rows=[], room_rate_rows=[], room=room)
    day = _make_day(day_date=None)
    quote = _make_quote([day], season="low")
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(1_000_000)


# ============================================================
# 2. Surcharge 三种 calc_method
# ============================================================
def test_surcharge_percent_on_room_cost():
    """21% 政府税 on 2M 房费 = 420k."""
    room = _room(low=2_000_000, high=2_000_000)
    surcharge = MagicMock(
        name="Gov Tax 21%",
        charge_type="tax",
        calc_method="percent",
        amount=Decimal(21),
        season_band=None,
        valid_from=None, valid_to=None,
        active=True,
    )
    db = _build_db(room=room, surcharge_rows=[surcharge])
    day = _make_day(day_date=_date(2026, 7, 1))
    quote = _make_quote([day], season="shoulder")
    b = calculate(quote, db)
    # 房 2M + 21% = 2M + 420k = 2.42M
    assert b.cost_idr_total == Decimal(2_420_000), b.cost_idr_total
    assert b.surcharge_idr_total == Decimal(420_000)


def test_surcharge_fixed_per_pax_night():
    """旅游税 IDR 150k/人/晚 × 2 大人 = 300k."""
    room = _room(low=1_000_000, high=1_000_000)
    surcharge = MagicMock(
        name="Tourist Tax",
        charge_type="tourist_tax",
        calc_method="fixed_per_pax_night",
        amount=Decimal(150_000),
        season_band=None,
        valid_from=None, valid_to=None,
        active=True,
    )
    db = _build_db(room=room, surcharge_rows=[surcharge])
    day = _make_day(day_date=_date(2026, 7, 1))
    quote = _make_quote([day], season="shoulder", pax_adult=2)
    b = calculate(quote, db)
    # 房 1M + 旅游税 150k × 2 = 1.3M
    assert b.cost_idr_total == Decimal(1_300_000), b.cost_idr_total


def test_surcharge_band_filter_skips_when_not_matching():
    """surcharge.season_band='peak,holiday' 但当日是 shoulder → 不应用."""
    room = _room(low=1_000_000, high=1_000_000)
    surcharge = MagicMock(
        name="Peak Resort Fee",
        charge_type="resort_fee",
        calc_method="fixed_per_room_night",
        amount=Decimal(500_000),
        season_band="peak,holiday",
        valid_from=None, valid_to=None,
        active=True,
    )
    db = _build_db(room=room, surcharge_rows=[surcharge])
    day = _make_day(day_date=_date(2026, 7, 1))
    quote = _make_quote([day], season="shoulder")
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(1_000_000), "shoulder 不应触发 peak/holiday 限定费"
    assert b.surcharge_idr_total == Decimal(0)


# ============================================================
# 3. HotelPackage 节日捆绑包
# ============================================================
def test_mandatory_package_adds_cost():
    """圣诞 Gala: 2M/房 + 500k/人 × 2 人 = 3M 节日包."""
    room = _room(low=1_000_000, high=1_000_000)
    pkg = MagicMock(
        name="Christmas Gala",
        cost_idr_per_room=Decimal(2_000_000),
        cost_idr_per_pax=Decimal(500_000),
        replaces_dinner=False,
    )
    db = _build_db(room=room, package_rows=[pkg])
    day = _make_day(day_date=_date(2026, 12, 24))
    quote = _make_quote([day], season="shoulder", pax_adult=2)
    b = calculate(quote, db)
    # 房 1M + 节日包 (2M + 500k×2 = 3M) = 4M
    assert b.cost_idr_total == Decimal(4_000_000), b.cost_idr_total
    assert b.package_idr_total == Decimal(3_000_000)


def test_package_replaces_dinner_skips_restaurant():
    """节日包 replaces_dinner=True → dinner_restaurant_id 设了也不算钱."""
    room = _room(low=1_000_000, high=1_000_000)
    pkg = MagicMock(
        name="NYE Dinner Package",
        cost_idr_per_room=Decimal(0),
        cost_idr_per_pax=Decimal(800_000),
        replaces_dinner=True,
    )
    dinner = MagicMock(name_zh="脏鸭餐", cost_idr_per_person=Decimal(200_000))
    db = _build_db(room=room, package_rows=[pkg], restaurant=dinner)
    day = _make_day(day_date=_date(2026, 12, 31), dinner_id=88)
    quote = _make_quote([day], season="shoulder", pax_adult=2)
    b = calculate(quote, db)
    # 房 1M + 节日包 800k × 2 = 2.6M (晚餐 200k×2=400k 被替换不算)
    assert b.cost_idr_total == Decimal(2_600_000), b.cost_idr_total


# ============================================================
# 4. 综合: 多档 + 附加费 + 节日包 全开
# ============================================================
def test_full_stack_holiday_with_everything():
    """圣诞夜: holiday 档房价 5M + 21% 税 + 旅游税 150k/人 + 圣诞 Gala 3M (替换晚餐)."""
    room = _room(low=1_000_000, high=2_000_000)
    season_cal = MagicMock(season_band="holiday", priority=10)
    room_rate = MagicMock(
        season_band="holiday",
        cost_idr=Decimal(5_000_000),
        valid_from=None, valid_to=None,
    )
    tax = MagicMock(
        name="Gov Tax", charge_type="tax", calc_method="percent",
        amount=Decimal(21), season_band=None, valid_from=None, valid_to=None, active=True,
    )
    tourist = MagicMock(
        name="Tourist Tax", charge_type="tourist_tax", calc_method="fixed_per_pax_night",
        amount=Decimal(150_000), season_band=None, valid_from=None, valid_to=None, active=True,
    )
    pkg = MagicMock(
        name="Xmas Gala",
        cost_idr_per_room=Decimal(2_000_000),
        cost_idr_per_pax=Decimal(500_000),
        replaces_dinner=True,
    )
    dinner = MagicMock(name_zh="脏鸭餐", cost_idr_per_person=Decimal(200_000))
    db = _build_db(
        season_calendar_rows=[season_cal],
        room_rate_rows=[room_rate],
        surcharge_rows=[tax, tourist],
        package_rows=[pkg],
        room=room, restaurant=dinner,
    )
    day = _make_day(day_date=_date(2026, 12, 25), dinner_id=88)
    quote = _make_quote([day], pax_adult=2)
    b = calculate(quote, db)
    # 房 5M + 21% 税 (5M × 0.21 = 1.05M) + 旅游税 300k + Gala (2M + 500k×2 = 3M) = 9.35M
    # 晚餐 400k 被 replaces 跳过
    assert b.cost_idr_total == Decimal(9_350_000), b.cost_idr_total
    assert b.surcharge_idr_total == Decimal(1_350_000)
    assert b.package_idr_total == Decimal(3_000_000)


# ============================================================
# 5. 老数据零回归: 全空 → 行为应等同于 v0.9.3
# ============================================================
def test_legacy_no_seasonal_data_falls_back_to_v093():
    """没 SeasonCalendar/RoomRate/Surcharge/Package → 用 cost_idr_high (season=high)."""
    room = _room(low=1_000_000, high=2_000_000)
    db = _build_db(room=room)
    day = _make_day(day_date=_date(2026, 8, 1))
    quote = _make_quote([day], season="high")
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(2_000_000)
    assert b.surcharge_idr_total == Decimal(0)
    assert b.package_idr_total == Decimal(0)
