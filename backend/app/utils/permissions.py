"""权限与字段过滤辅助 (v0.4).

设计原则:
1. agent / viewer 看不到 IDR 成本、利润、赌额
2. agency_owner / super_admin 看完整数据
3. 字段过滤在 API 响应序列化层做(简单粗暴), 不在数据库层
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .. import models


# 角色等级 — 数字大权限大 (v0.7 加 ops_manager)
ROLE_LEVEL = {
    "viewer": 1,
    "agent": 2,
    "agency_owner": 3,
    "ops_manager": 50,
    "super_admin": 99,
}

# 各资源类型对 agent/viewer 隐藏的字段
RESOURCE_HIDDEN_FIELDS = {
    "hotel_room":      ["cost_idr_low", "cost_idr_high"],
    "attraction":      ["ticket_idr_adult", "ticket_idr_child"],
    "restaurant":      ["cost_idr_per_person"],
    "vehicle":         ["cost_idr_per_day"],
    "guide":           ["cost_idr_per_day"],
    "spa":             ["cost_idr_per_person"],
    "water_activity":  ["cost_idr_per_person"],
    "afternoon_tea":   ["cost_idr_per_person"],
    "optional_tour":   ["cost_idr", "margin_cny"],
}

# Quote 对 agent/viewer 隐藏的敏感字段
QUOTE_HIDDEN_FIELDS = [
    "cost_idr_total",
    "cost_cny_total",
    "profit_cny_per_pax",
    "gamble_cny_per_pax",
]


def can_see_costs(user: models.User | None) -> bool:
    """是否能看 IDR 成本与利润. v0.7: ops_manager 也可见 (帮做单需要)."""
    if user is None:
        return True  # 关闭口令门时不限制
    return user.role in ("super_admin", "ops_manager", "agency_owner")


def filter_quote_dict(quote_dict: dict, user: models.User | None) -> dict:
    """裁剪 Quote 输出."""
    if can_see_costs(user):
        return quote_dict
    return {k: v for k, v in quote_dict.items() if k not in QUOTE_HIDDEN_FIELDS}


def filter_resource_list(rows: list[dict], rtype: str, user: models.User | None) -> list[dict]:
    """裁剪资源列表输出 (hotel/attraction/...)."""
    if can_see_costs(user):
        return rows
    hidden = RESOURCE_HIDDEN_FIELDS.get(rtype, [])
    if not hidden:
        return rows
    return [{k: v for k, v in row.items() if k not in hidden} for row in rows]


def filter_hotel_with_rooms(hotels: list[dict], user: models.User | None) -> list[dict]:
    """酒店 list 嵌套 rooms — 双层过滤."""
    if can_see_costs(user):
        return hotels
    hidden = RESOURCE_HIDDEN_FIELDS["hotel_room"]
    out = []
    for h in hotels:
        h2 = dict(h)
        if h2.get("rooms"):
            h2["rooms"] = [{k: v for k, v in r.items() if k not in hidden} for r in h2["rooms"]]
        out.append(h2)
    return out


# ============================================================
#  FastAPI 依赖 — 提取当前用户(可选/强制)
# ============================================================
def current_user_optional(request: Request, db: Session) -> models.User | None:
    """从 cookie 取用户; 无效返回 None. middleware 已挡 401, 此处给出便利."""
    from ..routers.auth import get_current_user
    return get_current_user(request, db)


def require_role(*allowed_roles: str):
    """装饰器工厂 — 用作 FastAPI Depends 强制角色检查."""
    from fastapi import Depends
    from ..database import get_db

    def _dep(request: Request, db: Session = Depends(get_db)) -> models.User:
        from ..routers.auth import get_current_user
        user = get_current_user(request, db)
        if user is None:
            raise HTTPException(401, "未登录")
        if user.role not in allowed_roles:
            raise HTTPException(403, f"需要角色 {'/'.join(allowed_roles)}, 当前 {user.role}")
        return user
    return _dep


def filter_quotes_by_scope(query, user: models.User | None):
    """按角色裁剪 Quote 查询范围.

    super_admin / ops_manager: 全量 (跨 agency)
    agency_owner: 本社全部
    agent / viewer: 仅自己创建
    """
    if user is None or user.role in ("super_admin", "ops_manager"):
        return query
    if user.role == "agency_owner":
        if user.agency_id is None:
            return query.filter(False)  # 不该出现, 防御性
        return query.filter(models.Quote.agency_id == user.agency_id)
    # agent / viewer
    return query.filter(models.Quote.created_by_user_id == user.id)
