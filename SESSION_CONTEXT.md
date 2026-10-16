# CampusMart AI — Internal Session Context (LOCK FILE)
> Self-facing working notes for AI/developer sessions. NOT client-facing —
> the client handover doc is `README.md`.
> LAST UPDATED: 2026-10-16. Completed full production overhaul (Warm Paper aesthetic,
> Brevo transactional email & instant OTP fallback, Gemini 3.5 Flash Vision AI,
> 4-photo mandatory sell flow with zoomable lightbox, grounded Ask AI campus assistant,
> on-the-fly user creation, and INR currency conversion).

## Project identity
- Student circular e-commerce: FastAPI + PostgreSQL + LangGraph & Gemini Vision AI backend,
  Flutter mobile/web client.
- Platform Admin / Support: **CampusMart Admin (martaicampus@gmail.com)**.
- Working dir: `D:\Career_and_Life_Goals\Projects\p-20\campusmart_ai`
- **Git repo**, branch `main`, remote `origin` =
  `https://github.com/AdityaJadhav9881/main-campus-mart.git`
  (`git push origin main` → Render Blueprint auto-deploys; verified live
  2026-10-16, commit `581e1e2`).
- **Android launcher label is exactly `CampusMart`** (10 characters, single word)
  in `AndroidManifest.xml` to prevent home screen icon truncation.
- **In-app display name is `Campus Mart Ai`** with elegant serif styling across
  app headers and navigation.
- Release APK lives at repo root `campusmart-ai.apk` (49.2 MB) and is **gitignored**
  (`.gitignore`: `campusmart-ai.apk`, `*.apk`).

## Environment quirks (this machine)
- Windows/PowerShell. **Docker NOT installed** → live Postgres untestable
  here; all backend verification uses in-memory SQLite harnesses.
- Flutter at `C:\flutter\bin` (NOT on PATH): prefix every flutter command
  with `$env:PATH = "C:\flutter\bin;$env:PATH"`.
- Flutter 3.24.5 / Dart 3.5.4 → use `withOpacity`, NOT `withValues`.
- Python 3.13 on PATH. Deps installed globally (cloudinary, python-multipart,
  PyJWT, bcrypt, pytest 9.1.1, Pillow 11.3).
- **PowerShell trap**: `$env:FOO = ""` *deletes* the variable rather than
  setting it empty. The legacy `test_*.py` harnesses therefore must NOT be
  launched with `$env:CLOUDINARY_*=""`; use the `runpy` one-liner in
  "Run & verify" (sets `os.environ.update({...: ''})` inside Python).
- **Gradle lock trap**: Windows file indexer or stale gradle daemon pins `frontend\build`.
  Fix: `taskkill /F /PID <java_pid>` and run `attrib -h -s -r /s desktop.ini 2>nul & del /s /q /f desktop.ini 2>nul`
  before release builds.
- aapt for APK inspection:
  `%LOCALAPPDATA%\Android\Sdk\build-tools\33.0.1\aapt.exe dump badging ..\campusmart-ai.apk`.

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
| 9 | Precision Overhaul: Warm Paper daylight aesthetic, Brevo transactional email & instant OTP fallback, Gemini 3.5 Flash Vision AI, 4-photo mandatory sell flow with zoomable lightbox, grounded Ask AI campus assistant, on-the-fly user creation, and INR currency conversion | ✅ 2026-10-16 |
| — | Root `README.md` master handover doc | ✅ updated 2026-10-16 |
| — | Real Firebase auth swap (`flutterfire configure`) | ⚠️ OPTIONAL — campus JWT is live; Firebase path stays active as alternate |
| — | Alembic migrations | ❌ BACKLOG (schema_upgrade.py stopgap handles Phase 7 columns) |
| — | Execute live deploy + seed against Render Postgres | ❌ BACKLOG |

## Key architectural decisions (do not regress)
- **Visual Design System**: Warm Paper aesthetic.
  - Background: Paper Cream (`#FAF9F6`)
  - Surface: Crisp White (`#FFFFFF`)
  - Primary text / actions: Deep Ink Black (`#141413`)
  - Inputs / subtle states: Stone Sand Gray (`#F3F2EE` / `#EFEFE9`)
  - Highlights: Royal Blue (`#2563EB`)
  - Badges: Matte Forest Green (`#15803D`) and soft amber
  - Typography: Serif font headers.
- **Currency**: Strictly Indian Rupees (`₹`) across all screens, models, prompts, and feeds.
- **Auth & Profiles**:
  - `get_or_create_current_user` creates `User` profile dynamically on valid token arrival if row was missing. Never raises `"Create your profile first"`.
  - Brevo transactional email for OTPs with `fallback_otp_code` in JSON response.
  - Flutter 1-tap OTP auto-fill & verify on yellow delivery delay banner tap.
- **Multimodal Vision AI**:
  - `backend/app/ai/vision_master.py` uses `gemini-3.5-flash` with fallback to `gemini-3.6-flash` and `gemini-3.5-flash-lite`.
  - Base64 payload decoding (`inline_data`), deep catalog brand/model matching, realistic INR valuation rules.
  - Mandatory 4 photos (Front, Back, Label/Model, Ports/Condition). AI valuation hidden until all 4 photos selected and user taps "Scan 4 Photos with AI".
- **Discover Feed**:
  - Minimalist Airbnb/Blinkit top bar: compact logo, inline search bar, notification shortcut.
  - Wide editorial recommendation rail cards with bold `₹` typography and matte forest green savings badges.
- **Product Details**:
  - Swipeable `PageView` 4-photo hero gallery with dot indicators.
  - Fullscreen interactive zoomable lightbox viewer (`InteractiveViewer`, 1.0x–4.0x).
  - Pinned bottom bar with "Chat with Seller" and "Buy / Reserve Now".
- **Ask AI Assistant**:
  - LLM contextualized with live PostgreSQL product catalog.
  - Stem synonym keyword matching for speakers, calculators, books, laptops, lab items.
  - Interactive product cards in chat stream.
- **Support & Moderation**:
  - Admin & support contact: `martaicampus@gmail.com`.
  - Single bottom logout button in profile screen.
  - Detached snapshot email notifications for listing publication and purchases.

## Verification & release commands
```powershell
# Backend verification harnesses (17/17 passed):
cd backend
python -m pytest test_email_otp.py test_production_upgrade.py -v

# Frontend linting (0 issues):
cd frontend
flutter analyze

# Clean Windows locks & desktop.ini prior to build:
cmd.exe /c "attrib -h -s -r /s desktop.ini 2>nul & del /s /q /f desktop.ini 2>nul"

# Build production release APK:
flutter build apk --release --dart-define=API_BASE_URL=https://campusmart-api-zia4.onrender.com
cmd.exe /c "copy /y build\app\outputs\flutter-apk\app-release.apk ..\campusmart-ai.apk"
```
