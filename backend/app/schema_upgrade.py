"""
schema_upgrade.py
=================
Best-effort live-database column migrator for CampusMart AI (Phase 7).

`Base.metadata.create_all` only creates MISSING tables — it never ALTERs an
existing table. On a live Render Postgres that was provisioned before Phase 7
(columns `users.status`, `users.password_hash`, `products.trust_reason` did
not exist), this module adds those columns idempotently with
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (PostgreSQL-only).

This is a stopgap until Alembic migrations land (see README roadmap).
SQLite (test harnesses) always builds a fresh schema via create_all, so the
migrator is a no-op there.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# (table, column, DDL type clause) — append new production columns here.
_NEW_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("users", "status", "VARCHAR(16) DEFAULT 'active'"),
    ("users", "password_hash", "VARCHAR(128)"),
    ("products", "trust_reason", "TEXT"),
)


def upgrade_schema(engine: Engine) -> None:
    """Add any Phase 7 columns that are missing on a pre-existing PostgreSQL.

    Safe to call on every boot: each ALTER is guarded by IF NOT EXISTS, and
    non-PostgreSQL engines (SQLite in tests) are skipped entirely.
    """
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
