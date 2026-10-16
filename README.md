# CampusMart AI

**An AI-powered circular marketplace for campus life** — students list second-hand items with a 4-angle photo scan, and a multimodal Vision AI + LangGraph engine identifies the product, inspects condition, calculates fair resale prices in Indian Rupees (`₹`), and screens for fraud before publishing.

---

## System Architecture

```
┌────────────────────┐     Bearer JWT        ┌───────────────────────────┐
│  Flutter Client    │ ────────────────────► │  FastAPI Gateway          │
│  (Android / iOS /  │  POST /products/      │  • Brevo Transactional OTP│
│   Web)             │  GET  /products/      │  • Dual-path JWT Auth     │
│  • Warm Paper UI   │  POST /products/      │  • Cloudinary CDN Uploads │
│  • 4-Photo Scan    │       upload-image/   └─────────────┬─────────────┘
│  • Zoom Lightbox   │  POST /ai/chat                      │
│  • Ask AI Card Bot │                                     │
└────────────────────┘                       ┌─────────────▼─────────────┐
                                             │ Multimodal AI Pipeline    │
                                             │ • Gemini 3.5 Flash Vision │
                                             │ • Catalog & Web Matching  │
                                             │ • INR (₹) Fair Resale Val │
                                             │ • Trust & Fraud Shield    │
                                             └─────────────┬─────────────┘
                                                           │
                                             ┌─────────────▼─────────────┐
                                             │ Neon PostgreSQL           │
                                             │ users · products · chats  │
                                             │ transactions · system_cfg │
                                             └───────────────────────────┘
```

| Component | Function | Tech Stack |
|---|---|---|
| **Flutter Frontend** | Warm Paper daylight theme, Airbnb/Blinkit header, 4-photo mandatory sell flow, zoomable image lightbox, grounded "Ask AI" assistant, 1-tap OTP auto-fill | Flutter 3.24 (Dart 3.5), Provider, http, image_picker, url_launcher |
| **FastAPI Gateway** | REST API, Brevo transactional email & OTP fallback, Bearer JWT auth, dynamic user synchronization, Cloudinary upload pipeline | Python 3.11+, FastAPI, SQLAlchemy 2, Brevo API, Cloudinary SDK |
| **Multimodal Vision AI** | 4-photo multi-angle brand/model catalog recognition, condition inspection, realistic Indian Rupee (`₹`) resale valuations | Google Gemini 3.5 Flash (with fallback chain: 3.6-flash, 3.5-flash-lite) |
| **Cloud PostgreSQL** | Cloud database storing users, listings, buyer-seller chat threads, transactions, and dynamic system config | Neon PostgreSQL (ap-southeast-1) / Render Postgres |

---

## Core Features

- **Warm Paper Aesthetic**: Minimalist, clean design featuring Warm Paper-Cream (`#FAF9F6`), Crisp Elevated White (`#FFFFFF`), Deep Ink-Black (`#141413`), Subtle Royal Blue (`#2563EB`), and Matte Forest Green (`#15803D`) badges with Serif typography.
- **Mandatory 4-Photo Sell Flow**: Ensures buyers inspect Front, Back, Label/Model, and Condition before purchase. The AI Smart Estimate remains hidden until all 4 photos are staged and scanned.
- **Swipeable Gallery & Pinch-to-Zoom Lightbox**: Product detail view features a swipeable `PageView` with page indicator dots and a fullscreen `InteractiveViewer` (1.0x–4.0x zoom).
- **Grounded "Ask AI" Assistant**: Chatbot grounded with live PostgreSQL catalog inventory and stem-synonym fuzzy matching (speakers, calculators, books, lab equipment, laptops).
- **Brevo Transactional Emails & Instant OTP**: Delivers 6-digit codes to student emails, listing publication snapshots, and purchase receipts. If external delivery is delayed, a 1-tap banner auto-fills and verifies the code instantly.
- **Zero-Lockout Dynamic Profiles**: Missing user records are automatically created on the fly when valid tokens arrive—eliminating `"Create your profile first"` errors.
- **Indian Rupee (`₹`) Standardization**: Native INR pricing throughout all models, feeds, search filters, and AI prompts.

