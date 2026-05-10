"""报价导出上下文 — 把 ORM 转成扁平、可读、按角色裁剪的字典.

3 个 builder (excel/pdf/docx) 都消费这个字典, 不再各自查 ORM, 保证字段一致.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ... import models
from ..permissions import can_see_costs


def _name(obj: Any, attr_zh: str = "name_zh", attr_fb: str = "name") -> str:
    if obj is None:
        return ""
    return getattr(obj, attr_zh, None) or getattr(obj, attr_fb, "") or ""


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def _fmt_money(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return f"{v:,.2f}"
    return f"{float(v):,.2f}"


def build_export_context(
    quote: models.Quote, db: Session, user: models.User | None = None
) -> dict[str, Any]:
    """汇总报价单导出所需的全部信息为可序列化字典.

    返回字典结构:
    {
        "meta": {导出时间/导出人/版本},
        "quote": {基本信息 + 价格(按角色裁剪)},
        "days": [{day_index, date, hotel_name, vehicle, restaurants, attractions[]}],
        "totals": {pax_total, days, free_days, ...},
        "show_costs": bool,  # 是否展示 IDR 成本/利润/赌额
        "feasibility": [{day_index, warnings, errors}],
        "gamble": {recommended_cny, configured_optional_tours[], excluded_optional_tours[], reasoning},
    }
    """
    show_costs = can_see_costs(user)
    pax_total = max(quote.pax_adult + quote.pax_child, 1)

    days_out: list[dict[str, Any]] = []
    for d in sorted(quote.days, key=lambda x: x.day_index):
        # 关联资源名称
        hotel = db.get(models.Hotel, d.hotel_id) if d.hotel_id else None
        room = db.get(models.HotelRoom, d.hotel_room_id) if d.hotel_room_id else None
        vehicle = db.get(models.Vehicle, d.vehicle_id) if d.vehicle_id else None
        guide = db.get(models.Guide, d.guide_id) if d.guide_id else None
        lunch = db.get(models.Restaurant, d.lunch_restaurant_id) if d.lunch_restaurant_id else None
        dinner = db.get(models.Restaurant, d.dinner_restaurant_id) if d.dinner_restaurant_id else None
        tea = db.get(models.AfternoonTea, d.afternoon_tea_id) if d.afternoon_tea_id else None
        spa = db.get(models.SpaPackage, d.spa_id) if d.spa_id else None
        water = db.get(models.WaterActivity, d.water_activity_id) if d.water_activity_id else None

        items_out: list[dict[str, Any]] = []
        for it in sorted(d.items, key=lambda x: x.order_index):
            attr = db.get(models.Attraction, it.attraction_id)
            items_out.append({
                "order": it.order_index,
                "name": _name(attr),
                "stay_minutes": it.stay_minutes or 0,
                "ticket_per_adult_cny": (
                    float(attr.ticket_idr_adult or 0) / float(quote.exchange_rate or 2300)
                    if attr else 0
                ),
            })

        days_out.append({
            "day_index": d.day_index,
            "date": d.date.isoformat() if d.date else "",
            "is_free": d.is_free,
            "free_hours": d.free_hours or 0,
            "hotel": _name(hotel),
            "room": _name(room, "room_type", "room_type"),
            "vehicle": _name(vehicle, "vehicle_type", "vehicle_type"),
            "guide": _name(guide),
            "breakfast_included": d.breakfast_included,
            "lunch": _name(lunch),
            "dinner": _name(dinner),
            "afternoon_tea": _name(tea),
            "spa": _name(spa),
            "water_activity": _name(water),
            "notes": d.notes or "",
            "attractions": items_out,
        })

    quote_dict: dict[str, Any] = {
        "id": quote.id,
        "quote_no": quote.quote_no,
        "agency_name": quote.agency_name or "",
        "agency_contact": quote.agency_contact or "",
        "customer_name": quote.customer_name or "",
        "pax_adult": quote.pax_adult,
        "pax_child": quote.pax_child,
        "pax_total": pax_total,
        "start_date": quote.start_date.isoformat() if quote.start_date else "",
        "end_date": quote.end_date.isoformat() if quote.end_date else "",
        "total_days": quote.total_days,
        "free_days": quote.free_days,
        "destination_codes": quote.destination_codes or "",
        "season_label": {"low": "淡季", "shoulder": "平季", "high": "旺季"}.get(
            quote.season, quote.season or ""
        ),
        "customer_type_label": {
            "honeymoon": "蜜月", "family_kids": "亲子",
            "young": "年轻人", "family": "家庭", "senior": "长辈",
            "mice": "MICE/会奖", "wedding": "婚礼",
        }.get(quote.customer_type, quote.customer_type or ""),
        "is_first_time_agency": quote.is_first_time_agency,
        "exchange_rate": float(quote.exchange_rate or 2300),
        "status": quote.status,
        "notes": quote.notes or "",
        "arrival_at": _fmt_dt(quote.arrival_at),
        "departure_at": _fmt_dt(quote.departure_at),
        "arrival_airport": quote.arrival_airport or "",
        "departure_airport": quote.departure_airport or "",
        # 客户始终能看到:
        "price_cny_per_pax": float(quote.price_cny_per_pax or 0),
        "price_cny_total": float(quote.price_cny_total or 0),
    }

    # 仅 super_admin / agency_owner 能看到:
    if show_costs:
        quote_dict.update({
            "cost_idr_total": float(quote.cost_idr_total or 0),
            "cost_cny_total": float(quote.cost_cny_total or 0),
            "profit_cny_per_pax": float(quote.profit_cny_per_pax or 0),
            "gamble_cny_per_pax": float(quote.gamble_cny_per_pax or 0),
        })

    # 赌自费推荐 — 复用最近一条 GambleHistory(最新一次 calculate)
    gamble_info: dict[str, Any] = {}
    if quote.gamble_records:
        latest = sorted(quote.gamble_records, key=lambda r: r.created_at, reverse=True)[0]
        gamble_info = {
            "recommended_cny": float(latest.recommended_cny or 0),
            "applied_cny": float(latest.applied_cny or 0),
            "ai_confidence": latest.ai_confidence,
            "reasoning": latest.reasoning or "",
            "won_or_lost": latest.won_or_lost,
        }
        if latest.optional_tours_revenue_cny is not None:
            gamble_info["actual_revenue_cny"] = float(latest.optional_tours_revenue_cny)
        if latest.profit_actual_cny is not None:
            gamble_info["actual_profit_cny"] = float(latest.profit_actual_cny)

    # 行程合理性
    feasibility_summary = {
        "status": quote.feasibility_status,
        "label": {
            "pass": "通过", "warning": "可执行但有风险",
            "fail": "不可执行, 需调整", "unchecked": "未校验",
        }.get(quote.feasibility_status, quote.feasibility_status),
    }

    return {
        "meta": {
            "exported_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "exported_by": user.display_name if (user and user.display_name) else (
                user.username if user else "system"
            ),
            "exporter_role": user.role if user else "guest",
            "system": "BWS 预报价系统 · B 端 v0.5",
        },
        "quote": quote_dict,
        "days": days_out,
        "show_costs": show_costs,
        "gamble": gamble_info,
        "feasibility": feasibility_summary,
    }
