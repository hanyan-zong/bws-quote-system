"""管理类路由 — agencies / users / invitations / erp-sync (v0.4).

合并到一个文件方便维护; 所有端点都需要登录 + 大部分需要特定角色.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta
from ..utils.time_utils import now_utc
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from .auth import _hash_password, get_current_user

logger = logging.getLogger("bws.admin")
router = APIRouter(tags=["admin"])


# ============================================================
#  辅助 — 取当前用户(强制)
# ============================================================
def _require_user(request: Request, db: Session) -> models.User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(401, "未登录")
    return user


def _require_role(user: models.User, *allowed: str):
    if user.role not in allowed:
        raise HTTPException(403, f"需要角色 {'/'.join(allowed)}")


# ============================================================
#  Pydantic
# ============================================================
class AgencyIn(BaseModel):
    id: Optional[int] = None
    name: str
    short_name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    commission_rate: float = 0.0
    credit_limit_cny: float = 0.0
    notes: Optional[str] = None


class UserCreateIn(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str = "agent"  # agent / viewer / agency_owner / super_admin
    agency_id: Optional[int] = None


class UserUpdateIn(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None  # active|disabled


class ResetPasswordIn(BaseModel):
    new_password: str
    force_change: bool = True


class InvitationIn(BaseModel):
    agency_id: int
    role: str = "agent"  # agency_owner / agent / viewer
    expires_in_days: int = 7
    max_uses: int = 1
    note: Optional[str] = None


class ErpConfigIn(BaseModel):
    enabled: bool = False
    webhook_url: Optional[str] = None
    auth_token: Optional[str] = None  # 明文; 后端会简单加密
    retry_max: int = 5
    retry_backoff_seconds: int = 60


# ============================================================
#  Agency CRUD (super_admin 全权)
# ============================================================
@router.get("/agencies")
def list_agencies(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    q = db.query(models.Agency)
    if user.role != "super_admin":
        # owner 只看自己的
        if user.agency_id is None:
            return []
        q = q.filter(models.Agency.id == user.agency_id)
    rows = q.order_by(models.Agency.id).all()
    return [_agency_to_dict(a, db) for a in rows]


@router.post("/agencies")
def upsert_agency(payload: AgencyIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin")
    if payload.id:
        a = db.get(models.Agency, payload.id)
        if not a:
            raise HTTPException(404)
    else:
        if db.query(models.Agency).filter_by(name=payload.name).first():
            raise HTTPException(409, "旅行社名已存在")
        a = models.Agency(created_by_user_id=user.id)
        db.add(a)
    for f in ["name", "short_name", "contact_person", "phone", "email",
              "commission_rate", "credit_limit_cny", "notes"]:
        setattr(a, f, getattr(payload, f))
    db.commit()
    db.refresh(a)
    return _agency_to_dict(a, db)


@router.delete("/agencies/{aid}")
def suspend_agency(aid: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin")
    a = db.get(models.Agency, aid)
    if not a:
        raise HTTPException(404)
    a.status = "suspended"  # 软删
    db.commit()
    return {"ok": True}


def _agency_to_dict(a: models.Agency, db: Session) -> dict:
    user_count = db.query(models.User).filter_by(agency_id=a.id).count()
    return {
        "id": a.id,
        "name": a.name,
        "short_name": a.short_name,
        "contact_person": a.contact_person,
        "phone": a.phone,
        "email": a.email,
        "commission_rate": float(a.commission_rate or 0),
        "credit_limit_cny": float(a.credit_limit_cny or 0),
        "status": a.status,
        "notes": a.notes,
        "user_count": user_count,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


# ============================================================
#  User 管理
#    super_admin: 全部
#    agency_owner: 仅本社
# ============================================================
@router.get("/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin", "agency_owner")
    q = db.query(models.User)
    if user.role == "agency_owner":
        if user.agency_id is None:
            return []
        q = q.filter(models.User.agency_id == user.agency_id)
    rows = q.order_by(models.User.id).all()
    return [_user_to_dict(u, db) for u in rows]


@router.post("/users")
def create_user(payload: UserCreateIn, request: Request, db: Session = Depends(get_db)):
    """v0.8.4 — 直接建用户(不走邀请码).
       super_admin 可以建任何角色到任何 agency.
       agency_owner 只能建 agent/viewer 到本社.
    """
    user = _require_user(request, db)
    _require_role(user, "super_admin", "agency_owner")
    if db.query(models.User).filter_by(username=payload.username).first():
        raise HTTPException(409, "用户名已被占用")
    if len(payload.password) < 8:
        raise HTTPException(400, "密码至少 8 位")

    # agency_owner 限制
    if user.role == "agency_owner":
        if payload.role not in ("agent", "viewer"):
            raise HTTPException(403, "agency_owner 只能创建 agent 或 viewer 角色")
        if payload.agency_id and payload.agency_id != user.agency_id:
            raise HTTPException(403, "agency_owner 只能创建本社用户")
        agency_id = user.agency_id  # 强制本社
    else:
        agency_id = payload.agency_id

    u = models.User(
        username=payload.username,
        password_hash=_hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        email=payload.email,
        phone=payload.phone,
        role=payload.role,
        agency_id=agency_id,
        status="active",
        force_password_change=True,
        created_by_user_id=user.id,
    )
    db.add(u)
    db.flush()
    # 配额初始化
    from ..utils.feature_permissions import init_quotas_for_user
    init_quotas_for_user(db, u)
    db.commit()
    db.refresh(u)
    return _user_to_dict(u, db)


@router.put("/users/{uid}")
def update_user(uid: int, payload: UserUpdateIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    target = db.get(models.User, uid)
    if not target:
        raise HTTPException(404)

    # 权限: super_admin 全权; agency_owner 仅本社且不能改 super_admin
    if user.role == "agency_owner":
        if target.agency_id != user.agency_id:
            raise HTTPException(403, "不能修改其他旅行社的用户")
        if target.role == "super_admin":
            raise HTTPException(403)
        if payload.role and payload.role not in ("agent", "viewer"):
            raise HTTPException(403, "agency_owner 仅可设 agent/viewer 角色")
    elif user.role != "super_admin":
        raise HTTPException(403)

    for f in ["display_name", "email", "phone", "role", "status"]:
        v = getattr(payload, f)
        if v is not None:
            setattr(target, f, v)
    db.commit()
    db.refresh(target)
    return _user_to_dict(target, db)


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, payload: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    target = db.get(models.User, uid)
    if not target:
        raise HTTPException(404)
    if user.role == "agency_owner":
        if target.agency_id != user.agency_id or target.role == "super_admin":
            raise HTTPException(403)
    elif user.role != "super_admin":
        raise HTTPException(403)
    if len(payload.new_password) < 8:
        raise HTTPException(400, "密码至少 8 位")
    target.password_hash = _hash_password(payload.new_password)
    target.force_password_change = bool(payload.force_change)
    target.failed_login_count = 0
    target.locked_until = None
    db.commit()
    return {"ok": True}


def _user_to_dict(u: models.User, db: Session) -> dict:
    agency = db.get(models.Agency, u.agency_id) if u.agency_id else None
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "email": u.email,
        "phone": u.phone,
        "role": u.role,
        "agency_id": u.agency_id,
        "agency_name": agency.name if agency else None,
        "status": u.status,
        "force_password_change": u.force_password_change,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# ============================================================
#  Invitation
# ============================================================
@router.get("/invitations")
def list_invitations(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin", "agency_owner")
    q = db.query(models.Invitation)
    if user.role == "agency_owner":
        q = q.filter(models.Invitation.agency_id == user.agency_id)
    rows = q.order_by(models.Invitation.id.desc()).limit(200).all()
    return [_invitation_to_dict(i, db) for i in rows]


@router.post("/invitations")
def create_invitation(payload: InvitationIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin", "agency_owner")
    # 校验权限: agency_owner 仅可生成 agent/viewer 角色 + 本社
    if user.role == "agency_owner":
        if payload.agency_id != user.agency_id:
            raise HTTPException(403, "只能为本社生成邀请")
        if payload.role not in ("agent", "viewer"):
            raise HTTPException(403, "agency_owner 仅可生成 agent/viewer 邀请")
    elif user.role == "super_admin":
        if payload.role not in ("super_admin", "agency_owner", "agent", "viewer"):
            raise HTTPException(400, "无效角色")

    agency = db.get(models.Agency, payload.agency_id)
    if not agency:
        raise HTTPException(404, "旅行社不存在")

    code = "bws-" + secrets.token_urlsafe(16).replace("_", "").replace("-", "").upper()[:16]
    while db.query(models.Invitation).filter_by(code=code).first():
        code = "bws-" + secrets.token_urlsafe(16).replace("_", "").replace("-", "").upper()[:16]

    inv = models.Invitation(
        code=code,
        agency_id=payload.agency_id,
        role=payload.role,
        max_uses=payload.max_uses,
        used_count=0,
        expires_at=now_utc() + timedelta(days=payload.expires_in_days),
        note=payload.note,
        created_by_user_id=user.id,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return _invitation_to_dict(inv, db)


@router.delete("/invitations/{iid}")
def revoke_invitation(iid: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin", "agency_owner")
    inv = db.get(models.Invitation, iid)
    if not inv:
        raise HTTPException(404)
    if user.role == "agency_owner" and inv.agency_id != user.agency_id:
        raise HTTPException(403)
    inv.revoked_at = now_utc()
    db.commit()
    return {"ok": True}


def _invitation_to_dict(inv: models.Invitation, db: Session) -> dict:
    agency = db.get(models.Agency, inv.agency_id)
    is_active = (
        inv.revoked_at is None and inv.expires_at > now_utc()
        and inv.used_count < inv.max_uses
    )
    return {
        "id": inv.id,
        "code": inv.code,
        "agency_id": inv.agency_id,
        "agency_name": agency.name if agency else None,
        "role": inv.role,
        "max_uses": inv.max_uses,
        "used_count": inv.used_count,
        "uses_remaining": inv.max_uses - inv.used_count,
        "expires_at": inv.expires_at.isoformat(),
        "note": inv.note,
        "revoked_at": inv.revoked_at.isoformat() if inv.revoked_at else None,
        "is_active": is_active,
        "register_url_hint": f"/register?code={inv.code}",
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


# ============================================================
#  ERP 同步 (v0.4 仅展示队列, 不真正推送)
# ============================================================
@router.get("/erp-sync/events")
def list_erp_events(
    request: Request,
    status: Optional[str] = None,
    event_type: Optional[str] = None,
    page: int = 1, page_size: int = 50,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_role(user, "super_admin")

    q = db.query(models.ErpSyncEvent)
    if status:
        q = q.filter(models.ErpSyncEvent.status == status)
    if event_type:
        q = q.filter(models.ErpSyncEvent.event_type == event_type)
    total = q.count()

    summary = {"pending": 0, "synced": 0, "failed": 0, "skipped": 0}
    for s, c in db.query(models.ErpSyncEvent.status, models.ErpSyncEvent.id).all():
        # 简化: 重新 group by
        pass
    for s_name in ("pending", "synced", "failed", "skipped"):
        summary[s_name] = db.query(models.ErpSyncEvent).filter_by(status=s_name).count()

    rows = q.order_by(models.ErpSyncEvent.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "summary": summary,
        "items": [_event_to_dict(e) for e in rows],
    }


@router.post("/erp-sync/events/{eid}/mark-synced")
def mark_synced(eid: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin")
    ev = db.get(models.ErpSyncEvent, eid)
    if not ev:
        raise HTTPException(404)
    ev.status = "synced"
    ev.synced_at = now_utc()
    ev.synced_by_user_id = user.id
    db.commit()
    return {"ok": True}


@router.post("/erp-sync/events/{eid}/skip")
def skip_event(eid: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin")
    ev = db.get(models.ErpSyncEvent, eid)
    if not ev:
        raise HTTPException(404)
    ev.status = "skipped"
    ev.synced_at = now_utc()
    ev.synced_by_user_id = user.id
    db.commit()
    return {"ok": True}


@router.post("/erp-sync/events/{eid}/retry")
def retry_event(eid: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin")
    ev = db.get(models.ErpSyncEvent, eid)
    if not ev:
        raise HTTPException(404)
    ev.status = "pending"
    ev.next_retry_at = None
    db.commit()
    return {"ok": True, "note": "重置为 pending; v0.5 worker 接入后将被自动消费"}


@router.get("/erp-sync/config")
def get_erp_config(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin")
    cfg = db.query(models.ErpConfig).first()
    if not cfg:
        return {"enabled": False, "webhook_url": None, "retry_max": 5, "retry_backoff_seconds": 60}
    return {
        "enabled": cfg.enabled,
        "webhook_url": cfg.webhook_url,
        "auth_token_set": bool(cfg.auth_token_encrypted),
        "retry_max": cfg.retry_max,
        "retry_backoff_seconds": cfg.retry_backoff_seconds,
        "last_health_check_at": cfg.last_health_check_at.isoformat() if cfg.last_health_check_at else None,
        "last_health_check_ok": cfg.last_health_check_ok,
    }


@router.put("/erp-sync/config")
def set_erp_config(payload: ErpConfigIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_role(user, "super_admin")
    cfg = db.query(models.ErpConfig).first()
    if not cfg:
        cfg = models.ErpConfig()
        db.add(cfg)
    cfg.enabled = payload.enabled
    cfg.webhook_url = payload.webhook_url
    if payload.auth_token:
        # 简单遮掩(v0.4); v0.5 上 Fernet
        cfg.auth_token_encrypted = "obfuscated:" + secrets.token_hex(8) + ":" + payload.auth_token[:4] + "***"
    cfg.retry_max = payload.retry_max
    cfg.retry_backoff_seconds = payload.retry_backoff_seconds
    db.commit()
    return {"ok": True}


def _event_to_dict(e: models.ErpSyncEvent) -> dict:
    try:
        payload = json.loads(e.payload) if e.payload else None
    except Exception:
        payload = {"_raw": e.payload}
    return {
        "id": e.id,
        "event_type": e.event_type,
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "payload": payload,
        "status": e.status,
        "retry_count": e.retry_count,
        "max_retries": e.max_retries,
        "next_retry_at": e.next_retry_at.isoformat() if e.next_retry_at else None,
        "last_error": e.last_error,
        "last_attempt_at": e.last_attempt_at.isoformat() if e.last_attempt_at else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "synced_at": e.synced_at.isoformat() if e.synced_at else None,
        "synced_by_user_id": e.synced_by_user_id,
    }


# ============================================================
#  v0.7 — 配额管理 / 使用日志 (super_admin 全部 / agency_owner 限本社)
# ============================================================
class QuotaOverrideIn(BaseModel):
    user_id: int
    feature: str
    period: Optional[str] = None  # daily / monthly / total; 不填保持原值
    limit_count: int               # -1 = 无限; 0 = 禁用
    note: Optional[str] = None


@router.get("/admin/quotas")
def admin_list_quotas(
    request: Request, db: Session = Depends(get_db),
    user_id: Optional[int] = None, agency_id: Optional[int] = None,
):
    """列出配额. super_admin 全部; agency_owner 仅本社."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner", "ops_manager")

    q = db.query(models.UsageQuota).join(models.User, models.User.id == models.UsageQuota.user_id)
    if me.role == "agency_owner":
        q = q.filter(models.User.agency_id == me.agency_id)
    if user_id:
        q = q.filter(models.UsageQuota.user_id == user_id)
    if agency_id and me.role in ("super_admin", "ops_manager"):
        q = q.filter(models.User.agency_id == agency_id)

    rows = q.order_by(models.UsageQuota.user_id, models.UsageQuota.feature).limit(2000).all()
    from ..utils.feature_permissions import FEATURES
    return [
        {
            "id": r.id, "user_id": r.user_id, "feature": r.feature,
            "feature_label": FEATURES.get(r.feature, {}).get("label", r.feature),
            "period": r.period, "limit": r.limit_count, "used": r.used_count,
            "remaining": -1 if r.limit_count < 0 else max(0, r.limit_count - r.used_count),
            "reset_at": r.reset_at.isoformat() if r.reset_at else None,
            "overridden": r.overridden_by_admin,
            "note": r.note,
        }
        for r in rows
    ]


