"""计价引擎 — 把 QuoteDay 列表的 IDR 成本汇总并换算为 CNY."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from .. import models


def D(v: Any) -> Decimal:
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


@dataclass
class PricingBreakdown:
    cost_idr_total: Decimal = Decimal(0)
    cost_cny_total: Decimal = Decimal(0)
    per_day: list[dict[str, Any]] = field(default_factory=list)
    per_pax_idr: Decimal = Decimal(0)
    per_pax_cny: Decimal = Decimal(0)


def calculate(quote: models.Quote, db: Session) -> PricingBreakdown:
    """根据报价单的 days 汇总成本.传入已加载 days/items 的 ORM 对象."""
    pax_total = max(quote.pax_adult + quote.pax_child, 1)
    rate = D(quote.exchange_rate) or Decimal(2300)
    season = quote.season

    breakdown = PricingBreakdown()
    for day in quote.days:
        day_cost_idr = Decimal(0)
        details: list[str] = []

        # ---- 酒店 ----
        if day.hotel_room_id:
            room = db.get(models.HotelRoom, day.hotel_room_id)
            if room:
                cost = D(room.cost_idr_high if season == "high" else room.cost_idr_low)
                day_cost_idr += cost
                details.append(f"酒店 {room.room_type}: {cost} IDR")

        # ---- 用车 ----
        if day.vehicle_id and not day.is_free:
            v = db.get(models.Vehicle, day.vehicle_id)
            if v:
                cost = D(v.cost_idr_per_day)
                day_cost_idr += cost
                details.append(f"用车 {v.vehicle_type}: {cost} IDR")

        # ---- 导游 ----
        if day.guide_id and not day.is_free:
            g = db.get(models.Guide, day.guide_id)
            if g:
                cost = D(g.cost_idr_per_day)
                day_cost_idr += cost
                details.append(f"导游 {g.name_zh}: {cost} IDR")

        if not day.is_free:
            # ---- 餐 ----
            for rid_attr, label in [
                ("lunch_restaurant_id", "午餐"),
                ("dinner_restaurant_id", "晚餐"),
            ]:
                rid = getattr(day, rid_attr)
                if rid:
                    r = db.get(models.Restaurant, rid)
                    if r:
                        cost = D(r.cost_idr_per_person) * pax_total
                        day_cost_idr += cost
                        details.append(f"{label} {r.name_zh}: {cost} IDR (×{pax_total})")

            # ---- 景点门票 ----
            for item in day.items:
                attr = db.get(models.Attraction, item.attraction_id)
                if attr:
                    cost = D(attr.ticket_idr_adult) * quote.pax_adult + D(attr.ticket_idr_child) * quote.pax_child
                    day_cost_idr += cost
                    details.append(f"景点 {attr.name_zh}: {cost} IDR")

            # ---- 下午茶 / SPA / 水上 ----
            if day.afternoon_tea_id:
                t = db.get(models.AfternoonTea, day.afternoon_tea_id)
                if t:
                    cost = D(t.cost_idr_per_person) * pax_total
                    day_cost_idr += cost
                    details.append(f"下午茶: {cost} IDR")
            if day.spa_id:
                s = db.get(models.SpaPackage, day.spa_id)
                if s:
                    cost = D(s.cost_idr_per_person) * pax_total
                    day_cost_idr += cost
                    details.append(f"SPA: {cost} IDR")
            if day.water_activity_id:
                w = db.get(models.WaterActivity, day.water_activity_id)
                if w:
                    cost = D(w.cost_idr_per_person) * pax_total
                    day_cost_idr += cost
                    details.append(f"水上项目: {cost} IDR")

        breakdown.cost_idr_total += day_cost_idr
        breakdown.per_day.append(
            {
                "day_index": day.day_index,
                "is_free": day.is_free,
                "cost_idr": str(day_cost_idr),
                "cost_cny": str((day_cost_idr / rate).quantize(Decimal("0.01"))),
                "details": details,
            }
        )

    breakdown.cost_cny_total = (breakdown.cost_idr_total / rate).quantize(Decimal("0.01"))
    breakdown.per_pax_idr = (breakdown.cost_idr_total / pax_total).quantize(Decimal("0.01"))
    breakdown.per_pax_cny = (breakdown.cost_cny_total / pax_total).quantize(Decimal("0.01"))
    return breakdown
