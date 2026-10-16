# CampusMart AI — Internal Session Context (LOCK FILE)
> Self-facing working notes for AI/developer sessions. NOT client-facing —
> the client handover doc is `README.md`.
> LAST UPDATED: end of production polish round (7 tasks: branding/logo,
> octet-stream image-upload fix, Discover/Detail/Sell/Profile overhaul,
> pytest gate, push + APK rebuild), 2026-10-15.

## Project identity
- Student circular e-commerce: FastAPI + PostgreSQL + LangGraph AI backend,
  Flutter mobile/web client.
- Engineer attribution: **Aditya Jadhav | Infinity Crew**.
- Working dir: `D:\Career_and_Life_Goals\Projects\p-20\campusmart_ai`
- **Git repo**, branch `main`, remote `origin` =
  `https://github.com/AdityaJadhav9881/main-campus-mart.git`
  (`git push origin main` → Render Blueprint auto-deploys; verified live
  2026-10-15, openapi.json serves the new schema).
- **App display name is exactly `Campus Mart Ai`** (spaces, capital M and A,
  lowercase i) — Android label, iOS CFBundleDisplayName, web title/manifest,
  in-app AppBars/header, widget test assertion. Do not "fix" it to CampusMart.
- Release APK lives at repo root `campusmart-ai.apk` and is **gitignored**
  (`.gitignore`: `campusmart-ai.apk`, `*.apk`).

## Environment quirks (this machine)
- Windows/PowerShell. **Docker NOT installed** → live Postgres untestable
  here; all backend verification uses in-memory SQLite harnesses.
- Flutter at `C:\flutter\bin` (NOT on PATH): prefix every flutter command
  with `$env:PATH = "C:\flutter\bin;$env:PATH"`.
- Flutter 3.24.5 / Dart 3.5.4 → use `withOpacity`, NOT `withValues`.
- Python 3.13 on PATH. Deps installed globally (cloudinary, python-multipart,
  PyJWT, bcrypt added Phases 6-7; **pytest 9.1.1 + Pillow 11.3 added polish
  round**; pytest was absent before — `pip install pytest` if it goes missing).
- **PowerShell trap**: `$env:FOO = ""` *deletes* the variable rather than
  setting it empty. The legacy `test_*.py` harnesses therefore must NOT be
  launched with `$env:CLOUDINARY_*=""`; use the `runpy` one-liner in
  "Run & verify" (sets `os.environ.update({...: ''})` inside Python).
- **Gradle lock trap**: a stale daemon pins `frontend\build`, `flutter clean`
  then fails with `AccessDeniedException` on
  `build\app\intermediates\...\merged.dir\values`. Fix:
  `frontend\android\gradlew.bat --stop`, then
  `Remove-Item -Recurse -Force frontend\build`, then rebuild.
- aapt for APK inspection:
  `%LOCALAPPDATA%\Android\Sdk\build-tools\33.0.1\aapt.exe dump badging`.
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
| 8 | Production polish: custom logo + rename "Campus Mart Ai", Android `application/octet-stream` upload fix, Discover/Detail/Sell/Profile UI overhaul, wishlist + client recommendation engine, pytest suite, push to origin/main + APK rebuild | ✅ 2026-10-15 |
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
- **Image-upload MIME (Phase 8 fix)**: Android `image_picker` declares
  `application/octet-stream`/none, so the old allow-list rejected real photos
  with 400. `storage.sniff_image_mime()` now recovers the type — magic bytes
  first (JPEG `\xff\xd8\xff`, PNG `\x89PNG`, GIF `GIF87a/89a`, WebP
  `RIFF....WEBP`), then filename extension (`.jpg/.jpeg/.png/.webp/.gif/
  .heic/.heif`) — and only a still-unclassifiable payload gets 400.
  `_validated_image_bytes` → `(bytes, mime, ext)`; `save_upload` →
  `(url, mime)`; router logs the RESOLVED type. Flutter also sends an
  explicit `MediaType` (adds `http_parser` dep). Never narrow the allow-list
  back — that is the bug.
  Caveat: `.heic` is accepted server-side but Flutter's `Image.network`
  cannot decode HEIC (fallback icon shows); Android/web pickers hand us
  JPEG/PNG, so this is a non-path today.
