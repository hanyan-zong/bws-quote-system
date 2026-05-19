"""v0.9.3: QuoteDay.day_type 对 pricing_engine 的影响 — unit test.

用 MagicMock 伪造 Quote/QuoteDay/Vehicle/Guide/HotelRoom, 直接调 calculate(quote, db).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from app.utils.pricing_engine import calculate


def _make_quote(*, day_type: str, vehicle_cost: int = 0, guide_cost: int = 0, hotel_room_cost: int = 0):
    """构造单日 quote, 注入指定 day_type 与可选成本."""
    db = MagicMock()

    vehicle = MagicMock(vehicle_type="商务车", cost_idr_per_day=Decimal(vehicle_cost)) if vehicle_cost else None
    guide = MagicMock(name_zh="阿明", cost_idr_per_day=Decimal(guide_cost)) if guide_cost else None
    room = MagicMock(
        cost_idr_low=Decimal(hotel_room_cost), cost_idr_high=Decimal(hotel_room_cost),
        room_type="豪华大床",
    ) if hotel_room_cost else None

    def _get(model, id_):
        name = model.__name__ if hasattr(model, "__name__") else str(model)
        if name == "Vehicle" and vehicle:
            return vehicle
        if name == "Guide" and guide:
            return guide
        if name == "HotelRoom" and room:
            return room
        return None
    db.get.side_effect = _get

    day = MagicMock(
        day_index=1,
        is_free=False,
        day_type=day_type,
        vehicle_id=1 if vehicle else None,
        guide_id=1 if guide else None,
        hotel_room_id=99 if room else None,
        hotel_id=None,
        lunch_restaurant_id=None,
        dinner_restaurant_id=None,
        afternoon_tea_id=None,
        spa_id=None,
        water_activity_id=None,
        items=[],
    )
    quote = MagicMock(
        days=[day],
        pax_adult=2,
        pax_child=0,
        exchange_rate=Decimal(2300),
        season="shoulder",
    )
    return quote, db


def test_full_day_charges_full_vehicle_cost():
    quote, db = _make_quote(day_type="full", vehicle_cost=1_000_000)
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(1_000_000)


def test_half_day_charges_half_vehicle_cost():
    quote, db = _make_quote(day_type="half", vehicle_cost=1_000_000)
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(500_000), f"half day vehicle should be 0.5x, got {b.cost_idr_total}"


def test_arrival_day_charges_half_vehicle_cost():
    quote, db = _make_quote(day_type="arrival", vehicle_cost=1_000_000)
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(500_000)


def test_departure_day_charges_half_vehicle_and_no_hotel():
    quote, db = _make_quote(day_type="departure", vehicle_cost=1_000_000, hotel_room_cost=2_000_000)
    b = calculate(quote, db)
    # 送机日: vehicle 0.5x = 500k, hotel 跳过 = 0, 总 500k
    assert b.cost_idr_total == Decimal(500_000), f"departure day should skip hotel + half vehicle, got {b.cost_idr_total}"


def test_full_day_charges_full_hotel():
    quote, db = _make_quote(day_type="full", hotel_room_cost=2_000_000)
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(2_000_000)


def test_half_day_does_not_skip_hotel():
    """半天≠送机. 半天用户可能就是回酒店中转, 仍要算住宿."""
    quote, db = _make_quote(day_type="half", hotel_room_cost=2_000_000, vehicle_cost=1_000_000)
    b = calculate(quote, db)
    # 半天: 酒店 2M + 车 1M × 0.5 = 2.5M
    assert b.cost_idr_total == Decimal(2_500_000)


def test_half_day_charges_half_guide_too():
    quote, db = _make_quote(day_type="half", guide_cost=800_000)
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(400_000)


def test_default_day_type_full_when_attribute_missing():
    """老数据 QuoteDay 没 day_type 属性 — getattr 默认 'full', 不应崩."""
    quote, db = _make_quote(day_type="full", vehicle_cost=1_000_000)
    # 主动删 day_type 让 getattr 走 fallback
    del quote.days[0].day_type
    b = calculate(quote, db)
    assert b.cost_idr_total == Decimal(1_000_000), "应按 'full' 默认计算"