---

## Repository Layout

```
campusmart_ai/
├── campusmart-ai.apk         # Production release APK (49.2 MB, Android universal)
├── render.yaml               # Render.com deployment blueprint
├── SESSION_CONTEXT.md        # Internal engineering lock file
├── README.md                 # Master documentation
├── backend/
│   ├── requirements.txt
│   ├── seed_db.py            # Demo campus seed data
│   ├── test_email_otp.py     # Brevo OTP & fallback verification test
│   ├── test_production_upgrade.py # 17-point production E2E test suite
│   └── app/
│       ├── main.py           # Lifespan, CORS, uploads mount, routers
│       ├── database.py       # Neon PostgreSQL / SQLite fallback
│       ├── auth.py           # JWT auth + get_or_create_current_user
│       ├── models.py         # User, Product, Transaction, ChatMessage, SystemConfig
│       ├── email_service.py  # Brevo API email dispatcher & templates
│       ├── storage.py        # Cloudinary CDN + local fallback
│       ├── ai/
│       │   ├── vision_master.py  # Gemini 3.5 Flash multimodal valuation
│       │   └── orchestrator.py   # LangGraph listing intelligence
│       └── routers/          # auth, products, transactions, chat, admin
└── frontend/                 # Flutter mobile & web client
    └── lib/
        ├── main.dart         # Providers + Warm Paper theme definition
        ├── constants/        # AppColors, typography, assets
        ├── services/         # api_service.dart, email/OTP handlers
        ├── providers/        # auth, product, wishlist providers
        ├── screens/          # feed, create_listing, product_detail, ai_assistant, profile
        └── widgets/          # product_card, trust_score_meter, lightbox
```

---

## Quickstart

### Prerequisites
- Python 3.10+
- Flutter 3.24+
- (Optional) Docker or PostgreSQL connection string

### 1. Backend Setup

```bash
cd backend
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Configure `backend/.env` (defaults provided):
```env
DATABASE_URL=postgresql://user:pass@ep-cool-frost.ap-southeast-1.aws.neon.tech/campusmart?sslmode=require
JWT_SECRET_KEY=campusmart-secret-key-32chars
BREVO_API_KEY=xkeysib-...
BREVO_SENDER_EMAIL=martaicampus@gmail.com
GEMINI_API_KEY=AIzaSy...
```

Run seed and start server:
```bash
python seed_db.py
python -m uvicorn app.main:app --reload
# → http://127.0.0.1:8000 (Swagger docs at /docs)
```

### 2. Frontend Setup

```bash
cd frontend
flutter pub get

# Run on connected device or emulator:
flutter run

# Or build release APK:
flutter build apk --release --dart-define=API_BASE_URL=https://campusmart-api-zia4.onrender.com
```

---

## Verification & Test Harnesses

To run backend tests without Docker (in-memory test harness):
```bash
cd backend
python -m pytest test_email_otp.py test_production_upgrade.py -v
# Result: 17 passed, 0 failures
```

To run Flutter code analysis:
```bash
cd frontend
flutter analyze
# Result: No issues found!
```

---

## Production Deployment

- **Backend API:** Deployed on Render (`https://campusmart-api-zia4.onrender.com`).
- **Database:** Neon Serverless PostgreSQL with SSL.
- **Admin & Support Account:** `martaicampus@gmail.com`
- **Android App Launcher Label:** Strictly `CampusMart` (10 chars, single word) in `AndroidManifest.xml`.
- **Release APK:** Built and available at the root repository as `campusmart-ai.apk`.

---

<div align="center">

**CampusMart AI** · Reuse. Reduce. Recycle — on campus.

*Contact & Support: [martaicampus@gmail.com](mailto:martaicampus@gmail.com)*

</div>