@router.post("/admin/quotas/override")
def admin_override_quota(payload: QuotaOverrideIn, request: Request, db: Session = Depends(get_db)):
    """覆盖单个用户某 feature 的配额. super_admin 全部; agency_owner 仅本社用户."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner")

    target_user = db.get(models.User, payload.user_id)
    if not target_user:
        raise HTTPException(404, "用户不存在")
    if me.role == "agency_owner" and target_user.agency_id != me.agency_id:
        raise HTTPException(403, "只能管理本社用户")

    q = (
        db.query(models.UsageQuota)
        .filter_by(user_id=payload.user_id, feature=payload.feature)
        .first()
    )
    if q is None:
        q = models.UsageQuota(
            user_id=payload.user_id, feature=payload.feature,
            period=payload.period or "monthly",
            limit_count=payload.limit_count, used_count=0,
        )
        db.add(q)
    else:
        if payload.period:
            q.period = payload.period
        q.limit_count = payload.limit_count
    q.overridden_by_admin = True
    q.note = payload.note
    db.commit()
    return {"ok": True, "quota_id": q.id, "limit": q.limit_count}


@router.post("/admin/quotas/{quota_id}/reset")
def admin_reset_quota_used(quota_id: int, request: Request, db: Session = Depends(get_db)):
    """手动重置某条配额的 used_count → 0."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner")
    q = db.get(models.UsageQuota, quota_id)
    if not q:
        raise HTTPException(404)
    target_user = db.get(models.User, q.user_id)
    if me.role == "agency_owner" and (not target_user or target_user.agency_id != me.agency_id):
        raise HTTPException(403)
    q.used_count = 0
    db.commit()
    return {"ok": True, "used": 0}


