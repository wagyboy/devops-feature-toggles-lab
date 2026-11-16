"""Database: SQLite locally, PostgreSQL on Render. SQLAlchemy Core, always with bound parameters."""
from datetime import datetime, timezone

from flask import Flask, current_app
from sqlalchemy import (Boolean, Column, DateTime, Engine, Integer, MetaData, String, Table, Text, UniqueConstraint,
                        create_engine, func, insert, select)
from sqlalchemy.exc import IntegrityError

metadata = MetaData()


def _now() -> datetime:
    return datetime.now(timezone.utc)


products = Table(
    "products", metadata,
    Column("sku", String(20), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("price", Integer, nullable=False),
    Column("stock", Integer, nullable=False),
    Column("blurb", Text, nullable=False),
)

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("provider", String(20), nullable=False),      # "github", or "dev" for local testing
    Column("provider_id", String(64), nullable=False),
    Column("login", String(100), nullable=False),
    Column("avatar", String(300)),
    Column("role", String(20), nullable=False),          # "customer" or "admin"
    Column("created_at", DateTime(timezone=True), default=_now),
    UniqueConstraint("provider", "provider_id"),
)

# One row per tracked action. Each row records the user's variant of BOTH experiments,
# so the analysis never has to re-derive who saw what.
events = Table(
    "events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), default=_now, index=True),
    Column("user_id", Integer, nullable=False),
    Column("visit_id", String(32), nullable=False),
    Column("event", String(20), nullable=False),         # list_view, impression, click, product_view, purchase
    Column("sku", String(20)),
    Column("low_stock", Boolean),
    Column("source", String(20)),                        # where a purchase came from: "list" or "product"
    Column("quick_buy", Boolean, nullable=False),
    Column("stock_badge", Boolean, nullable=False),
)

# Runtime changes made in the admin console; they override flags.json without a redeploy.
flag_overrides = Table(
    "flag_overrides", metadata,
    Column("flag", String(40), primary_key=True),
    Column("enabled", Boolean, nullable=False),
    Column("rollout", Integer, nullable=False),
    Column("updated_by", String(100), nullable=False),
    Column("updated_at", DateTime(timezone=True), default=_now),
)

flag_audit = Table(
    "flag_audit", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), default=_now),
    Column("actor", String(100), nullable=False),
    Column("flag", String(40), nullable=False),
    Column("change", Text, nullable=False),
)

# Stock levels are fixed: purchases are simulated orders, so both experiment groups always see
# the same catalogue and the same low-stock items.
CATALOGUE = [
    ("SKU-100", "Mechanical keyboard", 120, 30, "Hot-swappable switches, aluminium case."),
    ("SKU-200", "27\" 4K monitor", 450, 15, "IPS panel, USB-C with 65 W charging."),
    ("SKU-300", "Standing desk", 990, 4, "Electric, two motors, memory presets."),
    ("SKU-400", "Noise-cancelling headphones", 280, 3, "30 h battery, multipoint Bluetooth."),
    ("SKU-500", "Ergonomic mouse", 60, 40, "Vertical grip, silent buttons."),
    ("SKU-600", "USB-C dock", 150, 5, "Dual display, 100 W pass-through."),
    ("SKU-700", "1080p webcam", 90, 25, "Auto light correction, privacy shutter."),
    ("SKU-800", "LED desk lamp", 45, 2, "Adjustable colour temperature."),
]


def _database_url(url: str) -> str:
    # Render gives postgres:// or postgresql://; SQLAlchemy needs the psycopg (v3) driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def init_app(app: Flask) -> None:
    engine = create_engine(_database_url(app.config["DATABASE_URL"]), pool_pre_ping=True)
    app.extensions["engine"] = engine
    metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(products)).scalar_one() == 0:
            for sku, name, price, stock, blurb in CATALOGUE:
                try:
                    with conn.begin_nested():
                        conn.execute(insert(products).values(sku=sku, name=name, price=price, stock=stock,
                                                             blurb=blurb))
                except IntegrityError:
                    pass  # another worker seeded it first


def engine() -> Engine:
    return current_app.extensions["engine"]
