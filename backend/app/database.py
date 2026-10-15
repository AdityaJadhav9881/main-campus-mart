"""
database.py
===========
SQLAlchemy engine / session factory for CampusMart AI.

Responsibilities
----------------
1. Read PostgreSQL credentials declared in the root `docker-compose.yml`
   (loaded from `/backend/.env` via python-dotenv, with safe fallbacks that
   match the compose file exactly).
2. Build a pooled SQLAlchemy engine that talks to PostgreSQL through psycopg2.
3. Expose:
      - `Base`         : declarative base class every ORM model inherits from.
      - `SessionLocal` : configured session factory used to open transactions.
      - `get_db`       : FastAPI dependency that yields a session and ALWAYS
                         closes it when the request finishes (prevents leaks).

Environment variables (defaults == docker-compose.yml):
      POSTGRES_USER       -> admin
      POSTGRES_PASSWORD   -> admin_password
      POSTGRES_HOST       -> localhost
      POSTGRES_PORT       -> 5432
      POSTGRES_DB         -> campusmart

Run/verify from `/backend`:
      python -m app.database        # prints the PostgreSQL server version
      uvicorn app.main:app --reload # (Phase 2 entrypoint)
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker

# -----------------------------------------------------------------------------
# 1. Environment loading
# -----------------------------------------------------------------------------
# Resolve the /backend folder (this file lives in /backend/app, so climb two
# levels) and load `.env` from there. This makes the module independent of the
# current working directory - secrets resolve no matter where uvicorn is run.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

# Credential variables. Fallback values mirror docker-compose.yml exactly, so
# the stack boots even before a .env file has been created.
DB_USER: str = os.getenv("POSTGRES_USER", "admin")
DB_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "admin_password")
DB_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME: str = os.getenv("POSTGRES_DB", "campusmart")

# -----------------------------------------------------------------------------
# 2. Engine (connection factory + pool)
# -----------------------------------------------------------------------------
# Cloud hosts (Render/Heroku) inject a single DATABASE_URL instead of the
# discrete POSTGRES_* variables. Prefer it when present and normalize the
# legacy "postgres://" scheme to SQLAlchemy's "postgresql://".
_EXTERNAL_DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()

if _EXTERNAL_DATABASE_URL:
    if _EXTERNAL_DATABASE_URL.startswith("postgres://"):
        _EXTERNAL_DATABASE_URL = _EXTERNAL_DATABASE_URL.replace(
            "postgres://", "postgresql://", 1
        )
    # SQLAlchemy 2.x maps bare "postgresql://" to the psycopg (v3) dialect,
    # but this project ships psycopg2-binary. Pin the driver explicitly when
    # the URL doesn't already carry one (e.g. Neon's copied connection string).
    if _EXTERNAL_DATABASE_URL.startswith("postgresql://"):
        _EXTERNAL_DATABASE_URL = _EXTERNAL_DATABASE_URL.replace(
            "postgresql://", "postgresql+psycopg2://", 1
        )
    DATABASE_URL = _EXTERNAL_DATABASE_URL
else:
    # URL.create() is used instead of an f-string so special characters in
    # the password (e.g. '@', ':', '/') are URL-escaped correctly and cannot
    # break the connection string or enable injection.
    DATABASE_URL = URL.create(
        drivername="postgresql+psycopg2",   # SQLAlchemy dialect + DBAPI driver
        username=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )

engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",  # SQL statement logging
    # --- Pooling / resilience tuning -------------------------------------
    pool_pre_ping=True,   # Validate connections BEFORE reuse (survives PG restarts)
    pool_size=5,          # Steady-state open connections per worker process
    max_overflow=10,      # Burst capacity beyond pool_size under load
    pool_recycle=1800,    # Recycle connections every 30 min (avoids stale sockets)
)

# -----------------------------------------------------------------------------
# 3. Session factory
# -----------------------------------------------------------------------------
# autocommit=False -> every transaction must be explicitly committed (prevents
# accidental partial writes).  autoflush=False   -> no surprise SQL flushes;
# the app decides when pending changes hit the database.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

# -----------------------------------------------------------------------------
# 4. Declarative base for all ORM models (see app/models.py)
# -----------------------------------------------------------------------------
Base = declarative_base()


# -----------------------------------------------------------------------------
# 5. FastAPI dependency: one session per request, closed deterministically
# -----------------------------------------------------------------------------
def get_db():
    """Yield a scoped database session and guarantee cleanup.

    Usage in Phase 2 endpoints:
        from fastapi import Depends
        from sqlalchemy.orm import Session
        from .database import get_db

        @app.get("/products")
        def list_products(db: Session = Depends(get_db)):
            ...

    The `finally` block runs even if the endpoint raises, so connections are
    never leaked back into a broken state.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------------------------------------------------------
# 6. Smoke test: `python -m app.database` from /backend verifies connectivity
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version()")).scalar()
    print(f"[OK] Connected to {DB_NAME} @ {DB_HOST}:{DB_PORT}")
    print(f"     {version}")
