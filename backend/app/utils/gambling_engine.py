"""赌自费推荐引擎 — v0.2 增强版.

核心改进:
1. 用户可在系统中维护"不赌自费规则" (NoGambleRule), 引擎按规则自动判断是否赌
2. 自由时间用 hours 累计 (支持半天=4h / 全天=8h), 取代旧的整天计数
3. 自费项目按 category 与行程内容做重叠检测, 已包含的不再加入预测
4. AI 信心评分集成行程结构与历史命中率
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .. import models
from ..ai import get_client

logger = logging.getLogger("bws.gamble")


CUSTOMER_FACTOR = {
    "honeymoon": 1.30,
    "family_kids": 1.15,
    "young": 1.20,
    "family": 1.00,
    "senior": 0.65,
    "mice": 0.80,
    "wedding": 0.95,
}

SEASON_FACTOR = {"high": 1.10, "shoulder": 1.00, "low": 0.90}


# ============================================================
#  数据类
# ============================================================
@dataclass
class GambleResult:
    recommended_cny: Decimal
    low_bound_cny: Decimal
    high_bound_cny: Decimal
    ai_confidence: float
    reasoning: str
    configured_optional_tours: list[dict[str, Any]]
    excluded_optional_tours: list[dict[str, Any]]  # 因覆盖被排除
    enabled: bool = True
    skip_rule: dict | None = None  # 触发的不赌规则
    extra_profit_cny_per_pax: Decimal = Decimal(0)  # v0.5.1: 命中"不赌+加利润"策略时, 反向加 ¥/人
    raw: dict[str, Any] | None = None


# ============================================================
#  工具函数
# ============================================================
def _audience_match(target_audience: str | None, customer_type: str) -> float:
    if not target_audience:
        return 0.6
    t = target_audience.lower()
    matches = {
        "honeymoon": ["蜜月", "couple"],
        "family_kids": ["亲子", "kids", "family"],
        "young": ["年轻人", "young", "网红"],
        "senior": ["老年", "senior"],
        "mice": ["mice", "商务"],
        "wedding": ["婚礼", "wedding"],
    }
    keys = matches.get(customer_type, [])
    if any(k in t for k in keys):
        return 1.0
    if "all" in t or "通用" in t:
        return 0.6
    return 0.2


def _load_config(db: Session) -> models.GambleConfig:
    cfg = db.query(models.GambleConfig).first()
    if cfg:
        return cfg
    return models.GambleConfig(
        enable_gambling=True,
        safety_ratio=0.7,
        max_loss_ratio=0.25,
        first_time_agency_factor=0.5,
        default_margin_rate=0.5,
        mice_wedding_max_cny=Decimal("150"),
    )


def _safe_json(text: str | None) -> list:
    if not text:
        return []
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ============================================================
#  行程内容信号 — 用于规则评估和自费排除
# ============================================================
@dataclass
class ItinerarySignals:
    total_days: int
    free_hours_total: int
    pax_total: int
    is_first_time_agency: bool
    season: str
    customer_type: str
    all_meals_included: bool
    has_spa_booked: bool
    has_water_booked: bool
    has_tea_booked: bool
    attraction_ids: set[int]
    restaurant_ids: set[int]
    spa_ids: set[int]
    water_ids: set[int]
    categories_in_itinerary: set[str]
    # v0.5.2 赌自费 5 维度细分:
    has_any_free_activity: bool = False        # 主结构铁律: 有任何自由活动 → 必须赌
    hotel_max_star: int = 0                    # 团内最高酒店星级 (0 = 未指定)
    water_activity_count: int = 0              # 已含水上项目数
    free_days_with_meals: bool = False         # 自由日是否含餐
    pax_child: int = 0                         # 儿童数
    child_ratio: float = 0.0                   # 儿童占比
    pax_senior: int = 0                        # 55+ 老年人数
    senior_ratio: float = 0.0                  # 老年占比


def _flight_implied_short_hours(quote: models.Quote) -> int:
    """根据航班时间推算被压缩的小时数(算入 free_hours_total).

    逻辑:
    - 标准全天可用 14h(08:00–22:00)
    - 首日:抵达后预留 60min 入住缓冲;之后到 22:00 是可用
        compressed = max(0, 14 - (22:00 - arrival_time - 60min))
    - 末日:出发前 90min 到机场;08:00 到此即可用
        compressed = max(0, 14 - (departure_time - 90min - 08:00))
    返回压缩总和(>=0).
    """
    short = 0
    try:
        if quote.arrival_at:
            arr_h = quote.arrival_at.hour + quote.arrival_at.minute / 60
            usable = max(0.0, 22.0 - (arr_h + 1.0))  # 22:00 - (arrival + 1h)
            short += max(0, int(round(14 - usable)))
        if quote.departure_at:
            dep_h = quote.departure_at.hour + quote.departure_at.minute / 60
            usable = max(0.0, (dep_h - 1.5) - 8.0)  # (departure - 1.5h) - 08:00
            short += max(0, int(round(14 - usable)))
    except Exception:
        pass
    return short


def _build_signals(quote: models.Quote, db: Session | None = None) -> ItinerarySignals:
    pax_total = max(quote.pax_adult + quote.pax_child, 1)
    free_hours_total = sum(int(d.free_hours or (8 if d.is_free else 0)) for d in quote.days)
    # 航班自动加成:首日抵达晚 / 末日离开早 → 被压缩的小时数等价于"客人没空买自费"
    free_hours_total += _flight_implied_short_hours(quote)
    total_days = quote.total_days or len(quote.days) or 1

    attr_ids: set[int] = set()
    rest_ids: set[int] = set()
    spa_ids: set[int] = set()
    water_ids: set[int] = set()
    hotel_ids: set[int] = set()
    has_tea = False

    # 检查"全程含餐": 每个非自由日 lunch + dinner 都设
    all_meals = True
    non_free_count = 0
    has_any_free = False
    free_days_with_meals = False
    water_count = 0  # 累计计数 (vs has_water_booked 的 bool)

    for d in quote.days:
        # 半天/全天自由日不计入 all_meals 检查
        is_full_free = (d.free_hours or 0) >= 8 or d.is_free
        is_partial_free = (d.free_hours or 0) >= 4 and not is_full_free
        if is_full_free or is_partial_free:
            has_any_free = True
        if is_full_free:
            # 自由日含餐: 含早 OR 安排了午晚餐
            if d.breakfast_included or d.lunch_restaurant_id or d.dinner_restaurant_id:
                free_days_with_meals = True
        if not is_full_free:
            non_free_count += 1
            # all_meals 要求每个非自由日 lunch 与 dinner 都设
            if not d.lunch_restaurant_id or not d.dinner_restaurant_id:
                all_meals = False
        for it in d.items:
            attr_ids.add(it.attraction_id)
        if d.lunch_restaurant_id:
            rest_ids.add(d.lunch_restaurant_id)
        if d.dinner_restaurant_id:
            rest_ids.add(d.dinner_restaurant_id)
        if d.spa_id:
            spa_ids.add(d.spa_id)
        if d.water_activity_id:
            water_ids.add(d.water_activity_id)
            water_count += 1
        if d.hotel_id:
            hotel_ids.add(d.hotel_id)
        if d.afternoon_tea_id:
            has_tea = True

    # 主结构铁律: 任意 free_hours > 0 (不要求 ≥4) 也要算"有自由"
    if not has_any_free:
        has_any_free = any((d.free_hours or 0) > 0 or d.is_free for d in quote.days)

    if non_free_count == 0:
        all_meals = False

    # 团内最高酒店星级 — 需要 db 才能查
    hotel_max_star = 0
    if db is not None and hotel_ids:
        try:
            stars = [
                getattr(h, "star", None) or 0
                for h in db.query(models.Hotel).filter(models.Hotel.id.in_(hotel_ids)).all()
            ]
            hotel_max_star = max(stars) if stars else 0
        except Exception:
            hotel_max_star = 0

    # 老年人 / 儿童占比
    pax_child_v = quote.pax_child or 0
    pax_senior_v = getattr(quote, "pax_senior", 0) or 0
    child_ratio_v = pax_child_v / pax_total if pax_total else 0
    senior_ratio_v = pax_senior_v / pax_total if pax_total else 0

    # categories 推断 — 简单规则: 用 attraction/restaurant 的 area / cuisine 关键词
    categories = set()
    if spa_ids:
        categories.add("spa")
    if water_ids:
        categories.add("water")
    if has_tea:
        categories.add("food_upgrade")  # 下午茶覆盖部分餐升级
    # TODO: 根据具体 attraction name 推断 sunset/sunrise/temple 等

    return ItinerarySignals(
        total_days=total_days,
        free_hours_total=free_hours_total,
        pax_total=pax_total,
        is_first_time_agency=bool(quote.is_first_time_agency),
        season=quote.season or "shoulder",
        customer_type=quote.customer_type or "family",
        all_meals_included=all_meals,
        has_spa_booked=bool(spa_ids),
        has_water_booked=bool(water_ids),
        has_tea_booked=has_tea,
        attraction_ids=attr_ids,
        restaurant_ids=rest_ids,
        spa_ids=spa_ids,
        water_ids=water_ids,
        categories_in_itinerary=categories,
        # v0.5.2 新增 5 维度信号:
        has_any_free_activity=has_any_free,
        hotel_max_star=hotel_max_star,
        water_activity_count=water_count,
        free_days_with_meals=free_days_with_meals,
        pax_child=pax_child_v,
        child_ratio=round(child_ratio_v, 3),
        pax_senior=pax_senior_v,
        senior_ratio=round(senior_ratio_v, 3),
    )


# ============================================================
#  不赌规则评估
# ============================================================
def _eval_condition(cond: dict, sig: ItinerarySignals) -> bool:
    t = cond.get("type")
    v = cond.get("value")
    try:
        if t == "customer_type_in":
            return sig.customer_type in (v or [])
        if t == "free_hours_lt":
            return sig.free_hours_total < int(v)
        if t == "free_hours_gt":
            return sig.free_hours_total > int(v)
        if t == "total_days_lt":
            return sig.total_days < int(v)
        if t == "total_days_gt":
            return sig.total_days > int(v)
        if t == "pax_total_lt":
            return sig.pax_total < int(v)
        if t == "pax_total_gt":
            return sig.pax_total > int(v)
        if t == "is_first_time_agency":
            return bool(v) == sig.is_first_time_agency
        if t == "all_meals_included":
            return sig.all_meals_included == bool(v)
        if t == "spa_already_booked":
            return sig.has_spa_booked == bool(v)
        if t == "water_already_booked":
            return sig.has_water_booked == bool(v)
        if t == "season_in":
            return sig.season in (v or [])
        # ============= v0.5.2 五维度细分 =============
        if t == "has_any_free_activity":
            return sig.has_any_free_activity == bool(v)
        if t == "hotel_max_star_gte":
            return sig.hotel_max_star >= int(v)
        if t == "hotel_max_star_lte":
            return 0 < sig.hotel_max_star <= int(v)
        if t == "water_count_gt":
            return sig.water_activity_count > int(v)
        if t == "water_count_gte":
            return sig.water_activity_count >= int(v)
        if t == "free_days_with_meals":
            return sig.free_days_with_meals == bool(v)
        if t == "child_count_gt":
            return sig.pax_child > int(v)
        if t == "child_ratio_gt":
            return sig.child_ratio > float(v)
        if t == "senior_count_gt":
            return sig.pax_senior > int(v)
        if t == "senior_ratio_gt":
            return sig.senior_ratio > float(v)
    except Exception:
        logger.exception("evaluate condition failed: %s", cond)
    return False


def _check_no_gamble_rules(db: Session, sig: ItinerarySignals) -> models.NoGambleRule | None:
    rules = (
        db.query(models.NoGambleRule)
        .filter_by(active=True)
        .order_by(models.NoGambleRule.priority.desc(), models.NoGambleRule.id)
        .all()
    )
    for rule in rules:
        conds = _safe_json(rule.conditions)
        if not conds:
            continue
        if all(_eval_condition(c, sig) for c in conds):
            return rule
    return None


# ============================================================
#  自费项目过滤 — 基于 category + 重叠 ID
# ============================================================
def _build_ot_listings(
    quote: models.Quote, db: Session, sig: ItinerarySignals
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """计算 (configured, excluded) 自费清单 — 供策略命中后展示用 (P1-7).

    与主路径(主流程兜底)共享计算逻辑, 但不计算 expected_revenue/profit.
    """
    dest_codes = quote.destination_codes.split(",") if quote.destination_codes else []
    dest_ids = [
        d.id for d in db.query(models.Destination).filter(
            models.Destination.code.in_(dest_codes)
        ).all()
    ]
    q = db.query(models.OptionalTour).filter(models.OptionalTour.status == 1)
    if dest_ids:
        q = q.filter(models.OptionalTour.destination_id.in_(dest_ids))
    optionals = q.all()

    configured: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for ot in optionals:
        overlap, reason = _is_overlapping(ot, sig)
        if overlap:
            excluded.append({
                "id": ot.id, "name": ot.name_zh,
                "sale_price_cny": float(ot.sale_price_cny),
                "category": ot.category,
                "exclusion_reason": reason,
            })
            continue
        match = _audience_match(ot.target_audience, sig.customer_type)
        purchase_rate = float(ot.historical_purchase_rate or 0.5) * match
        rev = float(ot.sale_price_cny) * purchase_rate
        configured.append({
            "id": ot.id, "name": ot.name_zh,
            "category": ot.category,
            "sale_price_cny": float(ot.sale_price_cny),
            "predicted_purchase_rate": round(purchase_rate, 3),
            "expected_revenue_cny": round(rev, 2),
        })
    return configured, excluded


def _is_overlapping(ot: models.OptionalTour, sig: ItinerarySignals) -> tuple[bool, str]:
    """返回 (是否被覆盖, 原因)"""
    cat = (ot.category or "").lower()
    # 1. 显式 ID 重叠
    if ot.overlap_attraction_ids:
        for aid in _safe_json(ot.overlap_attraction_ids):
            if int(aid) in sig.attraction_ids:
                return True, f"行程已含景点 ID={aid}"
    if ot.overlap_spa_ids:
        for sid in _safe_json(ot.overlap_spa_ids):
            if int(sid) in sig.spa_ids:
                return True, f"行程已含 SPA ID={sid}"
    if ot.overlap_water_ids:
        for wid in _safe_json(ot.overlap_water_ids):
            if int(wid) in sig.water_ids:
                return True, f"行程已含水上 ID={wid}"
    if ot.overlap_restaurant_ids:
        for rid in _safe_json(ot.overlap_restaurant_ids):
            if int(rid) in sig.restaurant_ids:
                return True, f"行程已含餐厅 ID={rid}"
    # 2. category 类型重叠
    if cat == "spa" and sig.has_spa_booked:
        return True, "行程已安排 SPA, 自费 SPA 升级被替代"
    if cat == "water" and sig.has_water_booked:
        return True, "行程已安排水上项目"
    if cat == "food_upgrade" and sig.all_meals_included:
        return True, "行程全含餐, 餐升级类自费购买率显著降低"
    return False, ""


# ============================================================
#  策略评估 (v0.3) — 用户在 UI 自定义的 GambleStrategy 表
# ============================================================
def _check_gamble_strategies(db: Session, sig: ItinerarySignals) -> models.GambleStrategy | None:
    """按 priority 倒序评估; 第一条 conditions 全部命中即返回."""
    strategies = (
        db.query(models.GambleStrategy)
        .filter_by(active=True)
        .order_by(models.GambleStrategy.priority.desc(), models.GambleStrategy.id)
        .all()
    )
    for s in strategies:
        conds = _safe_json(s.conditions)
        if not conds:
            continue
        if all(_eval_condition(c, sig) for c in conds):
            return s
    return None


# ============================================================
#  推荐主函数 (v0.3)
# ============================================================
def recommend(quote: models.Quote, db: Session) -> GambleResult:
    cfg = _load_config(db)
    if not cfg.enable_gambling:
        return GambleResult(
            recommended_cny=Decimal(0), low_bound_cny=Decimal(0), high_bound_cny=Decimal(0),
            ai_confidence=0,
            reasoning="管理员关闭了赌自费功能",
            configured_optional_tours=[], excluded_optional_tours=[],
            enabled=False,
        )

    sig = _build_signals(quote, db)

    # ---- v0.5.2 业务铁律 ----
    # 用户原话: "主结构只要有自由活动, 不能判定不赌自费"
    # 实现: 命中 skip 策略后, 如果 sig.has_any_free_activity == True, 警告业务员
    #       (不强制改 action — 仍尊重用户明确写的策略, 但 reasoning 里高亮)
    iron_rule_warning = ""
    if sig.has_any_free_activity:
        iron_rule_warning = " [⚠ 提示: 行程含自由活动, 通常应赌; 当前命中的策略仍会执行]"

    # ---- 0a. v0.3 主路径: GambleStrategy 优先 ----
    strategy = _check_gamble_strategies(db, sig)
    if strategy is not None:
        action = strategy.action
        gamble_cny = Decimal(str(strategy.gamble_cny or 0))
        if action == "skip":
            extra = Decimal(str(getattr(strategy, "extra_profit_cny", 0) or 0))
            reasoning_msg = f"命中策略 [{strategy.name}] → 不赌"
            if extra > 0:
                reasoning_msg += f"; 反向加 ¥{extra}/人 利润"
            reasoning_msg += iron_rule_warning
            return GambleResult(
                recommended_cny=Decimal(0), low_bound_cny=Decimal(0), high_bound_cny=Decimal(0),
                ai_confidence=0.95,
                reasoning=reasoning_msg,
                configured_optional_tours=[], excluded_optional_tours=[],
                enabled=False,
                extra_profit_cny_per_pax=extra,
                skip_rule={
                    "id": strategy.id, "name": strategy.name,
                    "description": strategy.description,
                    "action": "skip",
                    "extra_profit_cny": float(extra),
                    "conditions": _safe_json(strategy.conditions),
                },
            )
        # P1-7: 命中 fixed/per_pax 策略时仍要带上自费推荐清单, 业务员需要看
        # "我让的 ¥X 是希望客户买这几个自费"的逻辑
        configured, excluded = _build_ot_listings(quote, db, sig)
        if action == "per_pax":
            total = gamble_cny * sig.pax_total
            return GambleResult(
                recommended_cny=total,
                low_bound_cny=total * Decimal("0.8"),
                high_bound_cny=total * Decimal("1.2"),
                ai_confidence=0.9,
                reasoning=f"命中策略 [{strategy.name}] → 按人让利 ¥{gamble_cny}/人 × {sig.pax_total} = ¥{total}",
                configured_optional_tours=configured,
                excluded_optional_tours=excluded,
                skip_rule={
                    "id": strategy.id, "name": strategy.name,
                    "description": strategy.description,
                    "action": "per_pax",
                    "gamble_cny_per_pax": float(gamble_cny),
                    "conditions": _safe_json(strategy.conditions),
                },
            )
        # action == "fixed" 单人值
        return GambleResult(
            recommended_cny=gamble_cny,
            low_bound_cny=gamble_cny * Decimal("0.8"),
            high_bound_cny=gamble_cny * Decimal("1.2"),
            ai_confidence=0.9,
            reasoning=f"命中策略 [{strategy.name}] → 固定让利 ¥{gamble_cny}/人",
            configured_optional_tours=configured,
            excluded_optional_tours=excluded,
            skip_rule={
                "id": strategy.id, "name": strategy.name,
                "description": strategy.description,
                "action": "fixed",
                "gamble_cny": float(gamble_cny),
                "conditions": _safe_json(strategy.conditions),
            },
        )

    # ---- 0b. 无策略命中 → 兜底走旧 NoGambleRule (v0.2 兼容期) ----
    triggered = _check_no_gamble_rules(db, sig)
    if triggered:
        return GambleResult(
            recommended_cny=Decimal(0), low_bound_cny=Decimal(0), high_bound_cny=Decimal(0),
            ai_confidence=0.95,
            reasoning=f"触发不赌规则: {triggered.name} — {triggered.description or ''}",
            configured_optional_tours=[], excluded_optional_tours=[],
            enabled=False,
            skip_rule={
                "id": triggered.id, "name": triggered.name,
                "description": triggered.description,
                "conditions": _safe_json(triggered.conditions),
            },
        )

    # ---- 1. 自由时间因子 (基于 hours 而非 days) ----
    total_hours = sig.total_days * 8.0  # 每天 8 小时活动时间
    free_ratio = sig.free_hours_total / total_hours if total_hours else 0
    free_time_factor = min(free_ratio * 1.5, 1.0)
    if sig.free_hours_total == 0:
        # 无自由时间 — 直接判定不赌, 因为没机会卖自费
        return GambleResult(
            recommended_cny=Decimal(0), low_bound_cny=Decimal(0), high_bound_cny=Decimal(0),
            ai_confidence=0.95,
            reasoning="行程无自由活动时间, 无赌自费基础",
            configured_optional_tours=[], excluded_optional_tours=[],
            enabled=False,
        )

    # ---- 2. 系数 ----
    cust_factor = CUSTOMER_FACTOR.get(sig.customer_type, 1.0)
    season_factor = SEASON_FACTOR.get(sig.season, 1.0)

    # ---- 3. 加载并过滤自费项目 ----
    dest_codes = quote.destination_codes.split(",") if quote.destination_codes else []
    dest_ids = [d.id for d in db.query(models.Destination).filter(models.Destination.code.in_(dest_codes)).all()]
    q = db.query(models.OptionalTour).filter(models.OptionalTour.status == 1)
    if dest_ids:
        q = q.filter(models.OptionalTour.destination_id.in_(dest_ids))
    optionals = q.all()

    expected_revenue = Decimal(0)
    configured: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for ot in optionals:
        overlap, reason = _is_overlapping(ot, sig)
        if overlap:
            excluded.append({
                "id": ot.id, "name": ot.name_zh,
                "sale_price_cny": float(ot.sale_price_cny),
                "category": ot.category,
                "exclusion_reason": reason,
            })
            continue
        match = _audience_match(ot.target_audience, sig.customer_type)
        purchase_rate = float(ot.historical_purchase_rate or 0.5) * match
        rev = Decimal(str(float(ot.sale_price_cny) * purchase_rate))
        expected_revenue += rev
        configured.append({
            "id": ot.id, "name": ot.name_zh,
            "category": ot.category,
            "sale_price_cny": float(ot.sale_price_cny),
            "predicted_purchase_rate": round(purchase_rate, 3),
            "expected_revenue_cny": round(float(rev), 2),
        })

    # 如果可推荐自费已经清空 → 不赌
    if not configured:
        return GambleResult(
            recommended_cny=Decimal(0), low_bound_cny=Decimal(0), high_bound_cny=Decimal(0),
            ai_confidence=0.9,
            reasoning="所有自费项目均被行程覆盖或无可用项, 无赌空间",
            configured_optional_tours=[], excluded_optional_tours=excluded,
            enabled=False,
        )

    # ---- 4. 期望毛利与推荐 ----
    margin_rate = float(cfg.default_margin_rate)
    expected_profit = float(expected_revenue) * margin_rate * free_time_factor * cust_factor * season_factor
    recommended = expected_profit * float(cfg.safety_ratio)
    low_bound = recommended * 0.6
    high_bound = recommended * 1.2

    # ---- 5. 风险护栏 ----
    pax_total = sig.pax_total
    cost_per_pax = float(quote.cost_cny_total or 0) / pax_total if pax_total else 0
    max_loss = cost_per_pax * float(cfg.max_loss_ratio)
    notes: list[str] = []
    if recommended > max_loss and max_loss > 0:
        notes.append(f"原推荐 {recommended:.0f} 触发最大亏损护栏 {max_loss:.0f}")
        recommended = max_loss
        high_bound = max_loss
        low_bound = min(low_bound, max_loss)

    if sig.is_first_time_agency:
        recommended *= float(cfg.first_time_agency_factor)
        low_bound *= float(cfg.first_time_agency_factor)
        high_bound *= float(cfg.first_time_agency_factor)
        notes.append(f"首次合作 B 端 ×{cfg.first_time_agency_factor}")

    if sig.customer_type in ("mice", "wedding"):
        cap = float(cfg.mice_wedding_max_cny)
        if recommended > cap:
            notes.append(f"MICE/婚礼 强制上限 ¥{cap}")
            recommended = cap
            high_bound = cap
            low_bound = min(low_bound, cap)

    # ---- 6. AI 信心评估 ----
    ai_payload = {
        "free_hours_total": sig.free_hours_total,
        "total_days": sig.total_days,
        "free_ratio": round(free_ratio, 2),
        "customer_type": sig.customer_type,
        "season": sig.season,
        "is_first_time_agency": sig.is_first_time_agency,
        "all_meals_included": sig.all_meals_included,
        "has_spa_booked": sig.has_spa_booked,
        "has_water_booked": sig.has_water_booked,
        "available_optionals": len(configured),
        "excluded_optionals": len(excluded),
        "expected_revenue_cny": round(float(expected_revenue), 2),
        "expected_profit_cny": round(expected_profit, 2),
        "recommended_cny": round(recommended, 2),
    }
    ai_text = get_client().chat_text(
        system="你是旅游行业资深销售经理. 根据给定数据评估赌自费成功概率. 返回严格 JSON: {\"confidence\":0-1, \"reasoning\":\"...\"}",
        user=f"评估这次赌自费的胜率:\n{json.dumps(ai_payload, ensure_ascii=False)}",
    )
    confidence = 0.7
    reasoning = "基于产品结构与历史经验给出推荐"
    try:
        parsed = json.loads(ai_text)
        confidence = float(parsed.get("confidence", 0.7))
        reasoning = parsed.get("reasoning", reasoning)
    except Exception:
        pass

    if notes:
        reasoning = "; ".join([reasoning] + notes)
    if excluded:
        reasoning += f" | 已排除 {len(excluded)} 个被行程覆盖的自费项"

    return GambleResult(
        recommended_cny=Decimal(str(round(recommended, 2))),
        low_bound_cny=Decimal(str(round(low_bound, 2))),
        high_bound_cny=Decimal(str(round(high_bound, 2))),
        ai_confidence=round(confidence, 2),
        reasoning=reasoning,
        configured_optional_tours=configured,
        excluded_optional_tours=excluded,
        raw=ai_payload,
    )
