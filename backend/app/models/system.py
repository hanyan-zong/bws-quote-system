"""系统/审计表 — 汇率、时间预算、赌自费配置、AI 解析记录、修正反馈."""
from __future__ import annotations

from datetime import date, datetime
from ..utils.time_utils import now_utc
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_date: Mapped[date] = mapped_column(Date)
    rate_cny_to_idr: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=2300)
    set_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class TimeBudgetConfig(Base):
    __tablename__ = "time_budget_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int | None] = mapped_column(ForeignKey("destinations.id"), nullable=True)  # null = 全局
    max_drive_minutes_per_day: Mapped[int] = mapped_column(Integer, default=300)
    max_drive_warn_minutes: Mapped[int] = mapped_column(Integer, default=240)
    morning_peak_coef: Mapped[float] = mapped_column(Float, default=1.40)
    evening_peak_coef: Mapped[float] = mapped_column(Float, default=1.55)
    holiday_coef: Mapped[float] = mapped_column(Float, default=1.65)
    hotel_to_first_max_minutes: Mapped[int] = mapped_column(Integer, default=90)
    airport_buffer_minutes: Mapped[int] = mapped_column(Integer, default=60)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class GambleConfig(Base):
    __tablename__ = "gamble_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enable_gambling: Mapped[bool] = mapped_column(Boolean, default=True)
    safety_ratio: Mapped[float] = mapped_column(Float, default=0.7)
    max_loss_ratio: Mapped[float] = mapped_column(Float, default=0.25)
    first_time_agency_factor: Mapped[float] = mapped_column(Float, default=0.5)
    default_margin_rate: Mapped[float] = mapped_column(Float, default=0.5)
    mice_wedding_max_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=150)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class AiExtraction(Base):
    """AI 文档解析记录."""

    __tablename__ = "ai_extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(200))
    file_type: Mapped[str] = mapped_column(String(20))  # pdf/docx/xlsx/image
    file_path: Mapped[str] = mapped_column(String(300))
    hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    extraction_summary: Mapped[str | None] = mapped_column(String(400), nullable=True)
    extracted_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/confirmed/rejected
    confidence_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    warnings: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NoGambleRule(Base):
    """不赌自费规则 — 用户可在系统里维护.

    规则结构: 一个规则包含若干 conditions (JSON 列表), 全部匹配则触发"不赌"决策.
    单条 condition 形如 {"type": "<类型>", "value": <值>}.
    支持的 condition.type:
      - customer_type_in: value=列表, 例 ["mice", "wedding"]
      - free_hours_lt: value=int, 总自由小时 < value
      - free_hours_gt: value=int
      - total_days_lt: value=int
      - total_days_gt: value=int
      - pax_total_lt: value=int
      - pax_total_gt: value=int
      - is_first_time_agency: value=true/false
      - all_meals_included: value=true (每个非自由日 lunch+dinner 全设)
      - spa_already_booked: value=true (任一日 spa_id 已设)
      - season_in: value=列表, 例 ["low"]
      - all_categories_covered: value=true (所有 optional_tour 的 category 都有对应资源在行程内)
    """

    __tablename__ = "no_gamble_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[str] = mapped_column(Text)  # JSON 列表
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 数大的先评估
    created_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class GambleStrategy(Base):
    """赌自费策略 — 一条 = 一种行程组合 + 对应让利金额(或不赌). v0.3.

    替代 NoGambleRule(只能 yes/no) + 复杂算法. 用户在 UI 里"案例编辑器"风格直接填.

    评估: priority 倒序, all-conditions-AND, 首条命中即返回.
    全不匹配 → 走 fallback(GambleConfig.default_fallback_cny 或老算法兜底).

    action 取值 (v0.5.1 简化):
      - "skip"   不赌 — 不让利, 同时可以指定 extra_profit_cny 反向加价
      - "fixed"  赌 — 让利 gamble_cny / 人 出去
      - "per_pax" (deprecated, 保留向后兼容; 老数据 = 按团总让, 不再生成新条目)

    conditions 复用 NoGambleRule 的 12 种 condition_type:
      customer_type_in / free_hours_lt|gt / total_days_lt|gt / pax_total_lt|gt
      is_first_time_agency / all_meals_included / spa_already_booked
      water_already_booked / season_in
      v0.5.1 新增:
      has_attraction_id_in / excludes_attraction_id_in / has_restaurant_id_in
    """

    __tablename__ = "gamble_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[str] = mapped_column(Text)  # JSON 列表
    action: Mapped[str] = mapped_column(String(20), default="skip")  # skip|fixed|per_pax
    gamble_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    # v0.5.1: 当 action=skip 时, 反向给 quote 加 ¥X/人 利润 (本来不会让利, 现在反而加价)
    extra_profit_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class AttractionConflictRule(Base):
    """景点互斥规则 — 同一天不能同时安排的两个景点.

    例:
      - 罗威纳海豚(凌晨 5:00 出发)+ 乌鲁瓦图日落 → error(时间不可能)
      - 圣猴森林 + 乌布皇宫 + 已含 → warning(同区域重复)

    判断:对每天 day,如果 day.attractions 包含 attr_a_id AND attr_b_id,触发.
    """
    __tablename__ = "attraction_conflict_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attraction_a_id: Mapped[int] = mapped_column(ForeignKey("attractions.id"), index=True)
    attraction_b_id: Mapped[int] = mapped_column(ForeignKey("attractions.id"), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # warning|error
    message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AreaRule(Base):
    """区域不兼容规则 — 防止极限/不合理行程组合.

    例:
      - 住努沙杜瓦,景点在罗威纳 → error(单程 4h,做不了一日游)
      - 住乌布,景点在乌鲁瓦图 → warning(单程 90min+ 不推荐当天往返)

    判断逻辑(feasibility 引擎):
      对每天 day,如果 day.hotel.area == hotel_area
      且 day.attractions 中有任一 attraction.area == excluded_attraction_area,
      则按 severity 输出 error/warning + message
    """

    __tablename__ = "area_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hotel_area: Mapped[str] = mapped_column(String(40))            # 住宿在哪个区域
    excluded_attraction_area: Mapped[str] = mapped_column(String(40))  # 不能搭配的景点区域
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # warning|error
    message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Agency(Base):
    """B 端旅行社. v0.4 邀请制."""

    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    short_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(60), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    credit_limit_cny: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|suspended
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class User(Base):
    """系统用户. v0.7 — 5 角色:
       super_admin   — 公司超管 (无限配额)
       ops_manager   — 公司 OP 操作员 (跨 agency 帮做单, 大配额)
       agency_owner  — B 端旅行社老板 (本社全部, 中配额)
       agent         — B 端业务员 (仅自己 quote, 小配额)
       viewer        — 基础只读用户 (无 AI/导出)
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="agent")  # super_admin|ops_manager|agency_owner|agent|viewer
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"), nullable=True, index=True)
    # v0.8 状态新增 pending_review / rejected
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|disabled|pending_review|rejected
    # v0.8 自助注册申请
    application_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 申请理由
    requested_agency_name: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 申请新建的旅行社名(可选)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 审核备注
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Invitation(Base):
    """邀请码 — super_admin 邀 agency_owner / agency_owner 邀本社业务员."""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"))
    role: Mapped[str] = mapped_column(String(20))  # 注册后赋的角色
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RefreshToken(Base):
    """APP 端 JWT 双 token 的 refresh token 撤销表 (v0.10).

    库里只存 sha256(token), 不存原文 — 撤库泄露也无法直接冒用.
    旋转: 每次 /auth/refresh 旧 token 标记 revoked_at 并发新 token.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_info: Mapped[str | None] = mapped_column(String(200), nullable=True)  # UA/设备标识, 排查异常登录用
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class ErpSyncEvent(Base):
    """ERP 同步事件队列 (v0.4 留位 / v0.5 worker 真正消费)."""

    __tablename__ = "erp_sync_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)  # quote.accepted / gamble.feedback / ...
    entity_type: Mapped[str] = mapped_column(String(40))  # quote / gamble_history / agency / user
    entity_id: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text)  # JSON

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|synced|failed|skipped
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=5)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    correlation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    synced_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ErpConfig(Base):
    """ERP 同步配置 (单行表)."""

    __tablename__ = "erp_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # v0.4 默认关
    webhook_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    auth_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet 加密
    retry_max: Mapped[int] = mapped_column(Integer, default=5)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, default=60)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class UsageQuota(Base):
    """v0.7 — 用户在某功能上的配额状态.

    每 (user_id, feature) 一条记录:
      limit_count = -1 → 无限
      limit_count = 0  → 禁用
      limit_count > 0  → 该周期内最多用这么多次
    period: daily | monthly | total (total 不重置)
    """

    __tablename__ = "usage_quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    feature: Mapped[str] = mapped_column(String(60), index=True)
    period: Mapped[str] = mapped_column(String(20), default="monthly")  # daily|monthly|total
    limit_count: Mapped[int] = mapped_column(Integer, default=0)        # -1 = 无限
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 下次重置时间
    overridden_by_admin: Mapped[bool] = mapped_column(Boolean, default=False)   # 标识非默认值
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class UsageLog(Base):
    """v0.7 — 功能使用流水 (审计 + 统计基础)."""

    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    agency_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(60), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_msg: Mapped[str | None] = mapped_column(String(300), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 比如 quote_id, file_name
    used_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class AiCorrection(Base):
    """AI 字段修正记录 — 用户改了 AI 的输出就写一条，用于持续优化."""

    __tablename__ = "ai_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(ForeignKey("ai_extractions.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    field_name: Mapped[str] = mapped_column(String(80))
    ai_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
