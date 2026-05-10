"""v0.6 — 把 AI 解析出的"行程意向"匹配到资源库实际 ID.

核心: AI 抽出的是文字 ("巴厘岛 The Mulia"), 数据库里是 ID. 用 fuzzy 匹配找到最佳 hit.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from .. import models


# ============================================================
#  字符串相似度 — 简易实现, 不依赖外部 fuzzywuzzy
# ============================================================
def _normalize(s: str) -> str:
    """去除空格/标点/大小写."""
    if not s:
        return ""
    s = re.sub(r"[\s\-_·.,()（）&/\\\[\]【】]", "", str(s))
    return s.lower()


def _similarity(a: str, b: str) -> float:
    """返回 0~1 的相似度. 简化算法: 子串包含 + 字符重合率."""
    a, b = _normalize(a), _normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # 完全包含
    if a in b or b in a:
        return 0.85
    # 字符重合度 (jaccard)
    set_a, set_b = set(a), set(b)
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _best_match(query: str, items: list, name_fields=("name_zh", "name_en", "name")) -> tuple[Any, float]:
    """返回 (best_item, score). 没匹配返回 (None, 0)."""
    if not query or not items:
        return None, 0.0
    best, best_score = None, 0.0
    for it in items:
        for fld in name_fields:
            v = getattr(it, fld, None)
            if not v:
                continue
            s = _similarity(query, v)
            if s > best_score:
                best, best_score = it, s
    return best, best_score


# ============================================================
#  匹配器 — 把行程意向 dict 转成可写库的 quote payload
# ============================================================
def match_itinerary_to_resources(
    quote_draft: dict[str, Any], db: Session, threshold: float = 0.5
) -> tuple[dict[str, Any], list[dict]]:
    """根据 AI 解析的 quote_draft, 匹配真实资源 ID, 返回 (resolved_draft, match_log).

    match_log 是逐条匹配记录, 用于前端"AI 这样匹配的, 你确认对不对"的展示.
    """
    if not quote_draft:
        return {}, []

    log: list[dict] = []

    # 预加载所有资源 (一次性查询, 避免 N+1)
    hotels = db.query(models.Hotel).filter(models.Hotel.status == 1).all()
    hotel_rooms_by_hotel: dict[int, list] = {}
    for r in db.query(models.HotelRoom).all():
        hotel_rooms_by_hotel.setdefault(r.hotel_id, []).append(r)
    attractions = db.query(models.Attraction).filter(models.Attraction.status == 1).all()
    restaurants = db.query(models.Restaurant).filter(models.Restaurant.status == 1).all()
    vehicles = db.query(models.Vehicle).filter(models.Vehicle.status == 1).all()
    guides = db.query(models.Guide).filter(models.Guide.status == 1).all()
    spas = db.query(models.SpaPackage).filter(models.SpaPackage.status == 1).all()
    waters = db.query(models.WaterActivity).filter(models.WaterActivity.status == 1).all()
    teas = db.query(models.AfternoonTea).filter(models.AfternoonTea.status == 1).all()

    def _match_log(day_index: int, kind: str, query: str, item, score: float) -> None:
        log.append({
            "day_index": day_index, "kind": kind,
            "query": query,
            "matched_id": item.id if item else None,
            "matched_name": getattr(item, "name_zh", None) or getattr(item, "name", None) if item else None,
            "score": round(score, 3),
            "accepted": item is not None and score >= threshold,
        })

    out_days: list[dict] = []
    for d in quote_draft.get("days", []) or []:
        d_out = dict(d)  # shallow copy
        di = d.get("day_index", 0)

        # ---- 酒店 ----
        if d.get("hotel_name"):
            h, score = _best_match(d["hotel_name"], hotels, name_fields=("name_zh", "name_en"))
            _match_log(di, "hotel", d["hotel_name"], h, score)
            if h and score >= threshold:
                d_out["hotel_id"] = h.id
                # 自动选第一个房型
                rooms = hotel_rooms_by_hotel.get(h.id, [])
                if rooms:
                    # 优先匹配 room_type_request
                    if d.get("room_type_request"):
                        r, rs = _best_match(d["room_type_request"], rooms, name_fields=("room_type",))
                        d_out["hotel_room_id"] = (r.id if r and rs >= 0.4 else rooms[0].id)
                    else:
                        d_out["hotel_room_id"] = rooms[0].id
            else:
                d_out["hotel_id"] = None
                d_out["hotel_room_id"] = None

        # ---- 车辆 ----
        if d.get("vehicle_request"):
            v, score = _best_match(d["vehicle_request"], vehicles, name_fields=("vehicle_type",))
            _match_log(di, "vehicle", d["vehicle_request"], v, score)
            d_out["vehicle_id"] = v.id if v and score >= threshold else (vehicles[0].id if vehicles else None)

        # ---- 导游 ----
        if d.get("guide_required"):
            d_out["guide_id"] = guides[0].id if guides else None
            _match_log(di, "guide", "需要导游", guides[0] if guides else None, 1.0 if guides else 0)

        # ---- 餐厅 ----
        for label, req_field, id_field in [
            ("午餐", "lunch_request", "lunch_restaurant_id"),
            ("晚餐", "dinner_request", "dinner_restaurant_id"),
        ]:
            if d.get(req_field):
                r, score = _best_match(d[req_field], restaurants)
                _match_log(di, label, d[req_field], r, score)
                if r and score >= threshold:
                    d_out[id_field] = r.id

        # ---- SPA / 水上 / 下午茶 ----
        for req_field, id_field, items, kind in [
            ("spa_request", "spa_id", spas, "SPA"),
            ("water_activity_request", "water_activity_id", waters, "水上"),
            ("afternoon_tea_request", "afternoon_tea_id", teas, "下午茶"),
        ]:
            if d.get(req_field):
                it, score = _best_match(d[req_field], items)
                _match_log(di, kind, d[req_field], it, score)
                if it and score >= threshold:
                    d_out[id_field] = it.id

        # ---- 景点 ----
        if d.get("attractions"):
            new_attrs = []
            for idx, attr_name in enumerate(d["attractions"], 1):
                if isinstance(attr_name, dict):
                    attr_name = attr_name.get("name") or attr_name.get("name_zh", "")
                a, score = _best_match(attr_name, attractions)
                _match_log(di, "景点", attr_name, a, score)
                if a and score >= threshold:
                    new_attrs.append({
                        "attraction_id": a.id,
                        "order_index": idx,
                        "stay_minutes": getattr(a, "recommended_minutes", None) or 60,
                    })
            d_out["attractions"] = new_attrs
        else:
            d_out["attractions"] = []

        # 清掉 AI 原始字段, 保留 quote API 接受的
        for k in ("hotel_name", "hotel_star_request", "room_type_request",
                  "vehicle_request", "guide_required",
                  "lunch_request", "dinner_request",
                  "spa_request", "water_activity_request", "afternoon_tea_request"):
            d_out.pop(k, None)
        out_days.append(d_out)

    resolved = dict(quote_draft)
    resolved["days"] = out_days
    return resolved, log


# ============================================================
#  缺失字段检测 — 用于"补漏"表单
# ============================================================
REQUIRED_TOP_FIELDS = [
    ("agency_name", "B 端旅行社名", "string", None),
    ("customer_name", "客户名称", "string", None),
    ("pax_adult", "成人数 (>=1)", "int", 2),
    ("start_date", "出发日期", "date", None),
    ("end_date", "结束日期", "date", None),
    ("destination_codes", "目的地", "list", ["DPS"]),
    ("customer_type", "客户类型", "select", "family"),
]

OPTIONAL_TOP_FIELDS = [
    ("pax_child", "儿童数", "int", 0),
    ("pax_senior", "老年人(55+)数", "int", 0),
    ("season", "季节", "select", "shoulder"),
]


def detect_missing_fields(quote_draft: dict[str, Any], match_log: list[dict]) -> list[dict]:
    """返回需要用户补漏的字段清单 (前端弹表单)."""
    out: list[dict] = []
    if not quote_draft:
        # 全空 → 全部必填
        for f, label, typ, default in REQUIRED_TOP_FIELDS:
            out.append({"field": f, "label": label, "type": typ, "default": default, "current": None, "required": True})
        return out

    # 顶层字段
    for f, label, typ, default in REQUIRED_TOP_FIELDS:
        v = quote_draft.get(f)
        if v in (None, "", [], 0) and not (typ == "int" and v == 0 and default == 0):
            out.append({"field": f, "label": label, "type": typ, "default": default, "current": v, "required": True})

    for f, label, typ, default in OPTIONAL_TOP_FIELDS:
        if quote_draft.get(f) is None:
            out.append({"field": f, "label": label, "type": typ, "default": default, "current": None, "required": False})

    # 每天的关键字段 — 至少要有 hotel_id (除非全自由) 和 vehicle_id (除非全自由)
    for i, d in enumerate(quote_draft.get("days", []) or []):
        di = d.get("day_index") or (i + 1)
        is_free = d.get("is_free") or (d.get("free_hours") or 0) >= 8
        if not d.get("hotel_id"):
            out.append({
                "field": f"days[{i}].hotel_id",
                "label": f"Day {di} 酒店 (AI 未匹配到)",
                "type": "hotel_select", "default": None, "current": None, "required": not is_free,
            })
        if not is_free and not d.get("vehicle_id"):
            out.append({
                "field": f"days[{i}].vehicle_id",
                "label": f"Day {di} 用车", "type": "vehicle_select",
                "default": None, "current": None, "required": True,
            })

    # 匹配日志里的"低分"匹配 — 提示用户确认
    for entry in match_log:
        if entry["matched_id"] and entry["score"] < 0.7:
            out.append({
                "field": f"verify_match_day{entry['day_index']}_{entry['kind']}",
                "label": f"Day {entry['day_index']} {entry['kind']} 匹配度仅 {int(entry['score'] * 100)}%: '{entry['query']}' → '{entry['matched_name']}', 是否正确?",
                "type": "verify", "default": True, "current": True, "required": False,
            })

    return out
