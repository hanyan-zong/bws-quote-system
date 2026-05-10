"""行程合理性校验引擎 — 距离矩阵 + 时间预算 + 车型限制 + AI 评估."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..ai import get_client

logger = logging.getLogger("bws.feasibility")

PEAK_COEF = {
    "morning_peak": 1.40,
    "evening_peak": 1.55,
    "holiday": 1.65,
    "normal": 1.00,
}

# 默认车型限制 — 母库 RESTRICTIONS dict 的精简版
DEFAULT_VEHICLE_RESTRICTIONS = {
    35: ["Monkey Forest", "Canggu Villa", "BTDC Inner", "Sanur Beach Walk", "Ubud Center", "猴林", "乌布中心"],
    25: ["Monkey Forest", "Canggu Villa", "猴林"],
    17: [],
    7: [],
}


@dataclass
class DayReport:
    day_index: int
    feasible: bool = True
    drive_minutes: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    ai_review: dict[str, Any] | None = None


@dataclass
class FeasibilityReport:
    overall_feasible: bool = True
    days: list[DayReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_feasible": self.overall_feasible,
            "days": [
                {
                    "day_index": d.day_index,
                    "feasible": d.feasible,
                    "drive_minutes": d.drive_minutes,
                    "errors": d.errors,
                    "warnings": d.warnings,
                    "suggestions": d.suggestions,
                    "ai_review": d.ai_review,
                }
                for d in self.days
            ],
        }


def get_distance_minutes(
    db: Session,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    period: str = "normal",
) -> int:
    """查表; 缺数据时返回保守默认 30 分钟."""
    if from_type == to_type and from_id == to_id:
        return 0
    rec = (
        db.query(models.Distance)
        .filter(
            models.Distance.from_type == from_type,
            models.Distance.from_id == from_id,
            models.Distance.to_type == to_type,
            models.Distance.to_id == to_id,
        )
        .first()
    )
    if not rec:
        # 反向查
        rec = (
            db.query(models.Distance)
            .filter(
                models.Distance.from_type == to_type,
                models.Distance.from_id == to_id,
                models.Distance.to_type == from_type,
                models.Distance.to_id == from_id,
            )
            .first()
        )
    if not rec:
        return 30  # 兜底默认值
    field_name = {"normal": "normal_minutes", "peak": "peak_minutes", "holiday": "holiday_minutes"}.get(
        period, "normal_minutes"
    )
    val = getattr(rec, field_name) or rec.normal_minutes
    return int(val or 30)


def get_time_budget(db: Session, destination_id: int | None = None) -> models.TimeBudgetConfig:
    cfg = (
        db.query(models.TimeBudgetConfig)
        .filter(or_(models.TimeBudgetConfig.destination_id == destination_id, models.TimeBudgetConfig.destination_id.is_(None)))
        .order_by(models.TimeBudgetConfig.destination_id.desc().nullslast())
        .first()
    )
    if cfg:
        return cfg
    # 返回默认值实例(不入库)
    return models.TimeBudgetConfig(
        max_drive_minutes_per_day=300,
        max_drive_warn_minutes=240,
        morning_peak_coef=1.40,
        evening_peak_coef=1.55,
        holiday_coef=1.65,
        hotel_to_first_max_minutes=90,
        airport_buffer_minutes=60,
    )


def is_holiday(d: Any) -> bool:
    """v0.1 简化: 周末视为节假日, 中国春节 + 印尼独立日另算(待扩)."""
    if d is None:
        return False
    try:
        return d.weekday() in (5, 6)
    except Exception:
        return False


def vehicle_restrictions_for(seat: int) -> list[str]:
    return DEFAULT_VEHICLE_RESTRICTIONS.get(seat, [])


def _get_distance_record(
    db: Session, from_type: str, from_id: int, to_type: str, to_id: int
) -> models.Distance | None:
    rec = (
        db.query(models.Distance)
        .filter_by(from_type=from_type, from_id=from_id, to_type=to_type, to_id=to_id)
        .first()
    )
    if not rec:
        rec = (
            db.query(models.Distance)
            .filter_by(from_type=to_type, from_id=to_id, to_type=from_type, to_id=from_id)
            .first()
        )
    return rec


def check_quote(quote: models.Quote, db: Session, run_ai_review: bool = True) -> FeasibilityReport:
    report = FeasibilityReport(overall_feasible=True)
    cfg = get_time_budget(db)

    for day in quote.days:
        d_report = DayReport(day_index=day.day_index)

        # 半天/全天自由 — 部分跳过
        is_full_free = (day.free_hours or 0) >= 8 or day.is_free
        if is_full_free:
            d_report.warnings.append("自由活动日 — 跳过路线校验")
            report.days.append(d_report)
            continue
        if day.free_hours and day.free_hours > 0:
            d_report.warnings.append(f"半天自由活动({day.free_hours}h) — 仅校验非自由时段")

        # 收集 POI
        pois: list[tuple[str, int, str]] = []  # (type, id, name)
        if day.hotel_id:
            h = db.get(models.Hotel, day.hotel_id)
            if h:
                pois.append(("hotel", h.id, h.name_zh))
        for item in day.items:
            a = db.get(models.Attraction, item.attraction_id)
            if a:
                pois.append(("attraction", a.id, a.name_zh))
        if day.lunch_restaurant_id:
            r = db.get(models.Restaurant, day.lunch_restaurant_id)
            if r:
                pois.append(("restaurant", r.id, f"午餐:{r.name_zh}"))
        if day.dinner_restaurant_id:
            r = db.get(models.Restaurant, day.dinner_restaurant_id)
            if r:
                pois.append(("restaurant", r.id, f"晚餐:{r.name_zh}"))
        if day.hotel_id:
            h = db.get(models.Hotel, day.hotel_id)
            if h:
                pois.append(("hotel", h.id, h.name_zh + "(回)"))

        # 当日车型
        vehicle = db.get(models.Vehicle, day.vehicle_id) if day.vehicle_id else None

        # 总驾驶时间 + 单段校验 (车型敏感)
        period = "holiday" if is_holiday(day.date) else "normal"
        total_drive = 0
        for i in range(len(pois) - 1):
            t1, id1, n1 = pois[i]
            t2, id2, n2 = pois[i + 1]
            rec = _get_distance_record(db, t1, id1, t2, id2)
            mins = get_distance_minutes(db, t1, id1, t2, id2, period)
            total_drive += mins

            # 车型 vs 该路段最大允许座位
            if vehicle and rec:
                if rec.vehicle_max_seat is not None and vehicle.seat_count > rec.vehicle_max_seat:
                    d_report.errors.append(
                        f"路段 {n1} → {n2}: 该路段最大允许 {rec.vehicle_max_seat} 座, 当前 {vehicle.seat_count} 座 {vehicle.vehicle_type} 不可通行"
                    )
                    d_report.feasible = False
                elif rec.vehicle_warn_seat is not None and vehicle.seat_count > rec.vehicle_warn_seat:
                    d_report.warnings.append(
                        f"路段 {n1} → {n2}: 当前 {vehicle.seat_count} 座超过推荐 {rec.vehicle_warn_seat} 座, 山路/小巷可能慢"
                    )

            # 车型 vs 单段最长驾驶
            if vehicle and vehicle.max_single_leg_minutes and mins > vehicle.max_single_leg_minutes:
                d_report.errors.append(
                    f"路段 {n1} → {n2} 用时 {mins} min 超过 {vehicle.seat_count} 座车单段上限 {vehicle.max_single_leg_minutes} min"
                )
                d_report.feasible = False

        d_report.drive_minutes = total_drive

        # ---- Tier 1 硬约束: 总驾驶 ----
        # 车型自身的 daily 限制 优先于全局
        daily_cap = (vehicle.max_daily_minutes if vehicle and vehicle.max_daily_minutes else cfg.max_drive_minutes_per_day)
        if total_drive > daily_cap:
            d_report.errors.append(
                f"Day {day.day_index} 总驾驶 {total_drive} 分钟超过{'车型' if vehicle and vehicle.max_daily_minutes else '全局'}上限 {daily_cap} 分钟"
            )
            d_report.feasible = False

        # 车型禁入区域 (legacy)
        if vehicle:
            restricts: list[str] = []
            if vehicle.restrictions:
                try:
                    restricts = json.loads(vehicle.restrictions)
                except Exception:
                    restricts = []
            if not restricts:
                restricts = vehicle_restrictions_for(vehicle.seat_count)
            for poi_type, poi_id, _ in pois:
                if poi_type == "attraction":
                    a = db.get(models.Attraction, poi_id)
                    if a and a.area:
                        for word in restricts:
                            if word and word in a.area:
                                d_report.errors.append(
                                    f"{vehicle.seat_count}座 {vehicle.vehicle_type} 不能进入区域 {a.area} (景点 {a.name_zh})"
                                )
                                d_report.feasible = False

        # 闭馆时段(简化: 仅检查抵达时间是否在 close_time 后)
        # 暂不实现复杂时序推算, 留 v0.2

        # ---- 区域不兼容规则 (v0.2.3) ----
        # 住宿区域 vs 景点区域,违反 AreaRule 时按 severity 标记
        hotel_area = None
        if day.hotel_id:
            h = db.get(models.Hotel, day.hotel_id)
            if h and h.area:
                hotel_area = h.area
        if hotel_area:
            attraction_areas: dict[str, str] = {}  # area -> attraction_name (任一即可)
            for item in day.items:
                a = db.get(models.Attraction, item.attraction_id)
                if a and a.area:
                    attraction_areas.setdefault(a.area, a.name_zh)
            if attraction_areas:
                rules = (
                    db.query(models.AreaRule)
                    .filter(
                        models.AreaRule.active == True,  # noqa: E712
                        models.AreaRule.hotel_area == hotel_area,
                        models.AreaRule.excluded_attraction_area.in_(list(attraction_areas.keys())),
                    )
                    .all()
                )
                for r in rules:
                    attr_name = attraction_areas.get(r.excluded_attraction_area, "")
                    msg = r.message or f"住 {r.hotel_area} 时不建议去 {r.excluded_attraction_area}"
                    full_msg = f"[区域规则] {attr_name}({r.excluded_attraction_area}): {msg}"
                    if r.severity == "error":
                        d_report.errors.append(full_msg)
                        d_report.feasible = False
                    else:
                        d_report.warnings.append(full_msg)

        # ---- 景点互斥规则 (v0.2.4) ----
        # 当日两景点匹配规则 → error/warning
        attr_ids_today = [item.attraction_id for item in day.items]
        if len(attr_ids_today) >= 2:
            attr_id_set = set(attr_ids_today)
            conflict_rules = db.query(models.AttractionConflictRule).filter(
                models.AttractionConflictRule.active == True,  # noqa: E712
                models.AttractionConflictRule.attraction_a_id.in_(attr_ids_today),
                models.AttractionConflictRule.attraction_b_id.in_(attr_ids_today),
            ).all()
            attr_name_map = {a.id: a.name_zh for a in db.query(models.Attraction).filter(models.Attraction.id.in_(attr_id_set)).all()}
            for r in conflict_rules:
                if r.attraction_a_id in attr_id_set and r.attraction_b_id in attr_id_set:
                    name_a = attr_name_map.get(r.attraction_a_id, f"#{r.attraction_a_id}")
                    name_b = attr_name_map.get(r.attraction_b_id, f"#{r.attraction_b_id}")
                    msg = r.message or f"{name_a} 与 {name_b} 不建议同日"
                    full = f"[景点互斥] {name_a} ↔ {name_b}: {msg}"
                    if r.severity == "error":
                        d_report.errors.append(full)
                        d_report.feasible = False
                    else:
                        d_report.warnings.append(full)

        # ---- Tier 2 软约束 ----
        if cfg.max_drive_warn_minutes < total_drive <= cfg.max_drive_minutes_per_day:
            d_report.warnings.append(f"驾驶 {total_drive} 分钟偏紧 (>预警 {cfg.max_drive_warn_minutes})")

        if day.hotel_id and day.items:
            first_attr_id = day.items[0].attraction_id
            mins_to_first = get_distance_minutes(db, "hotel", day.hotel_id, "attraction", first_attr_id, period)
            if mins_to_first > cfg.hotel_to_first_max_minutes:
                d_report.warnings.append(
                    f"早上首站距酒店 {mins_to_first} 分钟 (>{cfg.hotel_to_first_max_minutes})，建议改为下午景点或换酒店"
                )

        # ---- Tier 3 AI 评估 ----
        if run_ai_review and pois:
            ai_result = _run_ai_review(pois, day, quote)
            d_report.ai_review = ai_result

        # 失败时给替代方案 (基础规则)
        if not d_report.feasible or d_report.errors:
            d_report.suggestions = _generate_suggestions(day, pois, total_drive, cfg)

        if not d_report.feasible:
            report.overall_feasible = False
        report.days.append(d_report)

    return report


def _run_ai_review(pois: list[tuple[str, int, str]], day: models.QuoteDay, quote: models.Quote) -> dict[str, Any]:
    client = get_client()
    route = " → ".join(p[2] for p in pois)
    user_msg = f"""请评估以下巴厘地接一日行程是否合理:

