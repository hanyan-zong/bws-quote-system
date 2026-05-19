"""v0.7 — 功能级权限 + 配额系统.

核心概念:
1. **角色 (role)** — 5 个等级: super_admin > ops_manager > agency_owner > agent > viewer
2. **功能 (feature)** — 系统的"动作"枚举: create_quote / ai_parse_itinerary / export_quote_pdf / ...
3. **角色 → 可用功能** (硬约束, FEATURE_REQUIREMENTS)
4. **角色 → 默认配额** (DEFAULT_QUOTAS) - 每用户首次登录时初始化
5. **可单用户覆盖配额** (UsageQuota.overridden_by_admin=True)

调用方式:
    user = get_current_user(request, db)
    require_feature(user, "ai_parse_itinerary")  # 抛 403 如果无权
    consume_quota(db, user, "ai_parse_itinerary", meta={"file": "x.pdf"})  # 扣减/写日志
    # 业务逻辑...
"""
from __future__ import annotations

import calendar
import json
import logging
from datetime import datetime, timedelta
from .time_utils import now_utc
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models

logger = logging.getLogger("bws.permissions")

# ============================================================
#  常量
# ============================================================
ROLE_LEVEL = {
    "viewer": 1,
    "agent": 2,
    "agency_owner": 3,
    "ops_manager": 50,
    "super_admin": 99,
}

ROLE_LABELS = {
    "super_admin": "公司超管",
    "ops_manager": "公司 OP 操作员",
    "agency_owner": "B 端旅行社老板",
    "agent": "B 端业务员",
    "viewer": "基础只读用户",
}

# 功能注册表: feature_key → {label, category, description}
FEATURES: dict[str, dict[str, str]] = {
    # 报价核心
    "create_quote":           {"label": "创建/编辑报价", "category": "报价"},
    "delete_quote":           {"label": "删除报价",     "category": "报价"},
    "calculate_quote":        {"label": "计算报价",     "category": "报价"},
    "see_quote_costs":        {"label": "查看成本/利润/赌额", "category": "报价"},
    # AI 功能 (主要受配额限制)
    "ai_parse_resource":      {"label": "AI 资源采集", "category": "AI"},
    "ai_parse_itinerary":     {"label": "AI 一键上传客户行程报价", "category": "AI"},
    "ai_review_quote":        {"label": "AI 行程评估", "category": "AI"},
    # 导出
    "export_quote_xlsx":      {"label": "报价导出 Excel", "category": "导出"},
    "export_quote_pdf":       {"label": "报价导出 PDF",  "category": "导出"},
    "export_quote_docx":      {"label": "报价导出 Word", "category": "导出"},
    # 反馈/统计
    "feedback_quote":         {"label": "团结束反馈回写", "category": "反馈"},
    "view_strategy_stats":    {"label": "查看策略胜率统计", "category": "反馈"},
    # 资源库
    "manage_resources":       {"label": "管理资源库 (酒店/景点/...)", "category": "管理"},
    "manage_templates":       {"label": "管理一日游模板", "category": "管理"},
    # 系统设置
    "manage_strategies":      {"label": "管理赌自费策略", "category": "管理"},
    "manage_area_rules":      {"label": "管理区域/景点规则", "category": "管理"},
    "manage_settings":        {"label": "全局设置 (汇率/时间预算)", "category": "管理"},
    # 账号
    "invite_users":           {"label": "邀请用户", "category": "账号"},
    "manage_users":           {"label": "管理用户 (改角色/重置密码)", "category": "账号"},
    "manage_agencies":        {"label": "管理旅行社 (创建/停用)", "category": "账号"},
    "view_usage_logs":        {"label": "查看全社使用日志", "category": "账号"},
    "override_quotas":        {"label": "覆盖单用户配额", "category": "账号"},
    # ERP
    "manage_erp_config":      {"label": "ERP 同步配置", "category": "管理"},
}

# 角色 → 可用功能 (allowlist)
FEATURE_REQUIREMENTS: dict[str, list[str]] = {
    # super_admin 拥有全部
    "create_quote":          ["super_admin", "ops_manager", "agency_owner", "agent"],
    "delete_quote":          ["super_admin", "ops_manager", "agency_owner"],  # agent 不能删自己已发出去的, 防误操作
    "calculate_quote":       ["super_admin", "ops_manager", "agency_owner", "agent"],
    "see_quote_costs":       ["super_admin", "ops_manager", "agency_owner"],
    "ai_parse_resource":     ["super_admin", "ops_manager"],   # 仅公司侧能录资源
    "ai_parse_itinerary":    ["super_admin", "ops_manager", "agency_owner", "agent"],
    "ai_review_quote":       ["super_admin", "ops_manager", "agency_owner", "agent"],
    "export_quote_xlsx":     ["super_admin", "ops_manager", "agency_owner", "agent"],
    "export_quote_pdf":      ["super_admin", "ops_manager", "agency_owner", "agent"],
    "export_quote_docx":     ["super_admin", "ops_manager", "agency_owner", "agent"],
    "feedback_quote":        ["super_admin", "ops_manager", "agency_owner", "agent"],
    "view_strategy_stats":   ["super_admin", "ops_manager", "agency_owner"],
    "manage_resources":      ["super_admin", "ops_manager"],
    "manage_templates":      ["super_admin", "ops_manager"],
    "manage_strategies":     ["super_admin"],
    "manage_area_rules":     ["super_admin"],
    "manage_settings":       ["super_admin"],
    "invite_users":          ["super_admin", "agency_owner"],  # owner 邀本社; super 邀任何
    "manage_users":          ["super_admin", "agency_owner"],
    "manage_agencies":       ["super_admin"],
    "view_usage_logs":       ["super_admin", "agency_owner"],  # owner 看本社; super 看全部
    "override_quotas":       ["super_admin"],
    "manage_erp_config":     ["super_admin"],
}

