"""认证模块 v0.4 — 多用户 + bcrypt + 邀请注册 + 会话 cookie 带 user_id."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta
from ..utils.time_utils import now_utc
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("bws.auth")

# ============================================================
#  Cookie 签名 (HMAC-SHA256, 含 user_id + 过期时间)
#  格式: "{user_id}.{expiry_ts}.{hex_sig}"
# ============================================================
def _sign(payload: str) -> str:
    return hmac.new(settings.auth_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_cookie_value(user_id: int) -> str:
    expiry = int(time.time()) + settings.auth_session_days * 86400
    payload = f"{user_id}.{expiry}"
    return f"{payload}.{_sign(payload)}"


def parse_cookie_value(value: str) -> tuple[int, int] | None:
    """返回 (user_id, expiry) 或 None."""
    if not value or value.count(".") != 2:
        return None
    try:
        uid_str, exp_str, sig = value.split(".")
        user_id = int(uid_str)
        expiry = int(exp_str)
    except (ValueError, AttributeError):
        return None
    if expiry < int(time.time()):
        return None
    expected = _sign(f"{user_id}.{expiry}")
    if not hmac.compare_digest(expected, sig):
        return None
    return user_id, expiry


# ============================================================
#  会话辅助 — v0.10 起 cookie (web) 与 Bearer access token (APP) 双通道
#  access token 与 cookie 同构 "{user_id}.{expiry}.{sig}", 复用同一套签名/解析
# ============================================================
def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return None


def get_current_user(request: Request, db: Session) -> Optional["models.User"]:
    """从 cookie (web) 或 Bearer access token (APP) 解出当前用户; 无效返回 None."""
    credential = request.cookies.get(settings.auth_cookie_name) or _bearer_token(request)
    if not credential:
        return None
    parsed = parse_cookie_value(credential)
    if not parsed:
        return None
    user_id, _ = parsed
    user = db.get(models.User, user_id)
    if not user or user.status != "active":
        return None
    return user


def is_authenticated(request: Request) -> bool:
    """auth_gate 入口 — cookie 有效放行 (web 不变), 否则查 Bearer (APP)."""
    if not settings.auth_required:
        # 兼容: 完全关闭口令门 (BWS_AUTH_USERNAME 留空 + 无 users 表)
        return True
    credential = request.cookies.get(settings.auth_cookie_name) or _bearer_token(request)
    if not credential:
        return False
    return parse_cookie_value(credential) is not None


# ============================================================
#  bcrypt 哈希 (无 bcrypt 库时降级 sha256+salt)
# ============================================================
def _hash_password(plain: str) -> str:
    try:
        import bcrypt  # type: ignore
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    except ImportError:
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"{salt}|{plain}".encode("utf-8")).hexdigest()
        return f"sha256${salt}${digest}"


def _verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("sha256$"):
        try:
            _, salt, expected = stored.split("$", 2)
        except ValueError:
            return False
        digest = hashlib.sha256(f"{salt}|{plain}".encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, digest)
    try:
        import bcrypt  # type: ignore
        return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
    except Exception:
        return False


# ============================================================
#  Pydantic
# ============================================================
class LoginIn(BaseModel):
    username: str
    password: str


class RegisterByInvitationIn(BaseModel):
    code: str
    username: str
    password: str
    display_name: str | None = None
    phone: str | None = None
    email: str | None = None


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


# v0.10 APP 端双 token
class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str | None = None


# v0.8.3 主密钥自助解锁
class MasterUnlockIn(BaseModel):
    master_password: str  # = .env BWS_AUTH_PASSWORD
    target_username: str | None = None  # 不填默认 admin
    reset_password_to: str | None = None  # 可选: 同时重置密码 (默认不改)


# v0.8 自助注册申请
class RegisterPublicIn(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    requested_role: str = "agent"  # 申请的角色 — 默认 agent; 不允许直接申请 super_admin/ops_manager
    agency_id: int | None = None   # 想加入的旅行社; null = 申请新建
    requested_agency_name: str | None = None  # 申请新建时的旅行社名
    application_note: str | None = None       # 申请理由


# ============================================================
#  /status — 前端启动检查
# ============================================================
@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return {
        "auth_required": settings.auth_required,
        "authenticated": user is not None,
        "user": _user_to_dict(user, db) if user else None,
        "version": "v0.4",
    }


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(401, "未登录")
    return _user_to_dict(user, db)


# ============================================================
#  /login — 用 username + password 登录
#  兼容: users 表为空时, 仍允许 .env 老账号登录(自动创建 super_admin)
# ============================================================
def _authenticate(body: LoginIn, request: Request, db: Session) -> models.User:
    """username+password → User; 失败抛 HTTPException.

    状态检查 / 5 次失败锁 15min / .env bootstrap 都在这 — /login 与 /auth/token 共用,
    保证 web 与 APP 的锁定策略永远一致.
    """
    # v0.4: 优先查 users 表
    user: models.User | None = db.query(models.User).filter_by(username=body.username).first()

    # 兼容: users 表无此用户 + .env 老配置匹配 → 自动 bootstrap 一个 super_admin
    if user is None and settings.auth_username and settings.auth_password:
        if (hmac.compare_digest(body.username.encode(), settings.auth_username.encode())
                and hmac.compare_digest(body.password.encode(), settings.auth_password.encode())):
            user = _bootstrap_admin_from_env(db)

    if user is None:
        raise HTTPException(401, "账号或密码错误")
    # v0.8 友好状态提示
    if user.status == "pending_review":
        raise HTTPException(403, "您的注册申请正在审核中,请等待管理员批准")
    if user.status == "rejected":
        note = user.review_note or "请联系管理员"
        raise HTTPException(403, f"您的注册申请已被拒绝: {note}")
    if user.status == "disabled":
        raise HTTPException(403, "账号已被停用,请联系管理员")
    if user.status != "active":
        raise HTTPException(401, "账号或密码错误")

    # 锁定检查
    if user.locked_until and user.locked_until > now_utc():
        secs = int((user.locked_until - now_utc()).total_seconds())
        raise HTTPException(403, f"账号已锁定 {secs} 秒后再试")

    if not _verify_password(body.password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= 5:
            user.locked_until = now_utc() + timedelta(minutes=15)
            user.failed_login_count = 0
        db.commit()
        raise HTTPException(401, "账号或密码错误")

    # 成功
    user.failed_login_count = 0
    user.last_login_at = now_utc()
    user.last_login_ip = request.client.host if request.client else None
    db.commit()
    return user


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _authenticate(body, request, db)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=make_cookie_value(user.id),
        max_age=settings.auth_session_days * 86400,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"ok": True, "user": _user_to_dict(user, db)}


@router.post("/logout")
def logout(response: Response, body: LogoutIn | None = None, db: Session = Depends(get_db)):
    """web: 删 cookie; APP: body 带 refresh_token 时一并撤销."""
    response.delete_cookie(settings.auth_cookie_name, path="/")
    if body and body.refresh_token:
        db.query(models.RefreshToken).filter_by(
            token_hash=_hash_refresh(body.refresh_token), revoked_at=None,
        ).update({"revoked_at": now_utc()})
        db.commit()
    return {"ok": True}


# ============================================================
#  v0.10 — APP 端双 token (短命 access + 旋转 refresh, 设计见
#  docs/APP版本设计方案_2026-06-11.md 3.1 节)
#  access: 与 cookie 同构的 HMAC 签名串, 30min, 无状态可验证;
#  refresh: 随机串, 库里只存 sha256, 旋转刷新 + 重放即全撤销.
# ============================================================
ACCESS_TOKEN_MINUTES = 30
REFRESH_TOKEN_DAYS = 14


def make_access_token(user_id: int) -> str:
    expiry = int(time.time()) + ACCESS_TOKEN_MINUTES * 60
    payload = f"{user_id}.{expiry}"
    return f"{payload}.{_sign(payload)}"


def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_pair_response(db: Session, user: models.User, request: Request) -> dict:
    """发一对新 token (access + refresh) 并落库 refresh hash."""
    refresh_plain = secrets.token_urlsafe(48)
    client_info = (request.headers.get("User-Agent") or "")[:200] or None
    db.add(models.RefreshToken(
        user_id=user.id,
        token_hash=_hash_refresh(refresh_plain),
        expires_at=now_utc() + timedelta(days=REFRESH_TOKEN_DAYS),
        client_info=client_info,
    ))
    db.commit()
    return {
        "token_type": "bearer",
        "access_token": make_access_token(user.id),
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
        "refresh_token": refresh_plain,
        "user": _user_to_dict(user, db),
    }


@router.post("/token")
def issue_token(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    """APP 端登录: username+password → access(30min) + refresh(14d)."""
    user = _authenticate(body, request, db)
    return _token_pair_response(db, user, request)


@router.post("/refresh")
def refresh_token(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    """旋转刷新: 旧 refresh 作废 + 发新对.

    已撤销 token 再次出现 = 重放迹象 (token 可能泄露), 撤销该用户全部 refresh 强制重登.
    """
    row = db.query(models.RefreshToken).filter_by(
        token_hash=_hash_refresh(body.refresh_token),
    ).first()
    if not row:
        raise HTTPException(401, "refresh token 无效")
    if row.revoked_at is not None:
        db.query(models.RefreshToken).filter_by(user_id=row.user_id, revoked_at=None).update(
            {"revoked_at": now_utc()},
        )
        db.commit()
        logger.warning("Revoked refresh token reused — all sessions revoked for user_id=%s", row.user_id)
        raise HTTPException(401, "refresh token 已失效, 请重新登录")
    if row.expires_at < now_utc():
        raise HTTPException(401, "refresh token 已过期, 请重新登录")
    user = db.get(models.User, row.user_id)
    if not user or user.status != "active":
        raise HTTPException(401, "账号不可用")

    row.revoked_at = now_utc()
    return _token_pair_response(db, user, request)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(401, "未登录")
    if not _verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "原密码错误")
    if len(body.new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    user.password_hash = _hash_password(body.new_password)
    user.force_password_change = False
    db.commit()
    return {"ok": True}


# ============================================================
#  /invitation — 邀请注册流程
# ============================================================
@router.get("/invitation/{code}")
def get_invitation_info(code: str, db: Session = Depends(get_db)):
    """公开端点 — 校验邀请码 + 返回 agency 信息(给注册页展示)."""
    inv = db.query(models.Invitation).filter_by(code=code).first()
    if not inv:
        raise HTTPException(404, "邀请码不存在")
    if inv.revoked_at:
        raise HTTPException(410, "邀请码已撤销")
    if inv.expires_at < now_utc():
        raise HTTPException(410, "邀请码已过期")
    if inv.used_count >= inv.max_uses:
        raise HTTPException(410, "邀请码已用完")

    agency = db.get(models.Agency, inv.agency_id)
    return {
        "code": inv.code,
        "role": inv.role,
        "agency": {"id": agency.id, "name": agency.name, "short_name": agency.short_name} if agency else None,
        "expires_at": inv.expires_at.isoformat(),
        "uses_remaining": inv.max_uses - inv.used_count,
    }


@router.post("/register")
def register_by_invitation(
    body: RegisterByInvitationIn, request: Request, response: Response, db: Session = Depends(get_db),
):
    """凭邀请码注册新用户."""
    inv = db.query(models.Invitation).filter_by(code=body.code).first()
    if not inv or inv.revoked_at or inv.expires_at < now_utc() or inv.used_count >= inv.max_uses:
        raise HTTPException(410, "邀请码无效或已过期")

    if len(body.username) < 4 or not body.username.replace("_", "").isalnum():
        raise HTTPException(400, "用户名至少 4 字符且只含字母/数字/下划线")
    if len(body.password) < 8:
        raise HTTPException(400, "密码至少 8 位")
    if db.query(models.User).filter_by(username=body.username).first():
        raise HTTPException(409, "用户名已被占用")

    user = models.User(
        username=body.username,
        password_hash=_hash_password(body.password),
        display_name=body.display_name or body.username,
        email=body.email,
        phone=body.phone,
        role=inv.role,
        agency_id=inv.agency_id,
        status="active",
        force_password_change=False,
        created_by_user_id=inv.created_by_user_id,
    )
    db.add(user)
    inv.used_count += 1
    db.flush()

    user.last_login_at = now_utc()
    user.last_login_ip = request.client.host if request.client else None
    db.flush()

    # v0.7: 注册成功后立即按角色初始化配额
    from ..utils.feature_permissions import init_quotas_for_user
    init_quotas_for_user(db, user)
    db.commit()

    response.set_cookie(
        key=settings.auth_cookie_name,
        value=make_cookie_value(user.id),
        max_age=settings.auth_session_days * 86400,
        httponly=True, samesite="lax", path="/",
    )
    return {"ok": True, "user": _user_to_dict(user, db)}


# ============================================================
#  v0.7 — 配额 + 权限自助查询端点
# ============================================================
@router.get("/quotas")
def my_quotas(request: Request, db: Session = Depends(get_db)):
    """当前用户的配额状态 (前端"我的配额"卡用)."""
    user = get_current_user(request, db)
    if not user:
        return {"quotas": [], "logged_in": False}
    from ..utils.feature_permissions import get_user_quotas, init_quotas_for_user
    # 老用户没配额行 → 自动初始化一次
    init_quotas_for_user(db, user)
    db.commit()
    return {
        "quotas": get_user_quotas(db, user),
        "logged_in": True,
        "user": {"id": user.id, "username": user.username, "role": user.role},
    }


@router.get("/permissions")
def my_permissions(request: Request, db: Session = Depends(get_db)):
    """当前用户可用功能列表 (前端按这个隐藏按钮/菜单)."""
    user = get_current_user(request, db)
    from ..utils.feature_permissions import get_user_features, ROLE_LABELS
    return {
        "role": user.role if user else "guest",
        "role_label": ROLE_LABELS.get(user.role, "—") if user else "未登录/口令门关闭",
        "features": get_user_features(user),
    }


# ============================================================
#  辅助
# ============================================================
def _user_to_dict(user: models.User, db: Session) -> dict:
    agency = db.get(models.Agency, user.agency_id) if user.agency_id else None
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "agency_id": user.agency_id,
        "agency_name": agency.name if agency else None,
        "force_password_change": user.force_password_change,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _bootstrap_admin_from_env(db: Session) -> models.User:
    """老 .env 单账号 → 自动建一个 super_admin user.

    一次性迁移:第一次用 .env 账号登录时触发, 之后就走 users 表.
    """
    # 同时建一家 default agency 兜底
    agency = db.query(models.Agency).filter_by(name="本社").first()
    if not agency:
        agency = models.Agency(name="本社", short_name="HOME", status="active")
        db.add(agency)
        db.flush()
    user = models.User(
        username=settings.auth_username,
        password_hash=_hash_password(settings.auth_password),
        display_name="超级管理员",
        role="super_admin",
        agency_id=agency.id,
        status="active",
    )
    db.add(user)
    db.flush()
    # v0.7: bootstrap super_admin 也初始化配额(无限)
    from ..utils.feature_permissions import init_quotas_for_user
    init_quotas_for_user(db, user)
    logger.info("Bootstrap super_admin '%s' from .env", user.username)
    return user


# ============================================================
#  v0.8.3 主密钥自助解锁 (无需登录, 用 .env 密钥校验)
# ============================================================
@router.post("/master-unlock")
def master_unlock(body: MasterUnlockIn, request: Request, db: Session = Depends(get_db)):
    """v0.8.3 — 用 .env BWS_AUTH_PASSWORD 作为主密钥, 解锁某账号 + 可选重置密码.

    应用场景:
    - admin 被锁了登不进来 → 输入 .env 密码 → 一键解锁
    - 忘了密码 → 输入 .env 密码 + 新密码 → 重置

    安全考虑:
    - 必须用 .env 里设的 BWS_AUTH_PASSWORD (= 部署者才知道)
    - 默认 .env 是 admin/admin123, 生产环境部署者应改密
    - 写入 logs 留痕
    """
    if not settings.auth_password or len(settings.auth_password) < 4:
        raise HTTPException(403, "服务器未配置主密钥, 此功能不可用")

    if not hmac.compare_digest(body.master_password.encode(), settings.auth_password.encode()):
        # 防爆破 - 故意延迟
        import time as _t; _t.sleep(0.5)
        raise HTTPException(401, "主密钥错误")

    target_username = body.target_username or "admin"
    user = db.query(models.User).filter_by(username=target_username).first()
    if not user:
        raise HTTPException(404, f"用户 {target_username} 不存在")

    # 解锁
    user.locked_until = None
    user.failed_login_count = 0
    if user.status in ("disabled", "rejected"):
        user.status = "active"  # 顺手激活

    msg_parts = [f"已解锁 {target_username}"]
    if body.reset_password_to:
        if len(body.reset_password_to) < 6:
            raise HTTPException(400, "新密码至少 6 位")
        user.password_hash = _hash_password(body.reset_password_to)
        user.force_password_change = True
        msg_parts.append("密码已重置")

    db.commit()
    ip = request.client.host if request.client else "?"
    logger.warning("Master-unlock from %s: %s", ip, " + ".join(msg_parts))
    return {
        "ok": True,
        "username": target_username,
        "unlocked": True,
        "password_reset": bool(body.reset_password_to),
        "message": " · ".join(msg_parts),
    }


# ============================================================
#  v0.8 自助注册 + 公共旅行社列表 (注册向导用)
# ============================================================
@router.get("/agencies-public")
def list_agencies_public(db: Session = Depends(get_db)):
    """供注册向导用 — 公开列出活跃旅行社, 让申请者选要加入哪家.
    不需要登录. 只返回 id+name+short_name, 不暴露 commission/credit 等敏感数据.
    """
    rows = db.query(models.Agency).filter_by(status="active").order_by(models.Agency.name).all()
    return [
        {"id": a.id, "name": a.name, "short_name": a.short_name}
        for a in rows
    ]


@router.post("/register-public")
def register_public(body: RegisterPublicIn, request: Request, db: Session = Depends(get_db)):
    """v0.8 — 自助注册申请 (无需邀请码, 但要管理员审核).

    流程:
    1. 校验用户名/密码格式
    2. 必须指定加入哪家旅行社 (agency_id) 或 申请新建一家 (requested_agency_name)
    3. 申请角色限定 ['agent', 'agency_owner', 'viewer']  — super_admin/ops_manager 必须超管邀请
    4. 创建 user with status='pending_review' — 不能直接登录, 等管理员审批
    """
    # 用户名/密码校验
    if len(body.username) < 4 or not body.username.replace("_", "").isalnum():
        raise HTTPException(400, "用户名至少 4 字符且只含字母/数字/下划线")
    if len(body.password) < 8:
        raise HTTPException(400, "密码至少 8 位")
    if db.query(models.User).filter_by(username=body.username).first():
        raise HTTPException(409, "用户名已被占用")

    # 角色白名单
    allowed_roles = {"agent", "agency_owner", "viewer"}
    if body.requested_role not in allowed_roles:
        raise HTTPException(400, f"requested_role 必须是 {allowed_roles}")

    # agency 二选一
    agency_id = body.agency_id
    requested_agency_name = body.requested_agency_name
    if not agency_id and not requested_agency_name:
        raise HTTPException(400, "必须选择要加入的旅行社, 或填写申请新建的旅行社名")
    if agency_id:
        agency = db.get(models.Agency, agency_id)
        if not agency or agency.status != "active":
            raise HTTPException(404, "选择的旅行社不存在或已停用")

    user = models.User(
        username=body.username,
        password_hash=_hash_password(body.password),
        display_name=body.display_name or body.username,
        email=body.email, phone=body.phone,
        role=body.requested_role,
        agency_id=agency_id,
        status="pending_review",  # ← 关键: 待审核, 不能登录
        application_note=body.application_note,
        requested_agency_name=requested_agency_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Public registration application: user=%s requested_role=%s agency_id=%s new_agency=%s",
                user.username, user.role, agency_id, requested_agency_name)
    return {
        "ok": True,
        "user_id": user.id,
        "username": user.username,
        "status": "pending_review",
        "message": "✓ 申请已提交! 请等待管理员审批. 审批通过后才能登录.",
    }
