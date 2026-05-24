"""季节多档定价 / 附加费 / 节日捆绑包 — 2026-05-24 v0.9.4 引入.

设计依据 (GitHub 调研结论):
- Booking.com Connectivity API: RateRelation (derived rate) + RatePlan + Meal
- Apaleo: Surcharge 可绝对值/百分比
- Resort Data Processing: Package 由可复用 Component 组成, 每个 Component 可按 season × room_type 多档
- Google Hotel Price structured data: ResortFee / GenericTax / ServiceFee / TransferFee

四张表:
  SeasonCalendar  全局日历区间, 把日期 → season_band 标签
  RoomRate        房型 × 季节档 × 价格 (替代 HotelRoom.cost_idr_low/high 二档制)
  Surcharge       附加费 (政府税 21% / 服务费 10% / 旅游税 IDR 150k 等)
  HotelPackage    节日/季节捆绑包 (圣诞 Gala / 新年烟花包 / 强制餐升级)

向下兼容: HotelRoom.cost_idr_low/high 保留. pricing_engine 优先查 RoomRate,
没有匹配再 fallback 到旧字段 (low→shoulder, high→high).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..utils.time_utils import now_utc


SEASON_BANDS = ("low", "shoulder", "high", "peak", "holiday")


class SeasonCalendar(Base):
    """季节日历区间. 一条记录 = 一段连续日期的季节档.

    优先级: holiday > peak > high > shoulder > low (用 priority 字段表达,
    重叠时按 priority DESC 取第一条).
    """

    __tablename__ = "season_calendars"
    __table_args__ = (
        Index("ix_season_cal_dates", "date_from", "date_to"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))  # "2026 春节高峰" / "2026 圣诞新年"
    season_band: Mapped[str] = mapped_column(String(20))  # low/shoulder/high/peak/holiday
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)
    destination_code: Mapped[str | None] = mapped_column(String(20), nullable=True)  # null=全部目的地通用
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class RoomRate(Base):
    """房型 × 季节档 × 价格. 替代 HotelRoom.cost_idr_low/high 二档."""

    __tablename__ = "room_rates"
    __table_args__ = (
        Index("ix_room_rate_room_band", "room_id", "season_band"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("hotel_rooms.id", ondelete="CASCADE"), index=True)
    season_band: Mapped[str] = mapped_column(String(20))  # low/shoulder/high/peak/holiday
    cost_idr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)  # 可选: 该档某年特价
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Surcharge(Base):
    """酒店附加费 (政府税 / 服务费 / 旅游税 / Resort Fee).

    calc_method:
      - "percent"          → amount 是百分比 (21.00 = 21%), 在 (房费+前置费) 上叠加
      - "fixed_per_room_night"  → amount IDR/房/晚
      - "fixed_per_pax_night"   → amount IDR/人/晚
      - "fixed_per_stay"   → amount IDR/整次入住 (一次性)
    """

    __tablename__ = "surcharges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))  # "Government Tax 21%" / "Tourist Tax IDR 150k"
    charge_type: Mapped[str] = mapped_column(String(30))  # tax / service_fee / resort_fee / tourist_tax / other
    calc_method: Mapped[str] = mapped_column(String(30))  # percent / fixed_per_room_night / fixed_per_pax_night / fixed_per_stay
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    season_band: Mapped[str | None] = mapped_column(String(60), nullable=True)  # null=所有季节; 多档逗号分隔 "high,peak"
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class HotelPackage(Base):
    """节日/季节捆绑包. 圣诞 Gala Dinner / 新年烟花包 / 中秋月饼包.

    mandatory=True 时: 在 valid_from~valid_to 期间住该酒店必须购买,
    pricing_engine 自动叠加成本; replaces_dinner=True 时, 当晚另设的晚餐
    会被替换(避免双算).
    """

    __tablename__ = "hotel_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))  # "Christmas Eve Gala Dinner"
    season_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_idr_per_room: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    cost_idr_per_pax: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    includes: Mapped[str | None] = mapped_column(Text, nullable=True)  # "圣诞晚宴 + 烟花 + 红酒 1 瓶"
    replaces_dinner: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
