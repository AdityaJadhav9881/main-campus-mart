"""
conftest.py - pytest bootstrap for the CampusMart backend suite.

Why this file exists
--------------------
The repository ships with a *production* `/backend/.env` (AUTH_DEV_BYPASS off,
Cloudinary credentials present, live DATABASE_URL). The verification harnesses
need the opposite: local-dev mock-token auth, the local `/uploads` fallback,
and no live database. Forcing that here lets a plain `pytest` run offline
without editing or weakening the production `.env`.

Order of operations matters:
    1. Environment is patched HERE, before any `app.*` module is imported.
    2. `load_dotenv(..., override=False)` inside app/database.py, app/auth.py
       and app/storage.py then leaves these values untouched.

Nothing in this file is imported by the production server.
"""

import os

# Mock-token bypass on => the harnesses' `mock-*` Bearer tokens work without
# a Firebase project (production keeps AUTH_DEV_BYPASS=false in .env).
os.environ["AUTH_DEV_BYPASS"] = "true"

# Force the safe local-storage fallback so uploads land in /backend/uploads
# (and assertable extensions) instead of the real Cloudinary account.
os.environ["CLOUDINARY_CLOUD_NAME"] = ""
os.environ["CLOUDINARY_API_KEY"] = ""
os.environ["CLOUDINARY_API_SECRET"] = ""

# Never let a test open a socket to the live Neon database; fall back to the
# localhost POSTGRES_* defaults (which nothing under pytest connects to).
os.environ["DATABASE_URL"] = ""

# Admin routes stay open (the React dashboard default) during tests.
os.environ["ADMIN_REQUIRE_AUTH"] = "false"
