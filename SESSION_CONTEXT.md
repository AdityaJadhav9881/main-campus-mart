# CampusMart AI — Internal Session Context (LOCK FILE)
> Self-facing working notes for AI/developer sessions. NOT client-facing —
> the client handover doc is `README.md`.
> LAST UPDATED: end of Phase 7 (live production auth + admin + purchase), 2026-10-15.

## Project identity
- Student circular e-commerce: FastAPI + PostgreSQL + LangGraph AI backend,
  Flutter mobile/web client.
- Engineer attribution: **Aditya Jadhav | Infinity Crew**.
- Working dir: `D:\Career_and_Life_Goals\Projects\p-20\campusmart_ai`
- NOT a git repo yet (Phase 6 deploy checklist expects a GitHub push first).

## Environment quirks (this machine)
- Windows/PowerShell. **Docker NOT installed** → live Postgres untestable
  here; all backend verification uses in-memory SQLite harnesses.
- Flutter at `C:\flutter\bin` (NOT on PATH): prefix every flutter command
  with `$env:PATH = "C:\flutter\bin;$env:PATH"`.
- Flutter 3.24.5 / Dart 3.5.4 → use `withOpacity`, NOT `withValues`.
- Python 3.13 on PATH. Deps installed globally (cloudinary, python-multipart,
  PyJWT, bcrypt added Phases 6-7).
- Known noise: symlink permission warning on `flutter pub add`/`flutter test`
  (Android builds only; exit code may be 1 despite success — read output).
  If `flutter test` fails on locked `build\unit_test_assets`, delete
  `frontend/build` and retry.

## Phase status
| Phase | Scope | Status |
|---|---|---|
| 1 | docker-compose Postgres, models (User/Product/Transaction, UUID PKs) | ✅ |
| 2 | FastAPI CRUD, Firebase auth layer, E2E harness | ✅ |
| 3 | LangGraph orchestrator (listing→price→trust), fail-closed on AI error | ✅ |
| 4 | Flutter app (feed/create/detail/profile), trust score fields, mock auth | ✅ |
| 5 | seed_db.py, image fallback UI, empty states, web build --release | ✅ |
| 6 | Cloudinary upload pipeline, upload-image endpoint, image_picker wiring, render.yaml/Procfile, CORS env, DATABASE_URL support | ✅ |
| 7 | Live production: campus JWT auth, admin control plane, purchase flow, mock removal | ✅ |
| — | Root `README.md` master handover doc | ✅ written 2026-10-15 |
| — | Real Firebase auth swap (`flutterfire configure`) | ⚠️ OPTIONAL — campus JWT is live; Firebase path stays active as alternate |
| — | Alembic migrations | ❌ BACKLOG (schema_upgrade.py stopgap handles Phase 7 columns) |
| — | Execute live deploy + seed against Render Postgres | ❌ BACKLOG |

## Key architectural decisions (do not regress)
- **Auth (Phase 7)**: Dual-path Bearer — local JWT (POST /auth/register|login,
  bcrypt + PyJWT HS256, `JWT_SECRET_KEY` env) checked FIRST in
  verify_firebase_token, then Firebase ID token. `mock-*` bypass unchanged
  (AUTH_DEV_BYPASS env, off in prod). Flutter `useMockAuth` is const false;
  JWT persisted in shared_preferences (`jwt_token`, `user_json`).
- **Local accounts**: `firebase_uid = "local-<hex>"` keeps the UNIQUE identity
  column working for both Firebase and email/password students.
- **Blocked users**: `users.status` ('active'|'blocked', CheckConstraint);
  403 on create-listing, upload-image, purchase; 403 on login when blocked.
- **AI owns** category, suggested_price, status (flagged if fraud). Client
  `category` field is deprecated/ignored. Pricing table:
  base 100 × {new 1.0, like new 0.8, good 0.6, fair 0.4, poor 0.2}.
- **trust_reason**: persisted on Product only when flagged; cleared on admin
  approve. Public feed never returns it for clean items.
- **Agent runtime flags**: orchestrator AGENT_KEYS dict; disabled agents are
  gated out with safe defaults (Uncategorized / None / trust_flag=False).
  Admin PATCH /admin/ai-agents/{key} toggles live.
- **Admin auth**: OPTIONAL by default (ADMIN_REQUIRE_AUTH=false) so the React
  dashboard works browser-direct; set true + ADMIN_EMAILS to lock down.