@router.get("/admin/usage-logs")
def admin_usage_logs(
    request: Request, db: Session = Depends(get_db),
    user_id: Optional[int] = None, feature: Optional[str] = None,
    success: Optional[bool] = None, days: int = 7, limit: int = 200,
):
    """使用日志 (审计). super_admin 全部; agency_owner 仅本社."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner", "ops_manager")
    cutoff = now_utc() - timedelta(days=days)
    q = db.query(models.UsageLog).filter(models.UsageLog.used_at >= cutoff)
    if me.role == "agency_owner":
        q = q.filter(models.UsageLog.agency_id == me.agency_id)
    if user_id:
        q = q.filter(models.UsageLog.user_id == user_id)
    if feature:
        q = q.filter(models.UsageLog.feature == feature)
    if success is not None:
        q = q.filter(models.UsageLog.success == success)
    rows = q.order_by(models.UsageLog.used_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "user_id": r.user_id, "agency_id": r.agency_id,
            "feature": r.feature, "success": r.success,
            "error_msg": r.error_msg,
            "meta_json": r.meta_json,
            "used_at": r.used_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/admin/role-info")
def admin_role_info():
    """返回所有角色 + 功能 + 默认配额配置 (前端做权限矩阵展示用)."""
    from ..utils.feature_permissions import (
        ROLE_LABELS, FEATURES, FEATURE_REQUIREMENTS, DEFAULT_QUOTAS,
    )
    return {
        "roles": [
            {"key": k, "label": v} for k, v in ROLE_LABELS.items()
        ],
        "features": [
            {"key": k, "label": v["label"], "category": v.get("category", "其他"),
             "allowed_roles": FEATURE_REQUIREMENTS.get(k, [])}
            for k, v in FEATURES.items()
        ],
        "default_quotas": {
            role: [
                {"feature": f, "period": p, "limit": l}
                for f, (p, l) in quotas.items()
            ]
            for role, quotas in DEFAULT_QUOTAS.items()
        },
    }


# ============================================================
#  v0.8 — 待审核用户(自助注册申请)管理
# ============================================================
class ReviewIn(BaseModel):
    approve: bool                       # True 批准 / False 拒绝
    role: Optional[str] = None          # 批准时可调整角色 (默认沿用 requested role)
    agency_id: Optional[int] = None     # 批准时若指定则覆盖, 或自动建新 agency
    review_note: Optional[str] = None


@router.get("/admin/pending-users")
def admin_list_pending_users(request: Request, db: Session = Depends(get_db)):
    """列出待审核的注册申请. super_admin 看全部; agency_owner 看本社相关."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "ops_manager", "agency_owner")

    q = db.query(models.User).filter_by(status="pending_review")
    if me.role == "agency_owner":
        q = q.filter(models.User.agency_id == me.agency_id)

    rows = q.order_by(models.User.created_at.desc()).limit(500).all()
    return [
        {
            "id": u.id, "username": u.username, "display_name": u.display_name,
            "email": u.email, "phone": u.phone,
            "requested_role": u.role,
            "agency_id": u.agency_id,
            "agency_name": (db.get(models.Agency, u.agency_id).name if u.agency_id else None),
            "requested_agency_name": u.requested_agency_name,
            "application_note": u.application_note,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]


@router.post("/admin/pending-users/{user_id}/review")
def admin_review_pending_user(
    user_id: int, payload: ReviewIn, request: Request, db: Session = Depends(get_db),
):
    """批准 / 拒绝待审核申请."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner")

    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.status != "pending_review":
        raise HTTPException(400, f"该用户当前状态={target.status}, 不在待审核中")

    # 权限边界: agency_owner 只能审本社相关 (含申请加入本社的)
    if me.role == "agency_owner":
        same_agency = (target.agency_id and target.agency_id == me.agency_id)
        # 申请新建旅行社的不能让 owner 批 (那是 super 的事)
        if not same_agency:
            raise HTTPException(403, "agency_owner 只能审本社申请")
        # owner 不能批 super_admin/ops_manager 角色
        if payload.approve and (payload.role or target.role) in ("super_admin", "ops_manager"):
            raise HTTPException(403, "agency_owner 不能批准 super_admin/ops_manager")

    target.reviewed_by_user_id = me.id
    target.reviewed_at = now_utc()
    target.review_note = payload.review_note

    if not payload.approve:
        target.status = "rejected"
        db.commit()
        return {"ok": True, "user_id": user_id, "status": "rejected"}

    # 批准 — 可选: 改角色, 改 agency, 或自动建新 agency
    if payload.role:
        target.role = payload.role
    if payload.agency_id:
        agency = db.get(models.Agency, payload.agency_id)
        if not agency:
            raise HTTPException(404, "指定的旅行社不存在")
        target.agency_id = payload.agency_id
    elif target.requested_agency_name and not target.agency_id:
        # 自动建一家新旅行社
        new_agency = models.Agency(
            name=target.requested_agency_name,
            short_name=target.requested_agency_name[:8],
            status="active",
            created_by_user_id=me.id,
            notes=f"由用户 {target.username} 自助注册时申请新建",
        )
        db.add(new_agency)
        db.flush()
        target.agency_id = new_agency.id
        target.requested_agency_name = None

    target.status = "active"
    db.flush()

    # 配额初始化
    from ..utils.feature_permissions import init_quotas_for_user
    init_quotas_for_user(db, target)
    db.commit()
    return {
        "ok": True, "user_id": user_id, "status": "active",
        "role": target.role, "agency_id": target.agency_id,
    }


# ============================================================
#  v0.8 — 使用日志聚合统计
# ============================================================
@router.get("/admin/usage-stats")
def admin_usage_stats(
    request: Request, db: Session = Depends(get_db), days: int = 7,
):
    """近 N 天使用聚合: 按 feature / 按 user / 总成功率."""
    from sqlalchemy import func
    me = _require_user(request, db)
    _require_role(me, "super_admin", "ops_manager", "agency_owner")
    cutoff = now_utc() - timedelta(days=days)

    base = db.query(models.UsageLog).filter(models.UsageLog.used_at >= cutoff)
    if me.role == "agency_owner":
        base = base.filter(models.UsageLog.agency_id == me.agency_id)

    # 1) 按 feature 统计
    by_feature = (
        base.with_entities(
            models.UsageLog.feature,
            func.count(models.UsageLog.id).label("total"),
            func.sum(models.UsageLog.success.cast(__import__("sqlalchemy").Integer)).label("success"),
        )
        .group_by(models.UsageLog.feature).all()
    )
    from ..utils.feature_permissions import FEATURES
    feat_stats = []
    for f, total, success in by_feature:
        s = int(success or 0)
        feat_stats.append({
            "feature": f,
            "label": FEATURES.get(f, {}).get("label", f),
            "total": total, "success": s, "failed": total - s,
            "success_rate": round(s / total, 3) if total else 0,
        })
    feat_stats.sort(key=lambda x: -x["total"])

    # 2) 按 user 统计 (top 20)
    by_user_q = base.with_entities(
        models.UsageLog.user_id,
        func.count(models.UsageLog.id).label("total"),
    ).group_by(models.UsageLog.user_id).order_by(func.count(models.UsageLog.id).desc()).limit(20).all()
    user_ids = [u[0] for u in by_user_q if u[0]]
    user_map = {
        u.id: {"username": u.username, "display_name": u.display_name, "role": u.role}
        for u in db.query(models.User).filter(models.User.id.in_(user_ids)).all()
    } if user_ids else {}
    user_stats = [
        {
            "user_id": uid,
            "username": user_map.get(uid, {}).get("username", "—"),
            "display_name": user_map.get(uid, {}).get("display_name"),
            "role": user_map.get(uid, {}).get("role"),
            "total": total,
        }
        for uid, total in by_user_q
    ]

    # 3) 总览
    total_calls = sum(s["total"] for s in feat_stats)
    total_success = sum(s["success"] for s in feat_stats)
    return {
        "window_days": days,
        "total_calls": total_calls,
        "total_success": total_success,
        "total_failed": total_calls - total_success,
        "success_rate": round(total_success / total_calls, 3) if total_calls else 0,
        "by_feature": feat_stats,
        "by_user": user_stats,
    }


# ============================================================
#  v0.8.3 - 用户解锁 / 重置密码 (super_admin / agency_owner)
# ============================================================
class ResetPasswordIn(BaseModel):
    new_password: str
    force_change: bool = True  # 强制对方下次登录改密


@router.post("/admin/users/{user_id}/unlock")
def admin_unlock_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """解锁某用户 (清除 locked_until + failed_login_count)."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner")
    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404)
    if me.role == "agency_owner" and target.agency_id != me.agency_id:
        raise HTTPException(403, "只能解锁本社用户")
    target.locked_until = None
    target.failed_login_count = 0
    db.commit()
    return {"ok": True, "username": target.username, "unlocked": True}


