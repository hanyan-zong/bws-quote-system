"""计价引擎 — 把 QuoteDay 列表的 IDR 成本汇总并换算为 CNY.

v0.9.4 (2026-05-24) 季节多档定价升级:
- _resolve_season_band(day): 先查 SeasonCalendar (按日期 + 优先级),
  没命中则 fallback 到 quote.season (老行为). day.date 为空也直接 fallback.
- _resolve_room_cost(room, band, day): 优先查 RoomRate 多档表 (low/shoulder/high/peak/holiday),
  没命中 fallback 到 HotelRoom.cost_idr_low/high 老字段.
- _calc_hotel_surcharges(): 政府税/服务费/旅游税 — 百分比或定额, 按晚累加.
- _calc_mandatory_packages(): 节日强制捆绑包 (圣诞 Gala/新年烟花), 替换晚餐时跳过餐厅成本.

全部加 fallback: 老数据(没 RoomRate/Surcharge/Package)行为不变, 单元测试不挂.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from .. import models


HIGH_BAND_SET = {"high", "peak", "holiday"}


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
    surcharge_idr_total: Decimal = Decimal(0)  # v0.9.4
    package_idr_total: Decimal = Decimal(0)    # v0.9.4


# ------------------------------------------------------------
# v0.9.4 helpers — 全部带 fallback, 老数据/老 schema 直接落到 quote.season + 老两档
# ------------------------------------------------------------
def _resolve_season_band(quote: models.Quote, day_date: _date | None, db: Session) -> str:
    """day_date → season_band. 没 day_date 或无 SeasonCalendar 命中则用 quote.season."""
    if day_date is None:
        return quote.season or "shoulder"
    SeasonCalendar = getattr(models, "SeasonCalendar", None)
    if SeasonCalendar is None:
        return quote.season or "shoulder"
    try:
        row = (
            db.query(SeasonCalendar)
            .filter(SeasonCalendar.date_from <= day_date, SeasonCalendar.date_to >= day_date)
            .order_by(SeasonCalendar.priority.desc())
            .first()
        )
        if row is not None:
            return row.season_band
    except Exception:
        pass
    return quote.season or "shoulder"


def _resolve_room_cost(
    room: models.HotelRoom | None,
    band: str,
    day_date: _date | None,
    db: Session,
) -> Decimal:
    """优先查 RoomRate 多档表; fallback 到 HotelRoom.cost_idr_low/high 老字段."""
    if room is None:
        return Decimal(0)
    RoomRate = getattr(models, "RoomRate", None)
    if RoomRate is not None:
        try:
            candidates = db.query(RoomRate).filter_by(room_id=room.id, season_band=band).all()
            # 优先匹配带日期区间的 (年度特价); 再降级到无日期区间的常规档
            for rr in candidates:
                ok_from = rr.valid_from is None or (day_date and rr.valid_from <= day_date) or day_date is None
                ok_to = rr.valid_to is None or (day_date and rr.valid_to >= day_date) or day_date is None
                if day_date and (rr.valid_from or rr.valid_to):
                    ok_from = rr.valid_from is None or rr.valid_from <= day_date
                    ok_to = rr.valid_to is None or rr.valid_to >= day_date
                if ok_from and ok_to:
                    return D(rr.cost_idr)
        except Exception:
            pass
    # fallback 老两档
    return D(room.cost_idr_high if band in HIGH_BAND_SET else room.cost_idr_low)


def _calc_hotel_surcharges(
    hotel_id: int | None,
    room_cost_idr: Decimal,
    band: str,
    day_date: _date | None,
    pax_total: int,
    db: Session,
) -> tuple[Decimal, list[str]]:
    """酒店附加费 (税/服务费/Resort Fee). 返回 (total_idr_added, 明细列表)."""
    Surcharge = getattr(models, "Surcharge", None)
    if Surcharge is None or hotel_id is None:
        return Decimal(0), []
    try:
        from sqlalchemy import or_
        rows = (
            db.query(Surcharge)
            .filter(Surcharge.active.is_(True))
            .filter(or_(Surcharge.hotel_id == hotel_id, Surcharge.hotel_id.is_(None)))
            .all()
        )
    except Exception:
        return Decimal(0), []

    total = Decimal(0)
    details: list[str] = []
    for s in rows:
        if s.season_band:
            allowed = {b.strip() for b in str(s.season_band).split(",") if b.strip()}
            if band not in allowed:
                continue
        if day_date is not None:
            if s.valid_from and day_date < s.valid_from:
                continue
            if s.valid_to and day_date > s.valid_to:
                continue
        amt = D(s.amount)
        method = s.calc_method
        if method == "percent":
            v = (room_cost_idr * amt / Decimal(100)).quantize(Decimal("1"))
        elif method == "fixed_per_room_night":
            v = amt
        elif method == "fixed_per_pax_night":
            v = amt * pax_total
        elif method == "fixed_per_stay":
            # 整次入住一次性 — 跳过 (留给上层 quote 级处理或在抵达日单独算)
            continue
        else:
            continue
        if v <= 0:
            continue
        total += v
        details.append(f"附加费 {s.name}: {v} IDR")
    return total, details


def _calc_mandatory_packages(
    hotel_id: int | None,
    day_date: _date | None,
    pax_total: int,
    db: Session,
) -> tuple[Decimal, list[str], bool]:
    """节日强制捆绑包. 返回 (total_idr, 明细, 是否替换晚餐)."""
    HotelPackage = getattr(models, "HotelPackage", None)
    if HotelPackage is None or hotel_id is None or day_date is None:
        return Decimal(0), [], False
    try:
        rows = (
            db.query(HotelPackage)
            .filter(
                HotelPackage.hotel_id == hotel_id,
                HotelPackage.mandatory.is_(True),
                HotelPackage.active.is_(True),
                HotelPackage.valid_from <= day_date,
                HotelPackage.valid_to >= day_date,
            )
            .all()
        )
    except Exception:
        return Decimal(0), [], False

    total = Decimal(0)
    details: list[str] = []
    replaces_dinner = False
    for p in rows:
        v = D(p.cost_idr_per_room) + D(p.cost_idr_per_pax) * pax_total
        if v <= 0:
            continue
        total += v
        details.append(f"节日包 {p.name}: {v} IDR")
        if p.replaces_dinner:
            replaces_dinner = True
    return total, details, replaces_dinner


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------
def calculate(quote: models.Quote, db: Session) -> PricingBreakdown:
    """根据报价单的 days 汇总成本.传入已加载 days/items 的 ORM 对象."""
    pax_total = max(quote.pax_adult + quote.pax_child, 1)
    rate = D(quote.exchange_rate) or Decimal(2300)

    breakdown = PricingBreakdown()
    for day in quote.days:
        day_cost_idr = Decimal(0)
        details: list[str] = []
        day_date = getattr(day, "date", None)
        band = _resolve_season_band(quote, day_date, db)

        # v0.9.3: 半天系数 — half/arrival(下午到)/departure(上午送机) 三种用车按 0.5 天算
        day_type = getattr(day, "day_type", "full") or "full"
        is_half_charged = day_type in ("half", "arrival", "departure")
        charge_ratio = Decimal("0.5") if is_half_charged else Decimal("1")
        day_type_label = {
            "half": "半天",
            "arrival": "抵达日",
            "departure": "送机日",
        }.get(day_type, "")

        # ---- 酒店 + v0.9.4 附加费 + 强制节日包 ----
        room_cost = Decimal(0)
        replaces_dinner = False
        # v0.9.3: departure (送机日) 不算住宿 — 前一晚已含
        if day.hotel_room_id and day_type != "departure":
            room = db.get(models.HotelRoom, day.hotel_room_id)
            if room:
                room_cost = _resolve_room_cost(room, band, day_date, db)
                day_cost_idr += room_cost
                label = {"low": "淡", "shoulder": "平", "high": "旺", "peak": "高峰", "holiday": "节日"}.get(band, band)
                details.append(f"酒店 {room.room_type} [{label}]: {room_cost} IDR")

            # 附加费 / 节日包: 取酒店级 (优先 day.hotel_id, 没有就从 room 反查)
            hotel_id_for_extras = day.hotel_id or (room.hotel_id if room else None)
            if hotel_id_for_extras:
                sur_total, sur_details = _calc_hotel_surcharges(
                    hotel_id_for_extras, room_cost, band, day_date, pax_total, db
                )
                if sur_total > 0:
                    day_cost_idr += sur_total
                    breakdown.surcharge_idr_total += sur_total
                    details.extend(sur_details)

                pkg_total, pkg_details, replaces_dinner = _calc_mandatory_packages(
                    hotel_id_for_extras, day_date, pax_total, db
                )
                if pkg_total > 0:
                    day_cost_idr += pkg_total
                    breakdown.package_idr_total += pkg_total
                    details.extend(pkg_details)

        # ---- 用车 (v0.9.3: 半天/送机日 × 0.5) ----
        if day.vehicle_id and not day.is_free:
            v = db.get(models.Vehicle, day.vehicle_id)
            if v:
                cost = (D(v.cost_idr_per_day) * charge_ratio).quantize(Decimal("1"))
                day_cost_idr += cost
                suffix = f" ({day_type_label})" if day_type_label else ""
                details.append(f"用车 {v.vehicle_type}{suffix}: {cost} IDR")

        # ---- 导游 (v0.9.3: 半天/送机日 × 0.5) ----
        if day.guide_id and not day.is_free:
            g = db.get(models.Guide, day.guide_id)
            if g:
                cost = (D(g.cost_idr_per_day) * charge_ratio).quantize(Decimal("1"))
                day_cost_idr += cost
                suffix = f" ({day_type_label})" if day_type_label else ""
                details.append(f"导游 {g.name_zh}{suffix}: {cost} IDR")

        if not day.is_free:
            # ---- 餐 (v0.9.4: 节日包替换晚餐时跳过 dinner) ----
            meal_attrs = [("lunch_restaurant_id", "午餐")]
            if not replaces_dinner:
                meal_attrs.append(("dinner_restaurant_id", "晚餐"))
            for rid_attr, label in meal_attrs:
                rid = getattr(day, rid_attr)
                if rid:
                    r = db.get(models.Restaurant, rid)
                    if r:
                        cost = D(r.cost_idr_per_person) * pax_total
                        day_cost_idr += cost
                        details.append(f"{label} {r.name_zh}: {cost} IDR (×{pax_total})")
            if replaces_dinner and day.dinner_restaurant_id:
                details.append("晚餐已并入节日包,不另计")

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
                "season_band": band,  # v0.9.4: 暴露季节档供 UI 显示
                "cost_idr": str(day_cost_idr),
                "cost_cny": str((day_cost_idr / rate).quantize(Decimal("0.01"))),
                "details": details,
            }
        )

    breakdown.cost_cny_total = (breakdown.cost_idr_total / rate).quantize(Decimal("0.01"))
    breakdown.per_pax_idr = (breakdown.cost_idr_total / pax_total).quantize(Decimal("0.01"))
    breakdown.per_pax_cny = (breakdown.cost_cny_total / pax_total).quantize(Decimal("0.01"))
    return breakdown