- **Fail-closed**: AI pipeline error → 500, listing NOT created.
- **No GET /products/{id}** — detail screen gets the Product object from the
  feed by design.
- **Purchase**: POST /products/{id}/purchase — Transaction(status='completed'),
  product→'sold', seller trust +0.1 (cap 5.0). Double-buy/own-listing → 400.
- **Admin trust math**: approve +0.2 (cap 5.0), delete −0.8 (floor 0.0).
- **Images**: Cloudinary when `CLOUDINARY_*` set; else local `backend/uploads/`
  served at `/uploads/<uuid>`. Render disks are ephemeral → Cloudinary REQUIRED
  in prod.
- **DB**: `app/database.py` prefers cloud `DATABASE_URL` env; tables via
  lifespan create_all + `schema_upgrade.py` (PostgreSQL ADD COLUMN IF NOT
  EXISTS for Phase 7 columns on pre-existing DBs).
- **CORS**: `CORS_ORIGINS` env, comma-separated, default `*`.
- **Flutter base URL**: `--dart-define=API_BASE_URL=https://...` override,
  else web/localhost → 127.0.0.1:8000, Android emulator → 10.0.2.2:8000.
- **Seed**: seed_db.py users have bcrypt password_hash for `password123` +
  status='active' (immediate test login: aditya.jadhav@campus.edu / etc.).
- Design language: dark "deep void", cyan accent 0xFF22D3EE, hairline borders.

## Run & verify commands
```powershell
# Backend (needs Postgres via docker compose up -d, or Render DATABASE_URL):
cd backend; python -m uvicorn app.main:app --reload

# Frontend:
cd frontend; $env:PATH = "C:\flutter\bin;$env:PATH"; flutter run  # or -d chrome

# Seed (default wipes; --append is idempotent; demo password123):
cd backend; python seed_db.py

# Verification harnesses (NO Docker needed — in-memory SQLite):
cd backend
python test_full_production.py      # Phase 7 E2E: auth/admin/purchase/agents (54 checks)
python test_ai_pipeline.py          # Phase 3 AI E2E (needs live Postgres! docker)
python test_phase4_auth_trust.py    # 13/13 — auth + trust score fields
python test_image_upload.py         # 15/15 — upload endpoint + fallback + validation
cd frontend
flutter analyze                     # must be 0 issues
flutter test                        # 1/1 smoke (AuthScreen gate)
flutter build web --release         # web-readiness gate
flutter build apk --release         # release APK
```

## File map (highest-value files)
- `backend/app/auth.py` — JWT create/decode, bcrypt, dual-path verify_firebase_token,
  require_admin_access (ADMIN_REQUIRE_AUTH gate)
- `backend/app/routers/auth_routes.py` — POST /auth/register|login
- `backend/app/routers/admin.py` — full /admin/* control plane
- `backend/app/routers/transactions.py` — purchase + /transactions/my
- `backend/app/routers/products.py` — blocked-403 guards, trust_reason persist
- `backend/app/ai/orchestrator.py` — AGENT_FLAGS runtime gates
- `backend/app/schema_upgrade.py` — live-PG ADD COLUMN IF NOT EXISTS stopgap
- `backend/app/storage.py` — Cloudinary + local fallback upload pipeline
- `backend/seed_db.py` — 3 sellers (password123), 8 listings
- `frontend/lib/screens/auth_screen.dart` — campus login/signup (.edu/.ac.in badge)
- `frontend/lib/providers/auth_provider.dart` — JWT session + shared_preferences
- `frontend/lib/screens/product_detail_screen.dart` — Buy Now → purchase
- `frontend/lib/screens/profile_screen.dart` — real profile + my listings + logout
- `frontend/lib/services/api_service.dart` — useMockAuth=false, login/register/purchase

## Backlog (next session likely asks for these)
1. Execute Render deploy checklist (push → Blueprint → secrets → health check,
   set JWT_SECRET_KEY + optionally ADMIN_REQUIRE_AUTH=true/ADMIN_EMAILS).
2. Optional real Firebase auth swap (flutterfire configure) — campus JWT is
   already live; Firebase remains an alternate verified path.
3. Alembic for schema migrations; live-Postgres runs of all harnesses.
4. Checkout/payment integration (purchase is instant-reserve today).
5. React Admin Dashboard build against /admin/* contract (open by default).