# 默认配额 (角色 → 功能 → (period, limit))
# limit = -1 无限; 0 禁用; >0 周期内限额
# period = "daily" / "monthly" / "total" (total 不重置)
DEFAULT_QUOTAS: dict[str, dict[str, tuple[str, int]]] = {
    "super_admin": {
        # 全部无限
        "ai_parse_itinerary":  ("monthly", -1),
        "ai_parse_resource":   ("monthly", -1),
        "ai_review_quote":     ("monthly", -1),
        "export_quote_xlsx":   ("monthly", -1),
        "export_quote_pdf":    ("monthly", -1),
        "export_quote_docx":   ("monthly", -1),
        "create_quote":        ("monthly", -1),
    },
    "ops_manager": {
        "ai_parse_itinerary":  ("monthly", 1000),
        "ai_parse_resource":   ("monthly", 500),
        "ai_review_quote":     ("monthly", 1000),
        "export_quote_xlsx":   ("monthly", -1),
        "export_quote_pdf":    ("monthly", -1),
        "export_quote_docx":   ("monthly", -1),
        "create_quote":        ("monthly", -1),
    },
    "agency_owner": {
        "ai_parse_itinerary":  ("monthly", 200),
        "ai_review_quote":     ("monthly", 200),
        "export_quote_xlsx":   ("monthly", 500),
        "export_quote_pdf":    ("monthly", 500),
        "export_quote_docx":   ("monthly", 500),
        "create_quote":        ("monthly", -1),
    },
    "agent": {
        "ai_parse_itinerary":  ("monthly", 50),
        "ai_review_quote":     ("monthly", 50),
        "export_quote_xlsx":   ("monthly", 100),
        "export_quote_pdf":    ("monthly", 100),
        "export_quote_docx":   ("monthly", 100),
        "create_quote":        ("monthly", 200),
    },
    "viewer": {
        "ai_parse_itinerary":  ("monthly", 0),
        "ai_review_quote":     ("monthly", 0),
        "export_quote_xlsx":   ("monthly", 5),   # 一点点导出权
        "export_quote_pdf":    ("monthly", 5),
        "export_quote_docx":   ("monthly", 5),
        "create_quote":        ("monthly", 0),
    },
}

# 哪些功能受配额管控 (其余功能只看 FEATURE_REQUIREMENTS, 不计配额)
QUOTA_TRACKED_FEATURES = set()
for role_quotas in DEFAULT_QUOTAS.values():
    QUOTA_TRACKED_FEATURES.update(role_quotas.keys())


# ============================================================
#  工具函数
# ============================================================
def can_use_feature(user: models.User | None, feature: str) -> bool:
    """检查用户角色是否在 feature 的 allowlist 内. 不消耗配额."""
    if user is None:
        # 关闭口令门 = 不限角色 (用于 dev / 单租户场景)
        return True
    allowed = FEATURE_REQUIREMENTS.get(feature)
    if allowed is None:
        # 未注册的 feature 默认开放, 写日志提醒
        logger.warning("未注册的 feature: %s", feature)
        return True
    return user.role in allowed


def require_feature(user: models.User | None, feature: str) -> None:
    """权限 gate: 不在 allowlist 抛 403."""
    if not can_use_feature(user, feature):
        role = user.role if user else "guest"
        label = FEATURES.get(feature, {}).get("label", feature)
        raise HTTPException(403, f"当前角色 [{ROLE_LABELS.get(role, role)}] 无权使用 [{label}]")


def _next_reset(now: datetime, period: str) -> datetime | None:
    if period == "daily":
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "monthly":
        # 下个月 1 号 00:00
        if now.month == 12:
            return datetime(now.year + 1, 1, 1)
        return datetime(now.year, now.month + 1, 1)
    return None  # total 不重置


def init_quotas_for_user(db: Session, user: models.User) -> int:
    """为新用户初始化配额 (按角色). 已存在的不动. 返回创建数."""
    role_quotas = DEFAULT_QUOTAS.get(user.role, {})
    if not role_quotas:
        return 0
    existing = {
        q.feature for q in db.query(models.UsageQuota).filter_by(user_id=user.id).all()
    }
    now = now_utc()
    created = 0
    for feature, (period, limit) in role_quotas.items():
        if feature in existing:
            continue
        db.add(models.UsageQuota(
            user_id=user.id, feature=feature,
            period=period, limit_count=limit, used_count=0,
            reset_at=_next_reset(now, period),
            overridden_by_admin=False,
        ))
        created += 1
    if created:
        db.flush()
    return created