@router.post("/admin/users/{user_id}/reset-password")
def admin_reset_user_password(
    user_id: int, payload: ResetPasswordIn, request: Request, db: Session = Depends(get_db),
):
    """管理员强制重置某用户密码."""
    from .auth import _hash_password
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner")
    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404)
    if me.role == "agency_owner" and target.agency_id != me.agency_id:
        raise HTTPException(403, "只能重置本社用户密码")
    if me.role == "agency_owner" and target.role in ("super_admin", "ops_manager"):
        raise HTTPException(403, "agency_owner 不能重置 super_admin/ops_manager 密码")
    if len(payload.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    target.password_hash = _hash_password(payload.new_password)
    target.force_password_change = bool(payload.force_change)
    target.locked_until = None  # 顺手解锁
    target.failed_login_count = 0
    db.commit()
    return {"ok": True, "username": target.username, "password_reset": True, "force_change": payload.force_change}


@router.post("/admin/users/{user_id}/disable")
def admin_disable_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """停用账号."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner")
    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404)
    if target.id == me.id:
        raise HTTPException(400, "不能停用自己")
    if me.role == "agency_owner" and target.agency_id != me.agency_id:
        raise HTTPException(403)
    target.status = "disabled"
    db.commit()
    return {"ok": True, "status": "disabled"}


@router.post("/admin/users/{user_id}/activate")
def admin_activate_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """启用账号 (从 disabled 状态)."""
    me = _require_user(request, db)
    _require_role(me, "super_admin", "agency_owner")
    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404)
    if me.role == "agency_owner" and target.agency_id != me.agency_id:
        raise HTTPException(403)
    target.status = "active"
    target.locked_until = None
    target.failed_login_count = 0
    db.commit()
    return {"ok": True, "status": "active"}