日期: {day.date or '未指定'}
人数: {quote.pax_adult + quote.pax_child}
车型: {day.vehicle_id and 'vehicle_id=' + str(day.vehicle_id) or '未选'}
路线: {route}

请输出 JSON: {{"score": 0-10, "issues": ["..."], "improved_route": ["..."]}}
仅返回 JSON 无其他文字。"""

    text = client.chat_text(
        system="你是巴厘岛资深地接调度,熟悉景点距离与堵车规律.要求返回严格 JSON.",
        user=user_msg,
    )
    try:
        return json.loads(text)
    except Exception:
        # 尝试提取 JSON 块
        try:
            l = text.index("{")
            r = text.rindex("}")
            return json.loads(text[l:r + 1])
        except Exception:
            return {"score": None, "issues": [], "improved_route": [], "raw": text}


def _generate_suggestions(
    day: models.QuoteDay,
    pois: list[tuple[str, int, str]],
    total_drive: int,
    cfg: models.TimeBudgetConfig,
) -> list[dict[str, Any]]:
    sugs: list[dict[str, Any]] = []
    if total_drive > cfg.max_drive_minutes_per_day:
        sugs.append(
            {
                "type": "remove_dinner",
                "description": "去掉晚餐安排或改为离酒店较近的餐厅",
                "delta_drive_minutes_estimate": -120,
                "patch": {"dinner_restaurant_id": None},
            }
        )
        sugs.append(
            {
                "type": "split_to_next_day",
                "description": "把当日最后一个景点挪到次日",
                "delta_drive_minutes_estimate": -90,
                "patch": None,
            }
        )
    if not sugs:
        sugs.append({"type": "manual", "description": "请人工调整顺序", "patch": None})
    return sugs
