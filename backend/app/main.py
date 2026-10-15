"""
main.py
=======
FastAPI application entrypoint for CampusMart AI (Phase 2).

Startup sequence (see `lifespan` below):
    1. init_firebase()           - idempotent firebase_admin SDK initialization
    2. Base.metadata.create_all  - provision PostgreSQL tables (FAILS FAST if
                                   the DB is down - start it first with
                                   `docker compose up -d`)

Run from the /backend folder:
    python -m uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .auth import init_firebase
from .database import Base, engine
from .routers import admin, auth_routes, products, transactions, users
from .schema_upgrade import upgrade_schema
from .storage import UPLOAD_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern replacement for the deprecated `@app.on_event("startup")` hook.

    Runs once when the server boots. Any exception raised here ABORTS startup:
    a backend without Firebase auth or a reachable database is unusable, so
    failing loudly at boot beats failing on the first user request.
    """
    # 1. Firebase Admin SDK (idempotent; logs a warning if the key is absent)
    #    so auth is ready before the first request arrives.
    init_firebase()

    # 2. Create tables for every model registered on Base.metadata
    #    (app/__init__.py imports models, so they are registered by now).
    #    DEV ONLY: `create_all` is not a migration tool - production must use
    #    Alembic so schema changes become versioned and reversible.
    Base.metadata.create_all(bind=engine)

    # 3. Phase 7 live-DB upgrade: add columns (users.status, users.password_hash,
    #    products.trust_reason) to tables that were created BEFORE Phase 7.
    #    Idempotent PostgreSQL ALTERs; no-op on SQLite (fresh test schemas).
    upgrade_schema(engine)

    yield

    # Shutdown: close all pooled DB connections cleanly.
    engine.dispose()


app = FastAPI(
    title="CampusMart AI API",           # required by spec
    description="Student-centric circular e-commerce platform API.",
    version="0.3.0",
    lifespan=lifespan,
)

# -----------------------------------------------------------------------------
# CORS - local Flutter testing AND production web clients (Vercel)
# -----------------------------------------------------------------------------
# Flutter clients (web/desktop debug builds) run on a different origin than
# the API, so browsers enforce the same-origin policy unless the server opts
# out via these headers. Native mobile builds are NOT subject to CORS at all.
#   * Default "*" accepts any origin - covers every Vercel preview domain
#     (https://<project>-<hash>.vercel.app) without enumerating them.
#   * Pin exact origins via CORS_ORIGINS (comma-separated) before handing the
#     API to third parties, e.g.:
#         CORS_ORIGINS=https://campusmart.vercel.app,https://app.example.com
#   * allow_credentials stays False: the API uses `Authorization: Bearer`
#     headers, not cookies, and the CORS spec forbids combining
#     `Access-Control-Allow-Credentials: true` with a "*" origin.
_cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Local image uploads (Phase 6) - served back when Cloudinary is unconfigured
# -----------------------------------------------------------------------------
# storage.py writes fallback files into /backend/uploads; mounting StaticFiles
# here makes them reachable at GET /uploads/<filename>. No-op-safe: the folder
# is created on demand. Cloudinary URLs never touch this mount.
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# -----------------------------------------------------------------------------
# Routers (Phase 2, Task 3)
# -----------------------------------------------------------------------------
app.include_router(users.router)        # /users/ , /users/{firebase_uid}
app.include_router(products.router)     # /products/ , /products/upload-image/
app.include_router(auth_routes.router)  # /auth/register , /auth/login (Phase 7)
app.include_router(transactions.router) # /products/{id}/purchase , /transactions/my
app.include_router(admin.router)        # /admin/* master control (Phase 7)


@app.get("/", tags=["health"])
def read_root() -> dict:
    """Liveness probe - confirms the API process is up and serving requests."""
    return {"status": "CampusMart API is running"}
