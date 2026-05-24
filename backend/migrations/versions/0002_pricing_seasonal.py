"""Add season_calendars / room_rates / surcharges / hotel_packages

Revision ID: 0002_pricing_seasonal
Revises: 0001_quote_day_day_type
Create Date: 2026-05-24

v0.9.4: 季节多档定价 + 附加费 + 节日捆绑包.
向下兼容: 老 HotelRoom.cost_idr_low/high 保留, 由 pricing_engine 做 fallback.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0002_pricing_seasonal"
down_revision = "0001_quote_day_day_type"
branch_labels = None
depends_on = None


def _table_exists(insp, name: str) -> bool:
    return name in set(insp.get_table_names())


def upgrade() -> None:
    """Idempotent: 表存在则跳过 (init_db 已 create_all 出新表的情况)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _table_exists(insp, "season_calendars"):
        op.create_table(
            "season_calendars",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("season_band", sa.String(length=20), nullable=False),
            sa.Column("date_from", sa.Date(), nullable=False),
            sa.Column("date_to", sa.Date(), nullable=False),
            sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="0"),
            sa.Column("destination_code", sa.String(length=20), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_season_cal_dates", "season_calendars", ["date_from", "date_to"])

    if not _table_exists(insp, "room_rates"):
        op.create_table(
            "room_rates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("room_id", sa.Integer(), sa.ForeignKey("hotel_rooms.id", ondelete="CASCADE"), nullable=False),
            sa.Column("season_band", sa.String(length=20), nullable=False),
            sa.Column("cost_idr", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_room_rates_room_id", "room_rates", ["room_id"])
        op.create_index("ix_room_rate_room_band", "room_rates", ["room_id", "season_band"])

    if not _table_exists(insp, "surcharges"):
        op.create_table(
            "surcharges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("hotel_id", sa.Integer(), sa.ForeignKey("hotels.id", ondelete="CASCADE"), nullable=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("charge_type", sa.String(length=30), nullable=False),
            sa.Column("calc_method", sa.String(length=30), nullable=False),
            sa.Column("amount", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("season_band", sa.String(length=60), nullable=True),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_surcharges_hotel_id", "surcharges", ["hotel_id"])

    if not _table_exists(insp, "hotel_packages"):
        op.create_table(
            "hotel_packages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("hotel_id", sa.Integer(), sa.ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("season_band", sa.String(length=20), nullable=True),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("valid_to", sa.Date(), nullable=False),
            sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("cost_idr_per_room", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("cost_idr_per_pax", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("includes", sa.Text(), nullable=True),
            sa.Column("replaces_dinner", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_hotel_packages_hotel_id", "hotel_packages", ["hotel_id"])


def downgrade() -> None:
    op.drop_table("hotel_packages")
    op.drop_table("surcharges")
    op.drop_table("room_rates")
    op.drop_table("season_calendars")
