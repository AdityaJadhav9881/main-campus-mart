# CampusMart AI

**An AI-powered circular marketplace for campus life** — students list second-hand items, and a LangGraph AI pipeline instantly classifies the listing, suggests a fair resale price, and screens it for fraud before it ever hits the feed.

*Engineer Attribution: **Aditya Jadhav | Infinity Crew***

---

## System Architecture

```
┌────────────────────┐     Bearer token      ┌───────────────────────────┐
│  Flutter Client    │ ────────────────────► │  FastAPI Gateway          │
│  (Android / iOS /  │  POST /products/      │  • Firebase Auth verify   │
│   Web)             │  GET  /products/      │  • SQLAlchemy ORM         │
│  • Provider state  │  POST /products/      │  • Cloudinary uploads     │
│  • image_picker →  │       upload-image/   └─────────────┬─────────────┘
│    cloud upload    │                       │             │
└────────────────────┘                       │   ┌─────────▼──────────┐
                                             │   │ LangGraph          │
                                             │   │ Orchestrator       │
                                             │   │ 1. Listing Intel.  │
                                             │   │ 2. Price Predict.  │
                                             │   │ 3. Trust & Fraud   │
                                             │   └─────────┬──────────┘
                                             │             │
                                   ┌─────────▼─────────────▼─────────┐
                                   │  PostgreSQL 15  (+ Cloudinary)  │
                                   │  users · products · transactions│
                                   │  listing photos (CDN)           │
                                   └─────────────────────────────────┘
```

| Component | Function | Tech Stack |
|---|---|---|
| **Flutter Frontend** | Discovery feed, AI-assisted sell flow, product detail, campus-trust profile; cloud photo picker | Flutter 3.24 (Dart 3.5), Provider, http, image_picker, firebase_auth |
| **FastAPI Gateway** | REST API, Firebase token verification, multipart image upload, CORS-enabled for web clients | Python 3.11+, FastAPI, SQLAlchemy 2, firebase-admin, Cloudinary SDK |
| **PostgreSQL** | Durable storage for users, listings (UUID PKs), purchase history; managed in cloud | PostgreSQL 15 (Docker locally / Render Postgres in cloud) |
| **LangGraph Orchestrator** | Runs before every insert: category extraction → fair-price suggestion → fraud/abuse flagging (fail-closed) | LangGraph, rule-based agents (scikit-learn/YOLO swap points marked) |

### API Surface

| Method & Path | Auth | Purpose |
|---|---|---|
| `POST /users/` | Bearer | Idempotent create-or-return profile (trust score starts at 5.0) |
| `GET /users/{uid}` | Public | Profile + public trust score |
| `POST /products/` | Bearer | Create listing — AI pipeline assigns category, suggested price, status |
| `GET /products/` | Public | Active listings feed (flagged items hidden), includes `seller_trust_score` |
| `POST /products/upload-image/` | Bearer | Upload photo → Cloudinary CDN URL (local `/uploads` fallback in dev) |
| `GET /` | Public | Health probe |

---

## Repository Layout

```
campusmart_ai/
├── docker-compose.yml        # PostgreSQL 15 for local development
├── render.yaml               # Render.com blueprint (Postgres + API service)
├── Procfile                  # Heroku-style alternate process declaration
├── SESSION_CONTEXT.md        # Internal engineering lock file (not client-facing)
├── backend/
│   ├── requirements.txt
│   ├── seed_db.py            # Demo data: 3 sellers, 8 listings
│   ├── test_ai_pipeline.py   # Phase 3 E2E harness (needs live Postgres)
│   ├── test_phase4_auth_trust.py  # Auth bypass + trust-score harness
│   ├── test_image_upload.py  # Upload endpoint harness
│   └── app/
│       ├── main.py           # Lifespan, CORS, /uploads mount, routers
│       ├── database.py       # DATABASE_URL (cloud) or POSTGRES_* (local)
│       ├── auth.py           # Firebase verify + AUTH_DEV_BYPASS dev mode
│       ├── models.py         # User / Product / Transaction (UUID PKs)
│       ├── schemas.py        # Pydantic request/response models
│       ├── storage.py        # Cloudinary upload + safe local fallback
│       ├── routers/          # users.py, products.py
│       └── ai/               # LangGraph: state, listing, price, trust, orchestrator
└── frontend/                 # Flutter app (Android / iOS / Web)
    └── lib/
        ├── main.dart         # Providers + 3-tab shell
        ├── services/api_service.dart
        ├── providers/        # auth_provider, product_provider
        ├── screens/          # feed, create_listing, product_detail, profile
        └── widgets/          # theme, product_card, category_icon, trust meter
```

