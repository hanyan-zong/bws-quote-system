"""报价单 — CRUD + Calculate (汇总成本+校验+赌自费推荐).

v0.4 增强:
- 创建/更新时记录 created_by_user_id + agency_id (从 cookie 推导)
- 列表/详情按角色 scope 过滤
- 输出按角色裁剪 sensitive 字段(成本/利润/赌额)
- 新增 PUT /{id}/status — 状态变更钉 ERP 事件队列
"""
from __future__ import annotations

import json
from datetime import date, datetime
from ..utils.time_utils import now_utc
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import models
from ..database import get_db
from ..schemas import QuoteIn, QuoteCalculateOut
from ..utils import pricing_engine, feasibility_engine, gambling_engine
from ..utils.erp_hook import enqueue_erp_event, quote_to_payload
from ..utils.permissions import filter_quote_dict, filter_quotes_by_scope
from .auth import get_current_user

router = APIRouter(prefix="/quotes", tags=["quotes"])


class QuoteStatusIn(BaseModel):
    status: str  # draft / sent / accepted / lost
    reason: Optional[str] = None


class QuoteFeedbackIn(BaseModel):
    """团结束回写实际自费结果, 反哺策略库 (v0.5 P0-3)."""

    actual_optional_revenue_cny: float
    actual_profit_cny: float
    won_or_lost: str  # won / lost / partial
    notes: Optional[str] = None


def _generate_quote_no() -> str:
    import random
    return "Q" + now_utc().strftime("%Y%m%d%H%M%S") + f"{random.randint(0, 999):03d}"


def _persist_days(quote: models.Quote, payload: QuoteIn, db: Session) -> None:
    # 简化: 全删全建
    for d in list(quote.days):
        db.delete(d)
    db.flush()
    for d_in in payload.days:
        # 根据 free_hours 自动推 is_free (>=8 视为全天自由)
        derived_is_free = d_in.is_free or (d_in.free_hours or 0) >= 8
        # v0.9.3: departure 类型自动 hotel_id=None + breakfast_included=True (前一晚含早)
        _day_type = getattr(d_in, "day_type", "full") or "full"
        _hotel_id = None if _day_type == "departure" else d_in.hotel_id
        _hotel_room_id = None if _day_type == "departure" else d_in.hotel_room_id
        _breakfast = True if _day_type == "departure" else d_in.breakfast_included
        day = models.QuoteDay(
            quote_id=quote.id,
            day_index=d_in.day_index,
            date=d_in.date,
            is_free=derived_is_free,
            free_hours=d_in.free_hours or (8 if d_in.is_free else 0),
            day_type=_day_type,
            template_id=d_in.template_id,
            hotel_id=_hotel_id,
            hotel_room_id=_hotel_room_id,
            vehicle_id=d_in.vehicle_id,
            guide_id=d_in.guide_id,
            breakfast_included=_breakfast,
            lunch_restaurant_id=d_in.lunch_restaurant_id,
            dinner_restaurant_id=d_in.dinner_restaurant_id,
            afternoon_tea_id=d_in.afternoon_tea_id,
            spa_id=d_in.spa_id,
            water_activity_id=d_in.water_activity_id,
            start_time=d_in.start_time,
            notes=d_in.notes,
        )
        db.add(day)
        db.flush()
        for item_in in d_in.attractions:
            db.add(
                models.QuoteItem(
                    quote_day_id=day.id,
                    attraction_id=item_in.attraction_id,
                    order_index=item_in.order_index,
                    arrival_time=item_in.arrival_time,
                    stay_minutes=item_in.stay_minutes,
                )
            )


