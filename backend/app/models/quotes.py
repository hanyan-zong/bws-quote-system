"""报价单模型族."""
from __future__ import annotations

from datetime import date, datetime, time
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    agency_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agency_contact: Mapped[str | None] = mapped_column(String(60), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    pax_adult: Mapped[int] = mapped_column(Integer, default=2)
    pax_child: Mapped[int] = mapped_column(Integer, default=0)
    pax_senior: Mapped[int] = mapped_column(Integer, default=0)  # v0.5.2: 55 岁以上老年人(pax_adult 中的子集; 用于赌自费判定)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_days: Mapped[int] = mapped_column(Integer, default=1)
    free_days: Mapped[int] = mapped_column(Integer, default=0)

    # 航班信息(用于自动判断首日/末日实际可用时长)
    arrival_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    departure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrival_airport: Mapped[str | None] = mapped_column(String(8), nullable=True)
    departure_airport: Mapped[str | None] = mapped_column(String(8), nullable=True)

    destination_codes: Mapped[str] = mapped_column(String(120), default="")  # "DPS,CGK"
    season: Mapped[str] = mapped_column(String(10), default="shoulder")  # low/shoulder/high
    customer_type: Mapped[str] = mapped_column(String(30), default="family")
    is_first_time_agency: Mapped[bool] = mapped_column(Boolean, default=False)

    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=2300)

    # 计价结果
    cost_idr_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cost_cny_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    profit_cny_per_pax: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    gamble_cny_per_pax: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    price_cny_per_pax: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    price_cny_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    feasibility_status: Mapped[str] = mapped_column(String(20), default="unchecked")  # pass/warning/fail/unchecked
    feasibility_report: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON

    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/sent/accepted/lost
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # v0.4 多用户:
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    agency_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    days: Mapped[list["QuoteDay"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="QuoteDay.day_index"
    )
    optional_tours: Mapped[list["QuoteOptionalTour"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan"
    )
    gamble_records: Mapped[list["GambleHistory"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan"
    )


class QuoteDay(Base):
    __tablename__ = "quote_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    day_index: Mapped[int] = mapped_column(Integer)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    free_hours: Mapped[int] = mapped_column(Integer, default=0)  # 0=全程行程, 4=半天自由, 8=全天自由
    # v0.9.3: 行程时长类型 — full=全天 / half=半天 / arrival=抵达日(下午到) / departure=离开日(上午送机+早餐)
    # half/arrival/departure 三种: vehicle/guide 成本按 0.5 天算; departure 类型隐含 hotel_id=null + breakfast_included=true
    day_type: Mapped[str] = mapped_column(String(20), default="full")
    template_id: Mapped[int | None] = mapped_column(ForeignKey("day_trip_templates.id"), nullable=True)

    hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id"), nullable=True)
    hotel_room_id: Mapped[int | None] = mapped_column(ForeignKey("hotel_rooms.id"), nullable=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    guide_id: Mapped[int | None] = mapped_column(ForeignKey("guides.id"), nullable=True)

    breakfast_included: Mapped[bool] = mapped_column(Boolean, default=False)
    lunch_restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"), nullable=True)
    dinner_restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"), nullable=True)
    afternoon_tea_id: Mapped[int | None] = mapped_column(ForeignKey("afternoon_teas.id"), nullable=True)
    spa_id: Mapped[int | None] = mapped_column(ForeignKey("spa_packages.id"), nullable=True)
    water_activity_id: Mapped[int | None] = mapped_column(ForeignKey("water_activities.id"), nullable=True)

    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    quote: Mapped["Quote"] = relationship(back_populates="days")
    items: Mapped[list["QuoteItem"]] = relationship(
        back_populates="day", cascade="all, delete-orphan", order_by="QuoteItem.order_index"
    )


class QuoteItem(Base):
    """每日的景点明细."""

    __tablename__ = "quote_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_day_id: Mapped[int] = mapped_column(ForeignKey("quote_days.id"), index=True)
    attraction_id: Mapped[int] = mapped_column(ForeignKey("attractions.id"))
    order_index: Mapped[int] = mapped_column(Integer, default=1)
    arrival_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    stay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    day: Mapped["QuoteDay"] = relationship(back_populates="items")


class QuoteOptionalTour(Base):
    """报价单附带推荐的自费项目."""

    __tablename__ = "quote_optional_tours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    optional_tour_id: Mapped[int] = mapped_column(ForeignKey("optional_tours.id"))
    recommended_for_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_purchase_rate: Mapped[float] = mapped_column(Float, default=0.5)

    quote: Mapped["Quote"] = relationship(back_populates="optional_tours")


class GambleHistory(Base):
    """赌自费历史 — 反哺模型用."""

    __tablename__ = "gamble_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    recommended_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    applied_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    optional_tours_revenue_cny: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    profit_actual_cny: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    won_or_lost: Mapped[str] = mapped_column(String(10), default="pending")  # won/lost/partial/pending
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v0.5 反哺闭环:
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    feedback_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    feedback_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    quote: Mapped["Quote"] = relationship(back_populates="gamble_records")