---

## Quickstart

### Prerequisites
- Docker (for local PostgreSQL)
- Python 3.10+
- Flutter 3.24+

### 1. Start PostgreSQL

```bash
docker compose up -d
docker compose ps        # verify healthy
```

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Configure `backend/.env` (copy the defaults already present):
- Dev ships with `AUTH_DEV_BYPASS=true` so the app runs **without any Firebase project** (mock tokens only; real tokens are still fully verified).
- Optionally set `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` — without them, uploads save to `backend/uploads/` and are served at `/uploads/`.

```bash
# Seed demo data (3 student sellers, 8 campus listings). Default wipes first;
# use --append to add idempotently.
python seed_db.py

# Launch the API
python -m uvicorn app.main:app --reload
# → http://127.0.0.1:8000  (Swagger docs at /docs)
```

### 3. Frontend

```bash
cd frontend
flutter pub get

flutter run                 # Android emulator / device / iOS simulator
flutter run -d chrome       # Web
```

Base-URL behavior: Android emulator uses `10.0.2.2:8000`; everything else uses `127.0.0.1:8000`. For a deployed backend:

```bash
flutter build web --release --dart-define=API_BASE_URL=https://campusmart-api-zia4.onrender.com
```

---

## Verification Suite

All three backend harnesses use an **in-memory SQLite** override and skip the FastAPI lifespan, so they run **without Docker or Cloudinary**. Each prints `PASS/FAIL` lines and exits non-zero on failure.

```bash
cd backend

# Phase 3 — LangGraph pipeline E2E (category, pricing, fraud flagging).
# NOTE: this one uses the real PostgreSQL from docker compose up -d.
python test_ai_pipeline.py

# Phase 4 — dev-bypass auth + seller trust-score exposure (13 checks).
python test_phase4_auth_trust.py

# Phase 6 — image upload endpoint: PNG/JPEG happy path, MIME/size validation,
# auth required, bytes served back from /uploads (15 checks).
python test_image_upload.py
```

```bash
cd frontend

flutter analyze              # must report "No issues found"
flutter test                 # app-shell smoke test
flutter build web --release  # production web build sanity check
flutter build apk --release  # Android release APK (see "Building the Android APK")
```

---

## Deploying to Render (Production)