def _get_or_create_quota(db: Session, user: models.User, feature: str) -> models.UsageQuota:
    """拿到该用户该 feature 的配额行; 没有就按角色默认值新建."""
    q = (
        db.query(models.UsageQuota)
        .filter_by(user_id=user.id, feature=feature)
        .first()
    )
    if q is not None:
        return q
    # 按角色默认值建一条
    role_quotas = DEFAULT_QUOTAS.get(user.role, {})
    period, limit = role_quotas.get(feature, ("monthly", 0))
    q = models.UsageQuota(
        user_id=user.id, feature=feature, period=period,
        limit_count=limit, used_count=0,
        reset_at=_next_reset(now_utc(), period),
    )
    db.add(q)
    db.flush()
    return q


def _check_and_reset(q: models.UsageQuota) -> None:
    """如果到了 reset 时间, 把 used_count 归零."""
    if q.reset_at and now_utc() >= q.reset_at:
        q.used_count = 0
        q.reset_at = _next_reset(now_utc(), q.period)


def _log_usage(
    db: Session, user: models.User | None, feature: str,
    success: bool, error_msg: str | None = None, meta: dict | None = None,
) -> None:
    db.add(models.UsageLog(
        user_id=user.id if user else None,
        agency_id=user.agency_id if user else None,
        feature=feature,
        success=success,
        error_msg=error_msg,
        meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
    ))


def consume_quota(
    db: Session, user: models.User | None, feature: str,
    meta: dict | None = None, raise_on_exceed: bool = True,
) -> tuple[bool, int]:
    """检查 + 扣减配额. 返回 (success, remaining).

    - user=None 时 (关闭口令门): 不计配额, 直接 (True, -1)
    - 配额超限: 写失败日志, 抛 429 (Too Many Requests)
    - 成功: used_count += 1, 写成功日志, 返回 remaining (剩余次数; -1 = 无限)
    """
    if user is None:
        return True, -1

    require_feature(user, feature)

    # 不在配额表的功能 → 不计数, 直接通过
    if feature not in QUOTA_TRACKED_FEATURES:
        _log_usage(db, user, feature, True, meta=meta)
        return True, -1

    q = _get_or_create_quota(db, user, feature)
    _check_and_reset(q)

    if q.limit_count == 0:
        _log_usage(db, user, feature, False, error_msg="该功能配额=0 (角色不开放)", meta=meta)
        if raise_on_exceed:
            label = FEATURES.get(feature, {}).get("label", feature)
            raise HTTPException(403, f"[{label}] 当前角色不开放使用")
        return False, 0

    if q.limit_count > 0 and q.used_count >= q.limit_count:
        _log_usage(db, user, feature, False, error_msg="配额耗尽", meta=meta)
        if raise_on_exceed:
            label = FEATURES.get(feature, {}).get("label", feature)
            reset_str = q.reset_at.strftime("%Y-%m-%d %H:%M") if q.reset_at else "永不"
            raise HTTPException(
                429,
                f"[{label}] 本{q.period[:1]}配额已用完 ({q.used_count}/{q.limit_count}). 下次重置: {reset_str}",
            )
        return False, 0

    q.used_count += 1
    _log_usage(db, user, feature, True, meta=meta)
    # 必须 commit — 否则后续业务逻辑出错时配额扣减会回滚
    # (这是审计准确性的硬要求: "调用过 = 必扣")
    db.commit()
    db.refresh(q)
    remaining = -1 if q.limit_count < 0 else (q.limit_count - q.used_count)
    return True, remaining


def get_user_quotas(db: Session, user: models.User) -> list[dict[str, Any]]:
    """返回当前用户全部配额状态 — 前端"我的配额"卡用."""
    rows = db.query(models.UsageQuota).filter_by(user_id=user.id).all()
    out = []
    for q in rows:
        _check_and_reset(q)
        info = FEATURES.get(q.feature, {"label": q.feature, "category": "其他"})
        out.append({
            "feature": q.feature,
            "label": info["label"],
            "category": info.get("category", "其他"),
            "period": q.period,
            "limit": q.limit_count,
            "used": q.used_count,
            "remaining": -1 if q.limit_count < 0 else max(0, q.limit_count - q.used_count),
            "reset_at": q.reset_at.isoformat() if q.reset_at else None,
            "overridden": q.overridden_by_admin,
        })
    db.flush()
    return out


def get_user_features(user: models.User | None) -> list[dict[str, Any]]:
    """返回当前用户**有权使用**的功能列表 — 前端按这个隐藏按钮."""
    out = []
    for fkey, info in FEATURES.items():
        if can_use_feature(user, fkey):
            out.append({
                "feature": fkey,
                "label": info["label"],
                "category": info.get("category", "其他"),
                "tracked_by_quota": fkey in QUOTA_TRACKED_FEATURES,
            })
    return out
