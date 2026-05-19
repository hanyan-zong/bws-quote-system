"""核心资源模型 — 酒店/景点/餐厅/车辆/导游/SPA/水上/下午茶/自费/距离/模板."""
from __future__ import annotations

from datetime import date, time, datetime
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
    Time,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


# ============================================================
#  目的地
# ============================================================
class Destination(Base):
    __tablename__ = "destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_zh: Mapped[str] = mapped_column(String(60))
    name_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(30), default="Asia/Makassar")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    hotels: Mapped[list["Hotel"]] = relationship(back_populates="destination", cascade="all, delete-orphan")


# ============================================================
#  酒店
# ============================================================
class Hotel(Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str | None] = mapped_column(String(120), nullable=True)
    star: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    area: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    airport_distance_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)  # 0 停用 1 启用
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    destination: Mapped["Destination"] = relationship(back_populates="hotels")
    rooms: Mapped[list["HotelRoom"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")


class HotelRoom(Base):
    __tablename__ = "hotel_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), index=True)
    room_type: Mapped[str] = mapped_column(String(80))
    max_occupancy: Mapped[int] = mapped_column(SmallInteger, default=2)
    breakfast_included: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_idr_low: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    cost_idr_high: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    hotel: Mapped["Hotel"] = relationship(back_populates="rooms")


# ============================================================
#  景点
# ============================================================
class Attraction(Base):
    __tablename__ = "attractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str | None] = mapped_column(String(120), nullable=True)
    area: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    ticket_idr_adult: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    ticket_idr_child: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    recommended_minutes: Mapped[int] = mapped_column(Integer, default=60)
    open_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    close_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    has_guide_service: Mapped[bool] = mapped_column(Boolean, default=False)
    restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


# ============================================================
#  餐厅 / 下午茶
# ============================================================
class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(120))
    cuisine: Mapped[str | None] = mapped_column(String(40), nullable=True)
    meal_type: Mapped[str] = mapped_column(String(20), default="both")  # lunch/dinner/both
    area: Mapped[str | None] = mapped_column(String(60), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_idr_per_person: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    min_pax: Mapped[int] = mapped_column(Integer, default=1)
    includes_drink: Mapped[bool] = mapped_column(Boolean, default=False)
    recommended_minutes: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


class AfternoonTea(Base):
    __tablename__ = "afternoon_teas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(120))
    venue: Mapped[str | None] = mapped_column(String(120), nullable=True)
    area: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cost_idr_per_person: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    min_pax: Mapped[int] = mapped_column(Integer, default=1)
    recommended_minutes: Mapped[int] = mapped_column(Integer, default=90)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


# ============================================================
#  SPA / 水上
# ============================================================
class SpaPackage(Base):
    __tablename__ = "spa_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    package_name: Mapped[str] = mapped_column(String(120))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    cost_idr_per_person: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    includes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


class WaterActivity(Base):
    __tablename__ = "water_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cost_idr_per_person: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    min_pax: Mapped[int] = mapped_column(Integer, default=1)
    max_pax: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_limit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


# ============================================================
#  车辆 / 导游
# ============================================================
class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    seat_count: Mapped[int] = mapped_column(Integer)
    vehicle_type: Mapped[str] = mapped_column(String(60))
    cost_idr_per_day: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    includes_fuel: Mapped[bool] = mapped_column(Boolean, default=True)
    includes_driver: Mapped[bool] = mapped_column(Boolean, default=True)
    restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: ["Monkey Forest Street", ...]
    # 单段最长驾驶 (分钟); 大车山路/远途单段不能超时. null = 无限制
    max_single_leg_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 全天最长驾驶 (分钟); 覆盖全局 time_budget. null = 沿用全局
    max_daily_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 地形限制说明 (展示给客户看)
    terrain_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


class Guide(Base):
    __tablename__ = "guides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(20), default="zh")  # zh/en/id/zh+en
    level: Mapped[str] = mapped_column(String(20), default="regular")  # senior/regular/trainee
    cost_idr_per_day: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    max_pax: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 中文司机限 2-3 人
    availability_note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


# ============================================================
#  自费项目
# ============================================================
class OptionalTour(Base):
    __tablename__ = "optional_tours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(120))
    sale_price_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    cost_idr: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    margin_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    historical_purchase_rate: Mapped[float] = mapped_column(Float, default=0.5)
    target_audience: Mapped[str | None] = mapped_column(String(120), nullable=True)
    best_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # category 用于自费与行程内容的重叠判断
    # 取值: spa / sunset / sunrise / food_upgrade / performance / water / shopping / temple / shows / island_trip
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 关联的"已包含则排除"的资源 id 列表 (JSON):
    # 例如某 SPA 自费 → 当行程的 spa_id 已设置时排除. 多个 id 任一命中即视为已覆盖
    overlap_attraction_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    overlap_restaurant_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    overlap_spa_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    overlap_water_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


# ============================================================
#  距离矩阵 ★
# ============================================================
class Distance(Base):
    __tablename__ = "distances"
    __table_args__ = (
        UniqueConstraint("from_type", "from_id", "to_type", "to_id", name="uix_distance_pair"),
        Index("ix_distance_from", "from_type", "from_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_type: Mapped[str] = mapped_column(String(20))  # hotel/attraction/restaurant/airport
    from_id: Mapped[int] = mapped_column(Integer)
    to_type: Mapped[str] = mapped_column(String(20))
    to_id: Mapped[int] = mapped_column(Integer)
    distance_km: Mapped[float] = mapped_column(Float, default=0)
    normal_minutes: Mapped[int] = mapped_column(Integer, default=0)
    peak_minutes: Mapped[int] = mapped_column(Integer, default=0)
    holiday_minutes: Mapped[int] = mapped_column(Integer, default=0)
    route_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 该路段允许的最大座位车 (山路/小巷限大车). null = 无限制
    vehicle_max_seat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 该路段警告但允许的座位 (大于此值会出 warning, 大于 vehicle_max_seat 直接 fail)
    vehicle_warn_seat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


# ============================================================
#  一日游模板 ★
# ============================================================
class DayTripTemplate(Base):
    __tablename__ = "day_trip_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(ForeignKey("destinations.id"), index=True)
    name_zh: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_minutes_estimate: Mapped[int] = mapped_column(Integer, default=480)
    recommended_pax_min: Mapped[int] = mapped_column(Integer, default=1)
    recommended_pax_max: Mapped[int] = mapped_column(Integer, default=99)
    difficulty: Mapped[str] = mapped_column(String(20), default="easy")  # easy/moderate/intense
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    attractions: Mapped[list["TemplateAttraction"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )
    restaurants: Mapped[list["TemplateRestaurant"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class TemplateAttraction(Base):
    __tablename__ = "template_attractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("day_trip_templates.id"), index=True)
    attraction_id: Mapped[int] = mapped_column(ForeignKey("attractions.id"))
    order_index: Mapped[int] = mapped_column(Integer, default=1)
    stay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    template: Mapped["DayTripTemplate"] = relationship(back_populates="attractions")


class TemplateRestaurant(Base):
    __tablename__ = "template_restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("day_trip_templates.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    meal_type: Mapped[str] = mapped_column(String(20), default="lunch")

    template: Mapped["DayTripTemplate"] = relationship(back_populates="restaurants")
