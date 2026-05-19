"""Pydantic 请求/响应模型 — 与 ORM 解耦, 仅含必要字段.

注意: 不使用 `from __future__ import annotations`, 也不使用 `X | None` 联合,
因为 Pydantic v2 在 Python 3.10 评估字段注解时, 字段名(如 `date`) 与类型名(date)
同名会引发 'unsupported operand type(s) for |' 错误. 统一用 Optional[...] 规避.
"""

from datetime import date as _date, datetime as _datetime, time as _time
from decimal import Decimal
from typing import Any, List, Literal, Optional, Dict

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
#  通用
# ============================================================
class Pagination(BaseModel):
    page: int = 1
    page_size: int = 50


class OkResponse(BaseModel):
    ok: bool = True
    message: str = "ok"


# ============================================================
#  资源 — 出入参共用 ORM 风格 (v0.1 简化)
# ============================================================
class HotelRoomIn(BaseModel):
    id: Optional[int] = None
    room_type: str
    max_occupancy: int = 2
    breakfast_included: bool = False
    cost_idr_low: Decimal = Decimal(0)
    cost_idr_high: Decimal = Decimal(0)
    valid_from: Optional[_date] = None
    valid_to: Optional[_date] = None
    supplier: Optional[str] = None
    note: Optional[str] = None


class HotelIn(BaseModel):
    id: Optional[int] = None
    destination_id: int
    name_zh: str
    name_en: Optional[str] = None
    star: Optional[int] = None
    area: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    airport_distance_min: Optional[int] = None
    description: Optional[str] = None
    rooms: List[HotelRoomIn] = Field(default_factory=list)