- **`seller_name`**: `Product.seller_name` property (mirrors
  `seller_trust_score`) + `ProductRead.seller_name` (nullable) so the detail
  screen can show who is selling. Feed is still the only read path.
- **`DELETE /products/{product_id}`** (Phase 8, owner-only): 204 on success;
  404 missing, 403 non-owner/blocked, 400 sold or FK RESTRICT (purchase
  history is append-only). **No trust penalty** — the −0.8 stays reserved for
  admin moderation deletes. Flutter Profile "My Listings" owns the call.
- **No backend "Recommendation Agent"** — ranking lives client-side in
  `frontend/lib/services/recommendations.dart` (`RecommendationEngine`:
  score = 0.55·value + 0.40·trust + 0.05·fresh, `reasonFor()` for badges).
  Do not add a server agent for this without a spec.
- **Trust scale is 0–5.0 everywhere** (backend caps at 5.0). The old UI
  printed `/10` and fed `score/10` to a 0–1 progress bar —
  `trust_score_meter.dart` now does `/5.0` + `(score/5.0).clamp(0,1)` +
  `trustTierLabel`/`trustTierColor`.
- **Hero tags must be unique per route**: no `Hero` inside the rail tiles,
  similar-listings tiles, or profile tiles (only the Discover grid tile →
  detail image animates). Adding one in a list breaks navigation.
- **Wishlist**: `WishlistProvider` (shared_preferences key
  `wishlist_product_ids`) is the single source of truth for heart state
  across Discover rail / grid / detail / Profile "Saved" tab.
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
python -m pytest -q                 # PRIMARY gate: 24 checks (upload MIME sniff,
                                    #   seller_name, owner delete). conftest.py
                                    #   forces dev env BEFORE app import — no .env
                                    #   edits, safe against the production .env.
python test_full_production.py      # Phase 7 E2E: auth/admin/purchase/agents (54 checks)
python test_ai_pipeline.py          # Phase 3 AI E2E (needs live Postgres! docker)
python test_phase4_auth_trust.py    # 13/13 — auth + trust score fields
python test_image_upload.py         # 15/15 — upload endpoint + fallback + validation
cd frontend
flutter analyze                     # must be 0 issues
flutter test                        # 1/1 smoke (AuthScreen gate)
flutter build web --release         # web-readiness gate

# Release APK with the PRODUCTION API baked in, then overwrite the root artifact
# (campusmart-ai.apk is gitignored — the GitHub release asset carries it):
flutter build apk --release --dart-define=API_BASE_URL=https://campusmart-api-zia4.onrender.com
Copy-Item -Force build\app\outputs\flutter-apk\app-release.apk ..\campusmart-ai.apk

# Verify the binary (label must be 'Campus Mart Ai'; grep libapp.so for the API host):
& "$env:LOCALAPPDATA\Android\Sdk\build-tools\33.0.1\aapt.exe" dump badging ..\campusmart-ai.apk

