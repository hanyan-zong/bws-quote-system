"""设置 API — 汇率、时间预算、赌自费配置、不赌自费规则、区域规则、策略胜率统计."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from ..utils.time_utils import now_utc
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..bali_areas import BALI_AREAS, BALI_AREAS_GROUPED
from ..database import get_db
from ..schemas import (
    ExchangeRateIn,
    GambleConfigIn,
    GambleStrategyIn,
    GambleStrategyPreviewIn,
    TimeBudgetIn,
)
from .auth import get_current_user
from ..utils.permissions import require_role

router = APIRouter(prefix="/settings", tags=["settings"])

# v0.9.2: 设置写操作仅 super_admin (改的是全局规则, 影响所有 agency)
_super_only = [Depends(require_role("super_admin"))]


# ---------------- 汇率 ----------------
@router.get("/exchange-rate")
def get_exchange_rate(db: Session = Depends(get_db)):
    rec = db.query(models.ExchangeRate).filter_by(is_current=True).first()
    if rec:
        return {
            "rate_cny_to_idr": float(rec.rate_cny_to_idr),
            "effective_date": rec.effective_date.isoformat(),
            "set_by": rec.set_by,
            "note": rec.note,
        }
    return {"rate_cny_to_idr": 2300, "effective_date": date.today().isoformat(), "set_by": "default"}


@router.put("/exchange-rate", dependencies=_super_only)
def set_exchange_rate(payload: ExchangeRateIn, db: Session = Depends(get_db)):
    db.query(models.ExchangeRate).update({"is_current": False})
    rec = models.ExchangeRate(
        effective_date=payload.effective_date or date.today(),
        rate_cny_to_idr=payload.rate_cny_to_idr,
        set_by=payload.set_by,
        note=payload.note,
        is_current=True,
    )
    db.add(rec)
    db.commit()
    return {"ok": True, "id": rec.id}


# ---------------- 时间预算 ----------------
@router.get("/time-budget")
def get_time_budget(db: Session = Depends(get_db)):
    rec = db.query(models.TimeBudgetConfig).filter_by(destination_id=None).first()
    if not rec:
        return TimeBudgetIn().model_dump()
    return {
        "max_drive_minutes_per_day": rec.max_drive_minutes_per_day,
        "max_drive_warn_minutes": rec.max_drive_warn_minutes,
        "morning_peak_coef": rec.morning_peak_coef,
        "evening_peak_coef": rec.evening_peak_coef,
        "holiday_coef": rec.holiday_coef,
        "hotel_to_first_max_minutes": rec.hotel_to_first_max_minutes,
        "airport_buffer_minutes": rec.airport_buffer_minutes,
    }


@router.put("/time-budget", dependencies=_super_only)
def set_time_budget(payload: TimeBudgetIn, db: Session = Depends(get_db)):
    rec = db.query(models.TimeBudgetConfig).filter_by(destination_id=None).first()
    if not rec:
        rec = models.TimeBudgetConfig()
        db.add(rec)
    for k, v in payload.model_dump().items():
        setattr(rec, k, v)
    db.commit()
    return {"ok": True}


# ---------------- 赌自费配置 ----------------
@router.get("/gamble-config")
def get_gamble_config(db: Session = Depends(get_db)):
    rec = db.query(models.GambleConfig).first()
    if not rec:
        return GambleConfigIn().model_dump()
    return {
        "enable_gambling": rec.enable_gambling,
        "safety_ratio": rec.safety_ratio,
        "max_loss_ratio": rec.max_loss_ratio,
        "first_time_agency_factor": rec.first_time_agency_factor,
        "default_margin_rate": rec.default_margin_rate,
        "mice_wedding_max_cny": float(rec.mice_wedding_max_cny),
    }


@router.put("/gamble-config", dependencies=_super_only)
def set_gamble_config(payload: GambleConfigIn, db: Session = Depends(get_db)):
    rec = db.query(models.GambleConfig).first()
    if not rec:
        rec = models.GambleConfig()
        db.add(rec)
    for k, v in payload.model_dump().items():
        setattr(rec, k, v)
    db.commit()
    return {"ok": True}


# ---------------- 不赌自费规则 CRUD ----------------
# v0.5.3: 已删除. 表 + 模型保留, 仅作 /gamble-strategies/migrate-from-no-gamble 的数据源.
# condition-types 端点保留 (前端编辑 GambleStrategy 条件下拉用) — 在文件末尾.


# ---------------- 巴厘岛区域字典 ----------------
@router.get("/areas")
def list_bali_areas():
    return {"flat": BALI_AREAS, "grouped": BALI_AREAS_GROUPED}


# ---------------- 区域不兼容规则 ----------------
class AreaRuleIn(BaseModel):
    id: int | None = None
    hotel_area: str
    excluded_attraction_area: str
    severity: str = "warning"  # warning | error
    message: str | None = None
    active: bool = True


def _area_rule_to_dict(r: models.AreaRule) -> dict:
    return {
        "id": r.id,
        "hotel_area": r.hotel_area,
        "excluded_attraction_area": r.excluded_attraction_area,
        "severity": r.severity,
        "message": r.message,
        "active": r.active,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/area-rules")
def list_area_rules(db: Session = Depends(get_db)):
    rows = db.query(models.AreaRule).order_by(
        models.AreaRule.severity.desc(),
        models.AreaRule.hotel_area,
    ).all()
    return [_area_rule_to_dict(r) for r in rows]


@router.post("/area-rules", dependencies=_super_only)
def upsert_area_rule(payload: AreaRuleIn, db: Session = Depends(get_db)):
    if payload.severity not in ("warning", "error"):
        raise HTTPException(400, "severity 必须是 warning 或 error")
    if payload.id:
        r = db.get(models.AreaRule, payload.id)
        if not r:
            raise HTTPException(404)
    else:
        r = models.AreaRule()
        db.add(r)
    r.hotel_area = payload.hotel_area
    r.excluded_attraction_area = payload.excluded_attraction_area
    r.severity = payload.severity
    r.message = payload.message
    r.active = payload.active
    db.commit()
    db.refresh(r)
    return {"id": r.id}


@router.delete("/area-rules/{rid}", dependencies=_super_only)
def delete_area_rule(rid: int, db: Session = Depends(get_db)):
    r = db.get(models.AreaRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


# ---------------- 景点互斥规则 ----------------
class AttractionConflictRuleIn(BaseModel):
    id: int | None = None
    attraction_a_id: int
    attraction_b_id: int
    severity: str = "warning"
    message: str | None = None
    active: bool = True


def _attr_conflict_to_dict(r: models.AttractionConflictRule, name_map: dict[int, str]) -> dict:
    return {
        "id": r.id,
        "attraction_a_id": r.attraction_a_id,
        "attraction_b_id": r.attraction_b_id,
        "attraction_a_name": name_map.get(r.attraction_a_id, f"#{r.attraction_a_id}"),
        "attraction_b_name": name_map.get(r.attraction_b_id, f"#{r.attraction_b_id}"),
        "severity": r.severity,
        "message": r.message,
        "active": r.active,
    }


@router.get("/attraction-conflicts")
def list_attraction_conflicts(db: Session = Depends(get_db)):
    rows = db.query(models.AttractionConflictRule).all()
    ids = {r.attraction_a_id for r in rows} | {r.attraction_b_id for r in rows}
    name_map = {a.id: a.name_zh for a in db.query(models.Attraction).filter(models.Attraction.id.in_(ids)).all()} if ids else {}
    return [_attr_conflict_to_dict(r, name_map) for r in rows]


@router.post("/attraction-conflicts", dependencies=_super_only)
def upsert_attraction_conflict(payload: AttractionConflictRuleIn, db: Session = Depends(get_db)):
    if payload.severity not in ("warning", "error"):
        raise HTTPException(400, "severity 必须 warning|error")
    if payload.attraction_a_id == payload.attraction_b_id:
        raise HTTPException(400, "两个景点不能相同")
    if payload.id:
        r = db.get(models.AttractionConflictRule, payload.id)
        if not r:
            raise HTTPException(404)
    else:
        r = models.AttractionConflictRule()
        db.add(r)
    # 规范化:始终让 a_id < b_id,避免重复方向规则
    a, b = sorted([payload.attraction_a_id, payload.attraction_b_id])
    r.attraction_a_id = a
    r.attraction_b_id = b
    r.severity = payload.severity
    r.message = payload.message
    r.active = payload.active
    db.commit()
    db.refresh(r)
    return {"id": r.id}


@router.delete("/attraction-conflicts/{rid}", dependencies=_super_only)
def delete_attraction_conflict(rid: int, db: Session = Depends(get_db)):
    r = db.get(models.AttractionConflictRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


# =============================================================
#  赌自费策略 (v0.3) — 单表 GambleStrategy 替代 NoGambleRule + 复杂算法
# =============================================================
def _strategy_to_dict(rec: models.GambleStrategy) -> dict:
    try:
        conds = json.loads(rec.conditions) if rec.conditions else []
    except Exception:
        conds = []
    return {
        "id": rec.id,
        "name": rec.name,
        "description": rec.description,
        "conditions": conds,
        "action": rec.action,
        "gamble_cny": float(rec.gamble_cny or 0),
        "extra_profit_cny": float(getattr(rec, "extra_profit_cny", 0) or 0),
        "priority": rec.priority,
        "active": rec.active,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


@router.get("/gamble-strategies")
def list_gamble_strategies(db: Session = Depends(get_db)):
    rows = db.query(models.GambleStrategy).order_by(
        models.GambleStrategy.priority.desc(), models.GambleStrategy.id
    ).all()
    return [_strategy_to_dict(r) for r in rows]


@router.post("/gamble-strategies", dependencies=_super_only)
def upsert_gamble_strategy(payload: GambleStrategyIn, db: Session = Depends(get_db)):
    if payload.id:
        r = db.get(models.GambleStrategy, payload.id)
        if not r:
            raise HTTPException(404)
    else:
        r = models.GambleStrategy()
        db.add(r)
    r.name = payload.name
    r.description = payload.description
    r.conditions = json.dumps(payload.conditions, ensure_ascii=False)
    r.action = payload.action
    r.gamble_cny = payload.gamble_cny
    r.extra_profit_cny = payload.extra_profit_cny
    r.priority = payload.priority
    r.active = payload.active
    db.commit()
    db.refresh(r)
    return _strategy_to_dict(r)


@router.delete("/gamble-strategies/{rid}", dependencies=_super_only)
def delete_gamble_strategy(rid: int, db: Session = Depends(get_db)):
    r = db.get(models.GambleStrategy, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/gamble-strategies/preview")
def preview_strategy_match(payload: GambleStrategyPreviewIn, db: Session = Depends(get_db)):
    """模拟一份行程信号 → 列出每条策略是否命中, 第一条命中即终止评估.

    UI 用: 用户填入"假想行程"参数, 看哪条策略生效, 验证设置是否正确.
    """
    from ..utils.gambling_engine import _eval_condition, ItinerarySignals

    sig = ItinerarySignals(
        total_days=payload.total_days,
        free_hours_total=payload.free_hours_total,
        pax_total=payload.pax_total,
        is_first_time_agency=payload.is_first_time_agency,
        season=payload.season,
        customer_type=payload.customer_type,
        all_meals_included=payload.all_meals_included,
        has_spa_booked=payload.has_spa_booked,
        has_water_booked=payload.has_water_booked,
        has_tea_booked=False,
        attraction_ids=set(),
        restaurant_ids=set(),
        spa_ids=set(),
        water_ids=set(),
        categories_in_itinerary=set(),
    )

    strategies = db.query(models.GambleStrategy).filter_by(active=True).order_by(
        models.GambleStrategy.priority.desc(), models.GambleStrategy.id
    ).all()

    trace = []
    matched = None
    for s in strategies:
        try:
            conds = json.loads(s.conditions) if s.conditions else []
        except Exception:
            conds = []
        results = []
        all_pass = True
        for c in conds:
            ok = _eval_condition(c, sig)
            results.append({"condition": c, "passed": ok})
            if not ok:
                all_pass = False
        item = {
            "strategy_id": s.id,
            "name": s.name,
            "priority": s.priority,
            "action": s.action,
            "gamble_cny": float(s.gamble_cny or 0),
            "conditions": results,
            "matched": all_pass,
        }
        trace.append(item)
        if all_pass and matched is None:
            matched = item
            # 命中即停; 后续策略仍展示用 evaluated=False
            for later in strategies[strategies.index(s) + 1:]:
                trace.append({
                    "strategy_id": later.id, "name": later.name,
                    "priority": later.priority, "action": later.action,
                    "gamble_cny": float(later.gamble_cny or 0),
                    "conditions": [], "matched": False, "evaluated": False,
                })
            break

    if matched:
        if matched["action"] == "skip":
            recommended = 0.0
        elif matched["action"] == "fixed":
            recommended = matched["gamble_cny"]
        else:  # per_pax
            recommended = matched["gamble_cny"] * sig.pax_total
        result_text = f"命中 [{matched['name']}] → " + (
            "不赌" if matched["action"] == "skip"
            else f"让利 ¥{recommended:.2f}/团" if matched["action"] == "per_pax"
            else f"让利 ¥{recommended:.2f}/人"
        )
    else:
        recommended = 0.0
        result_text = "无策略命中, 走默认(不让利)"

    return {
        "matched": matched,
        "recommended_cny": recommended,
        "result_text": result_text,
        "trace": trace,
        "signals": {
            "customer_type": sig.customer_type,
            "season": sig.season,
            "total_days": sig.total_days,
            "free_hours_total": sig.free_hours_total,
            "pax_total": sig.pax_total,
            "is_first_time_agency": sig.is_first_time_agency,
            "all_meals_included": sig.all_meals_included,
            "has_spa_booked": sig.has_spa_booked,
            "has_water_booked": sig.has_water_booked,
        },
    }


@router.post("/gamble-strategies/migrate-from-no-gamble", dependencies=_super_only)
def migrate_no_gamble_to_strategies(db: Session = Depends(get_db)):
    """一次性把现有 NoGambleRule 全部迁移成 GambleStrategy(action=skip).

    幂等: 如果某条 NoGambleRule.name 已在 GambleStrategy 里, 跳过.
    """
    existing_names = {s.name for s in db.query(models.GambleStrategy).all()}
    migrated = 0
    skipped = 0
    for old in db.query(models.NoGambleRule).all():
        if old.name in existing_names:
            skipped += 1
            continue
        db.add(models.GambleStrategy(
            name=old.name,
            description=old.description,
            conditions=old.conditions,
            action="skip",
            gamble_cny=Decimal(0),
            priority=old.priority,
            active=old.active,
            created_by=f"migrated_from_no_gamble_rule#{old.id}",
        ))
        migrated += 1
    db.commit()
    return {"migrated": migrated, "skipped_duplicate": skipped}


# =============================================================
#  策略胜率统计 (v0.5 P0-3) — 反哺策略库
# =============================================================
@router.get("/strategy-stats")
def get_strategy_stats(
    request: Request,
    days: int = Query(90, ge=1, le=365, description="统计窗口(天)"),
    db: Session = Depends(get_db),
):
    """每条 GambleStrategy 的命中数 / 反馈数 / 胜率 / 平均实际利润.

    权限: super_admin 看全部; agency_owner 看本社; agent / viewer → 403.
    """
    user = get_current_user(request, db)
    if user is not None and user.role in ("agent", "viewer"):
        raise HTTPException(403, "需要管理员或老板角色")

    cutoff = now_utc() - timedelta(days=days)

    # 基础查询: 在窗口内的 gamble_history (含 feedback)
    base = db.query(models.GambleHistory).filter(models.GambleHistory.created_at >= cutoff)

    # 按 agency 隔离 (agency_owner)
    if user is not None and user.role == "agency_owner":
        # 关联 quotes 表筛 agency_id
        base = base.join(models.Quote, models.Quote.id == models.GambleHistory.quote_id)
        base = base.filter(models.Quote.agency_id == user.agency_id)

    histories = base.all()

    # 按 strategy_id 聚合
    by_strategy: dict[int | None, list[models.GambleHistory]] = {}
    for h in histories:
        by_strategy.setdefault(h.strategy_id, []).append(h)

    strategies_map = {
        s.id: s for s in db.query(models.GambleStrategy).all()
    }

    out: list[dict] = []
    for sid, items in by_strategy.items():
        strat = strategies_map.get(sid) if sid else None
        feedback_items = [i for i in items if i.won_or_lost in ("won", "lost", "partial")]
        won_items = [i for i in feedback_items if i.won_or_lost == "won"]
        partial_items = [i for i in feedback_items if i.won_or_lost == "partial"]
        actual_profits = [
            float(i.profit_actual_cny) for i in feedback_items if i.profit_actual_cny is not None
        ]
        actual_revenues = [
            float(i.optional_tours_revenue_cny) for i in feedback_items
            if i.optional_tours_revenue_cny is not None
        ]
        recommended = [float(i.recommended_cny or 0) for i in items]

        out.append({
            "strategy_id": sid,
            "strategy_name": strat.name if strat else "(无策略命中 · 走兜底算法)",
            "action": strat.action if strat else None,
            "active": strat.active if strat else None,
            "hit_count": len(items),
            "feedback_count": len(feedback_items),
            "won_count": len(won_items),
            "partial_count": len(partial_items),
            "lost_count": len(feedback_items) - len(won_items) - len(partial_items),
            "win_rate": (
                round(len(won_items) / len(feedback_items), 3)
                if feedback_items else None
            ),
            "avg_actual_profit_cny": (
                round(sum(actual_profits) / len(actual_profits), 2) if actual_profits else None
            ),
            "avg_actual_revenue_cny": (
                round(sum(actual_revenues) / len(actual_revenues), 2) if actual_revenues else None
            ),
            "avg_recommended_cny": (
                round(sum(recommended) / len(recommended), 2) if recommended else 0
            ),
        })

    # 按命中数倒序; 无策略命中那条放最后
    out.sort(key=lambda x: (x["strategy_id"] is None, -x["hit_count"]))
    return {
        "window_days": days,
        "total_quotes": sum(s["hit_count"] for s in out),
        "items": out,
    }


@router.get("/no-gamble-rules/condition-types")
def list_condition_types():
    """前端用 — 返回支持的 condition.type 与示例值. v0.5.2 加 5 维度细分."""
    return [
        # ---- 客户/团队属性 ----
        {"type": "customer_type_in", "label": "客户类型属于", "value_example": ["mice", "wedding"]},
        {"type": "season_in", "label": "季节属于", "value_example": ["low"]},
        {"type": "is_first_time_agency", "label": "首次合作 B 端", "value_example": True},
        {"type": "pax_total_lt", "label": "总人数 <", "value_example": 3},
        {"type": "pax_total_gt", "label": "总人数 >", "value_example": 30},
        {"type": "total_days_lt", "label": "总天数 <", "value_example": 3},
        {"type": "total_days_gt", "label": "总天数 >", "value_example": 10},
        # ---- v0.5.2 主结构铁律 ----
        {"type": "has_any_free_activity", "label": "★ 行程含任何自由活动 (主结构铁律)", "value_example": True},
        {"type": "free_hours_lt", "label": "总自由小时 <", "value_example": 4},
        {"type": "free_hours_gt", "label": "总自由小时 >", "value_example": 12},
        # ---- v0.5.2 维度1: 酒店级别 ----
        {"type": "hotel_max_star_gte", "label": "团内最高酒店星级 ≥", "value_example": 5},
        {"type": "hotel_max_star_lte", "label": "团内最高酒店星级 ≤", "value_example": 3},
        # ---- v0.5.2 维度2: 水上项目 ----
        {"type": "water_already_booked", "label": "行程已含水上项目 (任意)", "value_example": True},
        {"type": "water_count_gt", "label": "已含水上项目数 >", "value_example": 1},
        {"type": "water_count_gte", "label": "已含水上项目数 ≥", "value_example": 2},
        # ---- v0.5.2 维度3: 自由活动 / 餐 ----
        {"type": "all_meals_included", "label": "全程含餐", "value_example": True},
        {"type": "free_days_with_meals", "label": "自由日是否含餐", "value_example": True},
        {"type": "spa_already_booked", "label": "行程已含 SPA", "value_example": True},
        # ---- v0.5.2 维度4: 儿童 ----
        {"type": "child_count_gt", "label": "儿童数 >", "value_example": 2},
        {"type": "child_ratio_gt", "label": "儿童占比 >", "value_example": 0.3},
        # ---- v0.5.2 维度5: 老年人 (55+) ----
        {"type": "senior_count_gt", "label": "老年人(55+) 数 >", "value_example": 5},
        {"type": "senior_ratio_gt", "label": "老年人(55+) 占比 >", "value_example": 0.5},
    ]