class HotelOut(HotelIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AttractionIn(BaseModel):
    id: Optional[int] = None
    destination_id: int
    name_zh: str
    name_en: Optional[str] = None
    area: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    ticket_idr_adult: Decimal = Decimal(0)
    ticket_idr_child: Decimal = Decimal(0)
    recommended_minutes: int = 60
    open_time: Optional[_time] = None
    close_time: Optional[_time] = None
    has_guide_service: bool = False
    restrictions: Optional[str] = None


class AttractionOut(AttractionIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class RestaurantIn(BaseModel):
    id: Optional[int] = None
    destination_id: int
    name_zh: str
    cuisine: Optional[str] = None
    meal_type: Literal["lunch", "dinner", "both"] = "both"
    area: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    cost_idr_per_person: Decimal = Decimal(0)
    min_pax: int = 1
    includes_drink: bool = False
    recommended_minutes: int = 60


class RestaurantOut(RestaurantIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class VehicleIn(BaseModel):
    id: Optional[int] = None
    destination_id: int
    seat_count: int
    vehicle_type: str
    cost_idr_per_day: Decimal = Decimal(0)
    includes_fuel: bool = True
    includes_driver: bool = True
    restrictions: Optional[str] = None
    max_single_leg_minutes: Optional[int] = None
    max_daily_minutes: Optional[int] = None
    terrain_note: Optional[str] = None


class VehicleOut(VehicleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class GuideIn(BaseModel):
    id: Optional[int] = None
    destination_id: int
    name_zh: str
    language: str = "zh"
    level: str = "regular"
    cost_idr_per_day: Decimal = Decimal(0)
    max_pax: Optional[int] = None
    availability_note: Optional[str] = None


class GuideOut(GuideIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class OptionalTourIn(BaseModel):
    id: Optional[int] = None
    destination_id: int
    name_zh: str
    sale_price_cny: Decimal = Decimal(0)
    cost_idr: Decimal = Decimal(0)
    margin_cny: Decimal = Decimal(0)
    historical_purchase_rate: float = 0.5
    target_audience: Optional[str] = None
    best_time: Optional[str] = None
    category: Optional[str] = None
    overlap_attraction_ids: Optional[str] = None  # JSON array
    overlap_restaurant_ids: Optional[str] = None
    overlap_spa_ids: Optional[str] = None
    overlap_water_ids: Optional[str] = None


class OptionalTourOut(OptionalTourIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SimpleResourceIn(BaseModel):
    """SPA / 水上 / 下午茶 共用的简化 schema."""

    id: Optional[int] = None
    destination_id: int
    name_zh: str
    cost_idr_per_person: Decimal = Decimal(0)
    duration_minutes: int = 60
    extra: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
#  距离
# ============================================================
class DistanceIn(BaseModel):
    id: Optional[int] = None
    from_type: str
    from_id: int
    to_type: str
    to_id: int
    distance_km: float = 0
    normal_minutes: int = 0
    peak_minutes: int = 0
    holiday_minutes: int = 0
    route_note: Optional[str] = None
    vehicle_max_seat: Optional[int] = None
    vehicle_warn_seat: Optional[int] = None
    source: str = "manual"


# ============================================================
#  一日游模板
# ============================================================
class TemplateAttractionIn(BaseModel):
    attraction_id: int
    order_index: int = 1
    stay_minutes: Optional[int] = None


class TemplateRestaurantIn(BaseModel):
    restaurant_id: int
    meal_type: str = "lunch"


class TemplateIn(BaseModel):
    id: Optional[int] = None
    destination_id: int
    name_zh: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    total_minutes_estimate: int = 480
    recommended_pax_min: int = 1
    recommended_pax_max: int = 99
    difficulty: str = "easy"
    attractions: List[TemplateAttractionIn] = Field(default_factory=list)
    restaurants: List[TemplateRestaurantIn] = Field(default_factory=list)


# ============================================================
#  报价
# ============================================================
class QuoteItemIn(BaseModel):
    attraction_id: int
    order_index: int = 1
    arrival_time: Optional[_time] = None
    stay_minutes: Optional[int] = None


class QuoteDayIn(BaseModel):
    day_index: int
    date: Optional[_date] = None
    is_free: bool = False
    free_hours: int = 0  # 0=全程行程, 4=半天自由, 8=全天自由
    # v0.9.3: 行程时长类型
    day_type: Literal["full", "half", "arrival", "departure"] = "full"
    template_id: Optional[int] = None
    hotel_id: Optional[int] = None
    hotel_room_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    guide_id: Optional[int] = None
    breakfast_included: bool = False
    lunch_restaurant_id: Optional[int] = None
    dinner_restaurant_id: Optional[int] = None
    afternoon_tea_id: Optional[int] = None
    spa_id: Optional[int] = None
    water_activity_id: Optional[int] = None
    start_time: Optional[_time] = None
    notes: Optional[str] = None
    attractions: List[QuoteItemIn] = Field(default_factory=list)


class QuoteIn(BaseModel):
    id: Optional[int] = None
    agency_name: Optional[str] = None
    agency_contact: Optional[str] = None
    customer_name: Optional[str] = None
    pax_adult: int = 2
    pax_child: int = 0
    pax_senior: int = 0  # v0.5.2: 55+ 老年人(pax_adult 子集; 用于赌自费判定)
    start_date: Optional[_date] = None
    end_date: Optional[_date] = None
    destination_codes: List[str] = Field(default_factory=list)
    season: Literal["low", "shoulder", "high"] = "shoulder"
    customer_type: str = "family"
    is_first_time_agency: bool = False
    exchange_rate: Optional[Decimal] = None
    notes: Optional[str] = None
    # 航班(v0.2.5)
    arrival_at: Optional[_datetime] = None
    departure_at: Optional[_datetime] = None
    arrival_airport: Optional[str] = None
    departure_airport: Optional[str] = None
    days: List[QuoteDayIn] = Field(default_factory=list)


class QuoteCalculateOut(BaseModel):
    quote_id: int
    quote_no: str
    cost_idr_total: Decimal
    cost_cny_total: Decimal
    profit_cny_per_pax: Decimal
    gamble_cny_per_pax: Decimal
    price_cny_per_pax: Decimal
    price_cny_total: Decimal
    feasibility_status: str
    feasibility_report: Dict[str, Any]
    gamble_recommendation: Optional[Dict[str, Any]] = None


# ============================================================
#  AI / 校验 / 赌自费
# ============================================================
class ConfirmExtractionIn(BaseModel):
    confirmed_resources: List[Dict[str, Any]]
    corrections: List[Dict[str, Any]] = Field(default_factory=list)


class GambleRecommendIn(BaseModel):
    quote_id: int


class GambleApplyIn(BaseModel):
    quote_id: int
    applied_cny: Decimal


class GambleFeedbackIn(BaseModel):
    quote_id: int
    optional_tours_revenue_cny: Decimal
    profit_actual_cny: Decimal
    won_or_lost: Literal["won", "lost"]


# ============================================================
#  设置
# ============================================================
class ExchangeRateIn(BaseModel):
    rate_cny_to_idr: Decimal
    effective_date: Optional[_date] = None
    set_by: Optional[str] = None
    note: Optional[str] = None


class TimeBudgetIn(BaseModel):
    max_drive_minutes_per_day: int = 300
    max_drive_warn_minutes: int = 240
    morning_peak_coef: float = 1.40
    evening_peak_coef: float = 1.55
    holiday_coef: float = 1.65
    hotel_to_first_max_minutes: int = 90
    airport_buffer_minutes: int = 60


class GambleConfigIn(BaseModel):
    enable_gambling: bool = True
    safety_ratio: float = 0.7
    max_loss_ratio: float = 0.25
    first_time_agency_factor: float = 0.5
    default_margin_rate: float = 0.5
    mice_wedding_max_cny: Decimal = Decimal(150)


class NoGambleRuleIn(BaseModel):
    """不赌自费规则.

    conditions 是 condition 对象的列表, 单个对象形如:
      {"type": "customer_type_in", "value": ["mice", "wedding"]}
    支持的 type 见 models.NoGambleRule 注释.
    """

    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    active: bool = True
    priority: int = 0


class GambleStrategyIn(BaseModel):
    """赌自费策略 (v0.5.1 简化版) — 替代 NoGambleRule + 复杂算法.

    一条 = 一种行程组合 + 对应动作.
    action:
      - "skip"  不赌 — gamble_cny=0; 可指定 extra_profit_cny 反向加价 ¥/人
      - "fixed" 赌 — 让利 gamble_cny 出去 (¥/人)
      - "per_pax" (deprecated, 保留兼容老数据 = 按团总让)
    """

    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    action: Literal["skip", "fixed", "per_pax"] = "skip"
    gamble_cny: Decimal = Decimal(0)
    extra_profit_cny: Decimal = Decimal(0)  # v0.5.1: skip 时反向加 ¥/人 利润
    priority: int = 0
    active: bool = True


class GambleStrategyPreviewIn(BaseModel):
    """模拟一份行程信号, 看哪条策略命中(用户在 UI 试错用)."""

    customer_type: str = "family"
    season: Literal["low", "shoulder", "high"] = "shoulder"
    total_days: int = 5
    free_hours_total: int = 8
    pax_total: int = 2
    is_first_time_agency: bool = False
    all_meals_included: bool = False
    has_spa_booked: bool = False
    has_water_booked: bool = False