def _quote_to_dict(q: models.Quote) -> dict[str, Any]:
    return {
        "id": q.id,
        "quote_no": q.quote_no,
        "agency_name": q.agency_name,
        "agency_contact": q.agency_contact,  # v0.10: APP 编辑模式透传用 (保存是全量覆盖语义)
        "customer_name": q.customer_name,
        "pax_adult": q.pax_adult,
        "pax_child": q.pax_child,
        "pax_senior": getattr(q, "pax_senior", 0) or 0,
        "start_date": q.start_date.isoformat() if q.start_date else None,
        "end_date": q.end_date.isoformat() if q.end_date else None,
        "total_days": q.total_days,
        "free_days": q.free_days,
        "destination_codes": q.destination_codes,
        "season": q.season,
        "customer_type": q.customer_type,
        "is_first_time_agency": q.is_first_time_agency,
        "exchange_rate": float(q.exchange_rate),
        "cost_idr_total": float(q.cost_idr_total),
        "cost_cny_total": float(q.cost_cny_total),
        "profit_cny_per_pax": float(q.profit_cny_per_pax),
        "gamble_cny_per_pax": float(q.gamble_cny_per_pax),
        "price_cny_per_pax": float(q.price_cny_per_pax),
        "price_cny_total": float(q.price_cny_total),
        "feasibility_status": q.feasibility_status,
        "status": q.status,
        "notes": q.notes,
        "arrival_at": q.arrival_at.isoformat() if q.arrival_at else None,
        "departure_at": q.departure_at.isoformat() if q.departure_at else None,
        "arrival_airport": q.arrival_airport,
        "departure_airport": q.departure_airport,
        "days": [
            {
                "id": d.id,
                "day_index": d.day_index,
                "date": d.date.isoformat() if d.date else None,
                "is_free": d.is_free,
                "free_hours": getattr(d, "free_hours", 0) or 0,  # v0.10: APP 编辑透传 (不下发会被全量覆盖抹掉)
                "day_type": getattr(d, "day_type", "full") or "full",
                "template_id": d.template_id,
                "hotel_id": d.hotel_id,
                "hotel_room_id": d.hotel_room_id,
                "vehicle_id": d.vehicle_id,
                "guide_id": d.guide_id,
                "breakfast_included": d.breakfast_included,
                "lunch_restaurant_id": d.lunch_restaurant_id,
                "dinner_restaurant_id": d.dinner_restaurant_id,
                "afternoon_tea_id": d.afternoon_tea_id,
                "spa_id": d.spa_id,
                "water_activity_id": d.water_activity_id,
                "start_time": d.start_time.isoformat() if d.start_time else None,  # v0.10: APP 编辑透传
                "notes": d.notes,
                "items": [
                    {
                        "attraction_id": i.attraction_id,
                        "order_index": i.order_index,
                        "arrival_time": i.arrival_time.isoformat() if i.arrival_time else None,  # v0.10: 同上
                        "stay_minutes": i.stay_minutes,
                    }
                    for i in d.items
                ],
            }
            for d in q.days
        ],
        "created_at": q.created_at.isoformat() if q.created_at else None,
    }


