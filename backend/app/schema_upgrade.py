"""
schema_upgrade.py
=================
Best-effort live-database migrator for CampusMart AI (Phase 7 + production
multi-angle upgrade + college network / order-handover release).

`Base.metadata.create_all` only creates MISSING tables — it never ALTERs an
existing table. On a live Render/Neon Postgres that was provisioned before the
current release, this module adds missing columns idempotently with
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (PostgreSQL-only) and creates the
brand-new tables (`system_config`, `chat_messages`, `email_otps`,
`action_otps`, `ai_chat_sessions`, `ai_chat_messages`, `notifications`,
`cart_items`) with `checkfirst=True`.

Covered by this file:
    Phase 7 columns : users.status, users.password_hash, products.trust_reason
    Upgrade columns : products.image_urls (JSON), products.ai_tags,
                      products.ai_condition_notes, chat_messages.read_at
    College network : users.college_name/code, products.college_name/code,
                      email_otps.college_name/code
    Order handover  : transactions.delivery_address/hostel_or_landmark/
                      contact_phone/payment_method/upi_reference/order_notes/
                      otp_code/order_status
    College search  : college_directory (AI/web-discovered colleges cache)
    New tables      : system_config, chat_messages, email_otps, action_otps,
                      ai_chat_sessions, ai_chat_messages, notifications,
                      cart_items, college_directory

This is a stopgap until Alembic migrations land (see README roadmap).
SQLite (test harnesses) always builds a fresh schema via create_all, so the
ALTER path is a no-op there — the table creation remains safe thanks to the
existence check.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .models import (
    ActionOTP,
    AiChatMessage,
    AiChatSession,
    CartItem,
    ChatMessage,
    CollegeDirectory,
    EmailOTP,
    Notification,
    SystemConfig,
)

logger = logging.getLogger(__name__)

# (table, column, DDL type clause) — append new production columns here.
_NEW_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("users", "status", "VARCHAR(16) DEFAULT 'active'"),
    ("users", "password_hash", "VARCHAR(128)"),
    ("products", "trust_reason", "TEXT"),
    # --- Production multi-angle / AI-search upgrade -------------------------
    # JSON (not JSONB) so the same DDL is valid on every PostgreSQL version
    # Neon offers and SQLAlchemy still decodes it into a Python list.
    ("products", "image_urls", "JSON"),
    ("products", "ai_tags", "TEXT"),
    ("products", "ai_condition_notes", "TEXT"),
    # Unread badge support for the Messages tab (NULL = unread).
    ("chat_messages", "read_at", "TIMESTAMP WITH TIME ZONE"),
    # WhatsApp-style photo messages (Cloudinary URL, nullable).
    ("chat_messages", "image_url", "TEXT"),
    # --- College network ------------------------------------------------------
    ("users", "college_name", "VARCHAR(255)"),
    ("users", "college_code", "VARCHAR(16)"),
    ("products", "college_name", "VARCHAR(255)"),
    ("products", "college_code", "VARCHAR(16)"),
    ("email_otps", "college_name", "VARCHAR(255)"),
    ("email_otps", "college_code", "VARCHAR(16)"),
    # --- Structured checkout (order handover) ---------------------------------
    ("transactions", "delivery_address", "VARCHAR(400)"),
    ("transactions", "hostel_or_landmark", "VARCHAR(200)"),
    ("transactions", "contact_phone", "VARCHAR(20)"),
    ("transactions", "payment_method", "VARCHAR(30)"),
    ("transactions", "upi_reference", "VARCHAR(120)"),
    ("transactions", "order_notes", "TEXT"),
    ("transactions", "otp_code", "VARCHAR(8)"),
    ("transactions", "order_status", "VARCHAR(40) DEFAULT 'Requested / Processing'"),
)

# Brand-new tables that older databases predate. `create_all` covers them on
# a fresh boot; this loop covers "run schema_upgrade against the live DB".
_NEW_TABLES = (
    SystemConfig.__table__,
    ChatMessage.__table__,
    EmailOTP.__table__,
    ActionOTP.__table__,
    AiChatSession.__table__,
    AiChatMessage.__table__,
    Notification.__table__,
    CartItem.__table__,
    CollegeDirectory.__table__,
)


def upgrade_schema(engine: Engine) -> None:
    """Bring a pre-existing database up to the current model set.

    Safe to call on every boot: table creation is guarded by checkfirst and
    every ALTER is guarded by IF NOT EXISTS.
    """
    inspector = inspect(engine)

    # 1. New tables first (chat_messages must exist before its column ALTER).
    #    `checkfirst=True` makes the CREATE TABLE a no-op when it is already
    #    there, so this doubles as the create_all safety net for live DBs.
    for table in _NEW_TABLES:
        if not inspector.has_table(table.name):
            table.create(bind=engine, checkfirst=True)
            logger.info("schema_upgrade: created table %s", table.name)

    # 2. New columns — PostgreSQL only (SQLite test schemas are always fresh).
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, column, ddl_type in _NEW_COLUMNS:
            if table not in existing_tables:
                continue  # create_all will build it with the column already
            columns = {c["name"] for c in inspector.get_columns(table)}
            if column in columns:
                continue
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl_type}")
            )
            logger.info("schema_upgrade: added %s.%s", table, column)