1. Push this repository to GitHub (`main` branch).
2. On [render.com](https://render.com): **New → Blueprint** → connect the repo. Render reads `render.yaml` and provisions:
   - `campusmart-db` — managed PostgreSQL
   - `campusmart-api` — FastAPI service (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
3. When prompted for `sync: false` secrets, paste:
   - `FIREBASE_SERVICE_ACCOUNT_KEY` — Firebase Console → Project settings → Service accounts → Generate new private key
   - `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` — Cloudinary dashboard → API Keys
4. Wait for the deploy; verify `https://campusmart-api-zia4.onrender.com/` returns `{"status": "CampusMart API is running"}`.
5. Seed once against the managed database: `DATABASE_URL=<render-db-url> python seed_db.py` (or use any Postgres client).
6. Harden CORS: set `CORS_ORIGINS=https://your-app.vercel.app` on the service.
7. Deploy the Flutter web build to Vercel with `--dart-define=API_BASE_URL=https://campusmart-api-zia4.onrender.com`.

> **Security notes:** `AUTH_DEV_BYPASS` is `false` in the Render blueprint by default — keep it that way. Render's disk is ephemeral, so the Cloudinary credentials are **required** in production (local-fallback uploads would vanish on redeploy).

---

## Building the Android APK (Release)

The release APK talks to the live server over HTTPS, so build it with the
production base URL baked in:

```bash
cd frontend
flutter build apk --release --dart-define=API_BASE_URL=https://campusmart-api-zia4.onrender.com
# → frontend/build/app/outputs/flutter-apk/app-release.apk
```

Distribution options: install directly (`adb install app-release.apk`), or
upload to Google Play. `--split-per-abi` produces smaller per-ABI APKs
(`app-arm64-v8a-release.apk`, etc.) if size matters.

**Release-build readiness checks (all verified in this repo):**

| Check | Status |
|---|---|
| `<uses-permission android:name="android.permission.INTERNET"/>` in `src/main/AndroidManifest.xml` | ✅ present — without it the signed APK cannot reach Render/Cloudinary (debug/profile manifests add it for hot reload only) |
| `image_picker` gallery flow | ✅ gallery-only pick (no `CAMERA` permission, no `FileProvider` needed); plugin auto-merges its own manifest entries |
| Signing config | ⚠️ `build.gradle` signs releases with **debug keys** (`signingConfigs.debug`) — fine for demos/side-loading; add a real keystore before Play Store submission |
| Android SDK levels | ✅ `minSdk = 23` (firebase_auth requirement; Flutter default 21 fails the release manifest merger), `compileSdk = 35` |
| Unreachable-server handling | ✅ 15s timeout → friendly `ApiException` → feed error state with **Refresh Feed** action; mock session stays usable on the Profile tab (retry button) |
| `AUTH_DEV_BYPASS` mismatch (client mock token vs. prod backend) | ✅ backend rejects with 401, message surfaces in the Profile session card — no crash |
| Broken image URLs | ✅ every `Image` uses `errorBuilder` → category fallback icon |

---

## Go-Live Checklist (Zero Coding Required)

Run top-to-bottom when shipping to production:

1. **Git** — `git init`, commit, and push to GitHub (`main`). *(This repo is not a git repo yet.)*
2. **Render** — New → Blueprint → select the repo; Render provisions `campusmart-db` + `campusmart-api` from `render.yaml`.
3. **Secrets** — paste when prompted (`sync: false`): `FIREBASE_SERVICE_ACCOUNT_KEY`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`.
4. **Cloudinary** — dashboard → API Keys; confirm uploads land on the CDN (Render disks are ephemeral, so this is mandatory, not optional).
5. **Health check** — `GET https://campusmart-api-zia4.onrender.com/` → `{"status": "CampusMart API is running"}`.
6. **Seed** — `DATABASE_URL=<render-db-url> python seed_db.py` → feed shows the 8 demo listings.
7. **Security** — confirm `AUTH_DEV_BYPASS=false` on the service (render.yaml default); real Firebase tokens only.
8. **CORS** — pin `CORS_ORIGINS` to your Vercel domain once the web app is deployed.
9. **Clients** — build web (`flutter build web --release --dart-define=API_BASE_URL=...`) and APK (command above) against the live URL.
10. **Smoke test** — feed loads, Sell flow uploads a photo to Cloudinary, AI snackbar shows category + suggested price.

---

## What the AI Pipeline Does

Every `POST /products/` runs the LangGraph orchestrator **before** any database write:

1. **Listing Intelligence** — classifies the item (`Academic Material` / `Electronics`) from the title. *Swap point: YOLOv8 + embedding classifier.*
2. **Price Prediction** — fair-value estimate from the condition table (base × {Like New 0.80, Good 0.60, Fair 0.40, Poor 0.20}). *Swap point: trained scikit-learn regressor.*
3. **Trust & Fraud Detection** — scans title/description for scam patterns; flagged listings get `status='flagged'` and never appear in the public feed. **Fail-closed:** a pipeline error rejects the listing with HTTP 500 rather than publishing it un-analyzed.

Seller **trust scores** (neutral start 5.0, range 0–10) are exposed on every feed item so buyers can judge credibility at a glance.

---

## Seed Data

`python seed_db.py` creates three demo sellers — **Aditya Jadhav (4.9)**, **Meera Iyer (4.2)**, **Rohan Deshmukh (3.1)** — and eight listings across *Academic Material*, *Lab Gear & Instruments*, and *Electronics* (textbooks, a mini drafter, a multimeter, a Casio calculator, an ESP32 bundle, an Arduino kit, and a notes bundle), each with realistic descriptions, Unsplash placeholder photos, and AI-consistent suggested prices.

All three seeded students can log in immediately on the live app with
**email + `password123`** (e.g. `aditya.jadhav@campus.edu` / `password123`) —
fresh registration via the app's Sign Up tab works the same way. Live
production database: Neon PostgreSQL (ap-southeast-1), seeded 2026-10-15.

---

## Roadmap

- [x] Phases 1–6: core marketplace, AI pipeline, Flutter client, cloud uploads, production configs
- [x] Root handover README (this document)
- [x] Android release-APK readiness (INTERNET permission, error handling) + Go-Live checklist
- [ ] Live Firebase authentication (`flutterfire configure`; dev-bypass disabled)
- [ ] Alembic migrations replacing `create_all`
- [ ] Checkout / transactions flow
- [ ] Real ML models at the marked swap points (YOLO classifier, price regressor, trust model)

---

<div align="center">

**CampusMart AI** · Built by [Aditya Jadhav](https://github.com) | Infinity Crew

*Reuse. Reduce. Recycle — on campus.*

</div>