@router.post("")
def create_or_update_quote(payload: QuoteIn, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if payload.id:
        quote = db.get(models.Quote, payload.id)
        if not quote:
            raise HTTPException(404, "报价不存在")
        # 权限: agent 只能改自己创建的; agency_owner 改本社; super_admin 全权
        if user and user.role == "agent" and quote.created_by_user_id != user.id:
            raise HTTPException(403, "无权修改他人报价")
        if user and user.role == "agency_owner" and quote.agency_id != user.agency_id:
            raise HTTPException(403, "无权修改其他旅行社的报价")
    else:
        quote = models.Quote(quote_no=_generate_quote_no())
        db.add(quote)
        if user:
            quote.created_by_user_id = user.id
            quote.agency_id = user.agency_id
            quote.created_by = user.username

    quote.agency_name = payload.agency_name
    quote.agency_contact = payload.agency_contact
    quote.customer_name = payload.customer_name
    quote.pax_adult = payload.pax_adult
    quote.pax_child = payload.pax_child
    quote.pax_senior = getattr(payload, "pax_senior", 0) or 0
    quote.start_date = payload.start_date
    quote.end_date = payload.end_date
    quote.destination_codes = ",".join(payload.destination_codes or [])
    quote.season = payload.season
    quote.customer_type = payload.customer_type
    quote.is_first_time_agency = payload.is_first_time_agency
    quote.notes = payload.notes
    # 航班信息(v0.2.5)
    quote.arrival_at = payload.arrival_at
    quote.departure_at = payload.departure_at
    quote.arrival_airport = payload.arrival_airport
    quote.departure_airport = payload.departure_airport
    if payload.exchange_rate is not None:
        quote.exchange_rate = payload.exchange_rate
    quote.total_days = len(payload.days) or quote.total_days
    # free_days 仍按 1 天为单位 (兼容旧字段); 新算法直接读 free_hours_total
    quote.free_days = sum(1 for d in payload.days if d.is_free or (d.free_hours or 0) >= 8)
    db.flush()

    _persist_days(quote, payload, db)
    db.commit()
    db.refresh(quote)
    return {"id": quote.id, "quote_no": quote.quote_no}


@router.get("")
def list_quotes(
    request: Request,
    db: Session = Depends(get_db),
    status: str | None = None,
    page: int | None = None,
    size: int = 20,
):
    """报价单列表.

    v0.10: 带 page 参数 → 分页信封 {items,total,page,size,pages} (APP z-paging 用);
    不带 page → 老行为裸数组上限 200 (web 前端依赖此格式, 只增不改).
    """
    user = get_current_user(request, db)
    base = db.query(models.Quote)
    if status:
        base = base.filter(models.Quote.status == status)
    base = filter_quotes_by_scope(base, user)
    ordered = base.order_by(models.Quote.created_at.desc())

    if page is None:
        rows = ordered.options(joinedload(models.Quote.days)).limit(200).all()
        return [filter_quote_dict(_quote_to_dict(x), user) for x in rows]

    page = max(1, page)
    size = min(max(1, size), 100)
    total = base.count()
    rows = (
        ordered.options(selectinload(models.Quote.days))
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "items": [filter_quote_dict(_quote_to_dict(x), user) for x in rows],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


def _day_resource_names(q: models.Quote, db: Session) -> dict[str, dict[int, str]]:
    """v0.10 APP 详情页人话渲染用 — 把 days 引用到的资源 id 批量换成中文名.

    只查本报价用到的 id (不全量 dump 资源库); 移动端拿 names 直接渲染, 不用再拉资源接口.
    """
    def ids(attr: str) -> set[int]:
        return {getattr(d, attr) for d in q.days if getattr(d, attr)}

    def name_map(model, id_set: set[int], label=None) -> dict[int, str]:
        if not id_set:
            return {}
        rows = db.query(model).filter(model.id.in_(id_set)).all()
        return {r.id: (label(r) if label else r.name_zh) for r in rows}

    attraction_ids = {i.attraction_id for d in q.days for i in d.items if i.attraction_id}
    restaurant_ids = ids("lunch_restaurant_id") | ids("dinner_restaurant_id")
    return {
        "hotels": name_map(models.Hotel, ids("hotel_id")),
        "rooms": name_map(models.HotelRoom, ids("hotel_room_id"), lambda r: r.room_type),
        "vehicles": name_map(models.Vehicle, ids("vehicle_id"), lambda r: f"{r.vehicle_type} {r.seat_count}座"),
        "guides": name_map(models.Guide, ids("guide_id")),
        "attractions": name_map(models.Attraction, attraction_ids),
        "restaurants": name_map(models.Restaurant, restaurant_ids),
        "templates": name_map(models.DayTripTemplate, ids("template_id")),
    }


@router.get("/{quote_id}")
def get_quote(quote_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    quote = (
        db.query(models.Quote)
        .options(joinedload(models.Quote.days).joinedload(models.QuoteDay.items))
        .filter_by(id=quote_id)
        .first()
    )
    if not quote:
        raise HTTPException(404)
    # 权限校验
    if user:
        if user.role == "agent" and quote.created_by_user_id != user.id:
            raise HTTPException(403, "无权查看")
        if user.role == "agency_owner" and quote.agency_id != user.agency_id:
            raise HTTPException(403, "无权查看其他旅行社的报价")
    data = filter_quote_dict(_quote_to_dict(quote), user)
    data["names"] = _day_resource_names(quote, db)
    return data


@router.delete("/{quote_id}")
def delete_quote(quote_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    q = db.get(models.Quote, quote_id)
    if not q:
        raise HTTPException(404)
    if user and user.role == "agent" and q.created_by_user_id != user.id:
        raise HTTPException(403)
    if user and user.role == "agency_owner" and q.agency_id != user.agency_id:
        raise HTTPException(403)
    if user and user.role == "viewer":
        raise HTTPException(403)
    db.delete(q)
    db.commit()
    return {"ok": True}


@router.put("/{quote_id}/status")
def update_quote_status(
    quote_id: int, payload: QuoteStatusIn, request: Request, db: Session = Depends(get_db),
):
    """状态变更 + ERP 钩子. 仅 super_admin / agency_owner / 创建者本人."""
    user = get_current_user(request, db)
    quote = (
        db.query(models.Quote)
        .options(joinedload(models.Quote.days).joinedload(models.QuoteDay.items))
        .filter_by(id=quote_id)
        .first()
    )
    if not quote:
        raise HTTPException(404)
    if user:
        if user.role == "agent" and quote.created_by_user_id != user.id:
            raise HTTPException(403)
        if user.role == "agency_owner" and quote.agency_id != user.agency_id:
            raise HTTPException(403)
        if user.role == "viewer":
            raise HTTPException(403)
    valid = {"draft", "sent", "accepted", "lost"}
    if payload.status not in valid:
        raise HTTPException(400, f"status 必须是 {valid}")
    old_status = quote.status
    quote.status = payload.status
    db.flush()

    # ★ ERP 钩子(仅在状态切换到 accepted/lost 时触发)
    if old_status != "accepted" and payload.status == "accepted":
        enqueue_erp_event(db, "quote.accepted", "quote", quote.id, quote_to_payload(quote))
    elif old_status != "lost" and payload.status == "lost":
        enqueue_erp_event(db, "quote.cancelled", "quote", quote.id, {
            "quote_no": quote.quote_no,
            "reason": payload.reason or "",
        })

    db.commit()
    return {"ok": True, "status": quote.status, "old_status": old_status}


@router.post("/{quote_id}/feedback")
def submit_quote_feedback(
    quote_id: int, payload: QuoteFeedbackIn, request: Request, db: Session = Depends(get_db),
):
    """团结束回写实际自费收入与利润. 仅 super_admin / agency_owner / 创建者本人."""
    user = get_current_user(request, db)
    quote = db.get(models.Quote, quote_id)
    if not quote:
        raise HTTPException(404, "报价不存在")
    if user:
        if user.role == "agent" and quote.created_by_user_id != user.id:
            raise HTTPException(403)
        if user.role == "agency_owner" and quote.agency_id != user.agency_id:
            raise HTTPException(403)
        if user.role == "viewer":
            raise HTTPException(403)
    if payload.won_or_lost not in ("won", "lost", "partial"):
        raise HTTPException(400, "won_or_lost 必须是 won / lost / partial")

    # 更新最新的 GambleHistory(每次 calculate 会插一条, 取最新)
    latest = (
        db.query(models.GambleHistory)
        .filter_by(quote_id=quote_id)
        .order_by(models.GambleHistory.created_at.desc())
        .first()
    )
    if not latest:
        # 没算过价? 罕见但允许补建一条
        latest = models.GambleHistory(quote_id=quote_id, recommended_cny=Decimal(0), applied_cny=Decimal(0))
        db.add(latest)
        db.flush()

    latest.optional_tours_revenue_cny = Decimal(str(payload.actual_optional_revenue_cny))
    latest.profit_actual_cny = Decimal(str(payload.actual_profit_cny))
    latest.won_or_lost = payload.won_or_lost
    latest.feedback_notes = payload.notes or ""
    latest.feedback_at = now_utc()
    if user:
        latest.feedback_by = user.id

    db.commit()
    db.refresh(latest)
    return {
        "ok": True,
        "gamble_history_id": latest.id,
        "quote_id": quote_id,
        "won_or_lost": latest.won_or_lost,
        "actual_optional_revenue_cny": float(latest.optional_tours_revenue_cny),
        "actual_profit_cny": float(latest.profit_actual_cny),
        "feedback_at": latest.feedback_at.isoformat(),
    }


@router.post("/{quote_id}/calculate", response_model=QuoteCalculateOut)
def calculate_quote(quote_id: int, db: Session = Depends(get_db)):
    quote = (
        db.query(models.Quote)
        .options(joinedload(models.Quote.days).joinedload(models.QuoteDay.items))
        .filter_by(id=quote_id)
        .first()
    )
    if not quote:
        raise HTTPException(404)

    # 1) 计价
    breakdown = pricing_engine.calculate(quote, db)
    quote.cost_idr_total = breakdown.cost_idr_total
    quote.cost_cny_total = breakdown.cost_cny_total

    pax_total = max(quote.pax_adult + quote.pax_child, 1)
    cost_per_pax = breakdown.per_pax_cny

    # 2) 行程合理性校验
    fea_report = feasibility_engine.check_quote(quote, db, run_ai_review=False)
    quote.feasibility_status = (
        "fail" if not fea_report.overall_feasible
        else ("warning" if any(d.warnings for d in fea_report.days) else "pass")
    )
    quote.feasibility_report = json.dumps(fea_report.to_dict(), ensure_ascii=False)

    # 3) 赌自费推荐
    gamble = gambling_engine.recommend(quote, db)
    quote.gamble_cny_per_pax = gamble.recommended_cny

    # 4) 默认利润 (可手动覆盖) — 这里 v0.1 用客户类型经验值
    default_profit_per_pax = {
        "honeymoon": Decimal("400"),
        "family_kids": Decimal("300"),
        "young": Decimal("250"),
        "family": Decimal("250"),
        "senior": Decimal("200"),
        "mice": Decimal("500"),
        "wedding": Decimal("600"),
    }.get(quote.customer_type, Decimal("250"))

    # v0.5.1: 命中"不赌+加利润"策略时, 反向给单人利润 +X
    extra_profit = getattr(gamble, "extra_profit_cny_per_pax", Decimal(0)) or Decimal(0)
    quote.profit_cny_per_pax = (default_profit_per_pax + extra_profit).quantize(Decimal("0.01"))
    # price = 成本 + 利润 - 赌额
    price_per_pax = cost_per_pax + default_profit_per_pax + extra_profit - gamble.recommended_cny
    quote.price_cny_per_pax = price_per_pax.quantize(Decimal("0.01"))
    quote.price_cny_total = (quote.price_cny_per_pax * pax_total).quantize(Decimal("0.01"))

    # 5) 写赌自费历史 (一份记录) — v0.5 同时记录命中的策略 ID(如有), 供事后胜率统计
    strategy_id = None
    if gamble.skip_rule and isinstance(gamble.skip_rule, dict):
        strategy_id = gamble.skip_rule.get("id")
    db.add(
        models.GambleHistory(
            quote_id=quote.id,
            recommended_cny=gamble.recommended_cny,
            applied_cny=gamble.recommended_cny,
            ai_confidence=gamble.ai_confidence,
            reasoning=gamble.reasoning,
            won_or_lost="pending",
            strategy_id=strategy_id,
        )
    )

    db.commit()
    db.refresh(quote)

    return QuoteCalculateOut(
        quote_id=quote.id,
        quote_no=quote.quote_no,
        cost_idr_total=quote.cost_idr_total,
        cost_cny_total=quote.cost_cny_total,
        profit_cny_per_pax=quote.profit_cny_per_pax,
        gamble_cny_per_pax=quote.gamble_cny_per_pax,
        price_cny_per_pax=quote.price_cny_per_pax,
        price_cny_total=quote.price_cny_total,
        feasibility_status=quote.feasibility_status,
        feasibility_report=fea_report.to_dict(),
        gamble_recommendation={
            "recommended_cny": float(gamble.recommended_cny),
            "low_bound_cny": float(gamble.low_bound_cny),
            "high_bound_cny": float(gamble.high_bound_cny),
            "ai_confidence": gamble.ai_confidence,
            "reasoning": gamble.reasoning,
            "configured_optional_tours": gamble.configured_optional_tours,
            "excluded_optional_tours": gamble.excluded_optional_tours,
            "skip_rule": gamble.skip_rule,
            "enabled": gamble.enabled,
        },
    )