# Publish the APK (gh CLI already authed as AdityaJadhav9881):
cd ..
gh release create v1.1.0 campusmart-ai.apk --title "Campus Mart Ai v1.1.0" --notes "..."
```

## File map (highest-value files)
- `backend/app/auth.py` — JWT create/decode, bcrypt, dual-path verify_firebase_token,
  require_admin_access (ADMIN_REQUIRE_AUTH gate)
- `backend/app/routers/auth_routes.py` — POST /auth/register|login
- `backend/app/routers/admin.py` — full /admin/* control plane
- `backend/app/routers/transactions.py` — purchase + /transactions/my
- `backend/app/routers/products.py` — blocked-403 guards, trust_reason persist,
  upload-image (logs resolved MIME), owner-only DELETE /{product_id}
- `backend/app/ai/orchestrator.py` — AGENT_FLAGS runtime gates
- `backend/app/schema_upgrade.py` — live-PG ADD COLUMN IF NOT EXISTS stopgap
- `backend/app/storage.py` — Cloudinary + local fallback upload pipeline;
  `sniff_image_mime()` + `_validated_image_bytes()` (octet-stream fix)
- `backend/conftest.py` — pytest bootstrap: forces AUTH_DEV_BYPASS=true, blanks
  CLOUDINARY_*/DATABASE_URL before `app.*` import. NEVER imported by uvicorn.
- `backend/test_upload_mime_sniffing.py` — the pytest suite (24 checks)
- `backend/seed_db.py` — 3 sellers (password123), 8 listings
- `frontend/assets/logo.png` — 512px brand mark (source: root
  `WhatsApp Image 2026-10-15 at 12.09.42 PM.jpeg`); mirrored into
  `android/app/src/main/res/mipmap-*/ic_launcher.png` and `web/favicon.png`,
  `web/icons/*`
- `frontend/lib/services/recommendations.dart` — client-side
  `RecommendationEngine` (For You rail, sort, deal reasons)
- `frontend/lib/services/ai_price_estimate.dart` — client mirror of the price
  agent for the Sell-screen live estimate banner
- `frontend/lib/providers/wishlist_provider.dart` — persisted heart state
- `frontend/lib/widgets/trust_score_meter.dart` — 0–5.0 trust display
- `frontend/lib/screens/feed_screen.dart` — Discover: logo AppBar, search,
  AI rail, dynamic chips, sort sheet, product grid (ratio 0.60)
- `frontend/lib/screens/product_detail_screen.dart` — glass back/heart,
  AI inspection report, seller trust, similar listings, pinned bottom buy bar
- `frontend/lib/screens/create_listing_screen.dart` — camera/gallery sheet,
  image preview, hidden URL field, AI estimate banner, bottom-bar padding
- `frontend/lib/screens/profile_screen.dart` — 3-tab activity (My Listings
  w/ delete, Purchased, Saved), Log Out, no SESSION & API box
- `frontend/lib/widgets/product_card.dart` — deal badge, wishlist heart, trust pill
- `frontend/lib/screens/auth_screen.dart` — campus login/signup (.edu/.ac.in badge)
- `frontend/lib/providers/auth_provider.dart` — JWT session + shared_preferences
- `frontend/lib/services/api_service.dart` — useMockAuth=false, login/register/
  purchase, explicit upload MediaType, deleteProduct, fetchMyTransactions

## Backlog (next session likely asks for these)
1. Render secrets still to set on the dashboard: `JWT_SECRET_KEY`, and
   optionally `ADMIN_REQUIRE_AUTH=true` + `ADMIN_EMAILS`. Push → auto-deploy
   itself is VERIFIED working (openapi.json shows Phase 8 routes).
2. Optional real Firebase auth swap (flutterfire configure) — campus JWT is
   already live; Firebase remains an alternate verified path.
3. Alembic for schema migrations; live-Postgres runs of all harnesses.
4. Checkout/payment integration (purchase is instant-reserve today).
5. React Admin Dashboard build against /admin/* contract (open by default).
6. Play Store hygiene: bump `versionCode`/`versionName` in
   `frontend/android/app/build.gradle` before every store upload
   (currently 1 / 1.0.0); store listing screenshots from the new branding.
7. HEIC → JPEG re-encode on upload if iOS HEIC photos ever become common
   (Flutter cannot decode HEIC; server accepts it today).
8. Keep cutting GitHub releases for the APK: tag `v<semver>` on `main`,
   `gh release create <tag> campusmart-ai.apk --title "Campus Mart Ai <tag>"`.
