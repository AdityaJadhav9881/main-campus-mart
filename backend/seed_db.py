"""
seed_db.py
==========
Phase 5 demo-data seeder for CampusMart AI.

Connects through app/database.py (same Session/engine the API uses) and
populates:
    * 3 student seller profiles with varying trust scores (4.9 / 4.2 / 3.1)
    * 8 realistic campus listings across Academic Material, Lab Gear &
      Instruments, and Electronics

Suggested prices are computed with the SAME category + condition table the
LangGraph price agent uses (app/ai/price_agent.py), so seeded data stays
consistent with live AI-processed listings (all amounts in â‚¹):
        Academic Material  base â‚¹500 | Lab Gear  â‚¹600 | Electronics â‚¹1500
        New 1.00 | Like New 0.80 | Good 0.60 | Fair 0.40 | Poor 0.20

Usage (always run from /backend so `app.*` imports resolve):
    python seed_db.py            # WIPE all tables, then repopulate (default)
    python seed_db.py --append   # keep existing data; add only missing rows

The default wipe drops users/products/transactions in FK-safe order via
Base.metadata.drop_all, so re-runs never hit foreign-key conflicts and the
demo state is always deterministic. Transaction history is intentionally
left empty (purchases are created by the checkout flow, Phase 6).
"""

from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from app.ai.price_agent import CONDITION_FACTORS, base_price_for
from app.auth import PROTECTED_ADMIN_EMAILS, SUPER_ADMIN_EMAIL, hash_password
from app.database import Base, SessionLocal, engine
from app.models import Product, Transaction, User

# Unsplash CDN tuning: small, cropped, cacheable placeholders.
_IMG = "?auto=format&fit=crop&w=800&q=80"

# Shared demo password so seeded accounts can be logged into immediately from
# the live app (email + password123) in addition to fresh registration.
SEED_PASSWORD = "password123"

# ---------------------------------------------------------------------------
# Seed users - varying trust scores so the UI trust indicators are demoable
# ---------------------------------------------------------------------------
SEED_USERS: list[dict] = [
    {
        "firebase_uid": "seed-admin",
        "name": "CampusMart Admin",
        "email": "martaicampus@gmail.com",
        "trust_score": 5.0,
        "status": "active",
        "password_hash": hash_password(SEED_PASSWORD),
    },
    {
        "firebase_uid": "seed-aarav",
        "name": "Aarav Mehta",
        "email": "aarav.mehta@campus.edu",
        "trust_score": 4.9,
        "status": "active",
        "password_hash": hash_password(SEED_PASSWORD),
    },
    {
        "firebase_uid": "seed-meera",
        "name": "Meera Iyer",
        "email": "meera.iyer@campus.edu",
        "trust_score": 4.2,
        "status": "active",
        "password_hash": hash_password(SEED_PASSWORD),
    },
    {
        "firebase_uid": "seed-rohan",
        "name": "Rohan Deshmukh",
        "email": "rohan.deshmukh@campus.edu",
        "trust_score": 3.1,
        "status": "active",
        "password_hash": hash_password(SEED_PASSWORD),
    },
]

# ---------------------------------------------------------------------------
# Seed listings - realistic engineering-campus inventory
# `suggested_price` is filled at seed time from the pricing-agent table.
# ---------------------------------------------------------------------------
SEED_PRODUCTS: list[dict] = [
    {
        "seller_uid": "seed-aarav",
        "title": "Engineering Mathematics III",
        "description": (
            "B.S. Grewal Engineering Mathematics III, 4th edition. Used for "
            "one semester only - no highlights, no missing pages. Perfect for "
            "third-year mechanical/civil students. Includes my clean formula "
            "summary stickers on the inside cover."
        ),
        "category": "Academic Material",
        "condition": "Like New",
        "listed_price": 350.0,
        "ai_tags": "textbook, mathematics, grewal, calculus, engineering, 4th edition",
        "image_url": f"https://images.unsplash.com/photo-1544947950-fa07a98d237f{_IMG}",
    },
    {
        "seller_uid": "seed-meera",
        "title": "Signals and Systems - Oppenheim (2nd Edition)",
        "description": (
            "Classic Oppenheim & Willsky signals and systems textbook. Good "
            "condition with light edge wear and a few pencil notes in the "
            "Fourier chapters. Worked problems are a lifesaver before exams."
        ),
        "category": "Academic Material",
        "condition": "Good",
        "listed_price": 280.0,
        "ai_tags": "textbook, signals, systems, oppenheim, fourier, communication",
        "image_url": f"https://images.unsplash.com/photo-1512820790803-83ca734da794{_IMG}",
    },
    {
        "seller_uid": "seed-aarav",
        "title": "Mini Drafter & Engineering Sheet Tube",
        "description": (
            "Mini drafter with telescopic arm plus a rolled engineering "
            "drawing tube. Used through Engineering Graphics coursework only. "
            "Clamps tight, angles stay true, scale still legible."
        ),
        "category": "Lab Gear & Instruments",
        "condition": "Like New",
        "listed_price": 350.0,
        "ai_tags": "mini drafter, engineering graphics, drawing, sketching, geometry",
        "image_url": f"https://images.unsplash.com/photo-1530124566582-a618bc2615dc{_IMG}",
    },
    {
        "seller_uid": "seed-rohan",
        "title": "Digital Multimeter (DMM) with Probe Set",
        "description": (
            "Auto-ranging digital multimeter with fresh 9V battery and full "
            "probe set (banana + crocodile clips). Calibrated against the lab "
            "reference last month. Ideal for circuits lab and hobby projects."
        ),
        "category": "Lab Gear & Instruments",
        "condition": "Good",
        "listed_price": 350.0,
        "ai_tags": "multimeter, dmm, probes, circuits lab, measurement, electronics",
        "image_url": f"https://images.unsplash.com/photo-1518770660439-4636190af475{_IMG}",
    },
    {
        "seller_uid": "seed-meera",
        "title": "Casio fx-991EX Scientific Calculator",
        "description": (
            "Casio fx-991EX Classwiz - the exam-allowed standard for "
            "engineering. Screen protector still on, buttons crisp, no "
            "scratches. Selling because I upgraded to the CX model."
        ),
        "category": "Electronics",
        "condition": "Like New",
        "listed_price": 900.0,
        "ai_tags": "calculator, casio, fx-991EX, classwiz, scientific, exam",
        "image_url": f"https://images.unsplash.com/photo-1587145820266-a5951ee6f620{_IMG}",
    },
    {
        "seller_uid": "seed-aarav",
        "title": "ESP32 DevKit v1 + Sensor Bundle (10x)",
        "description": (
            "IoT starter bundle: 2x ESP32-WROOM DevKit v1 boards plus DHT11, "
            "HC-SR04, LDR, and MQTT-ready jumper harness. Everything tested "
            "with PlatformIO. Perfect for the IoT elective mini-project."
        ),
        "category": "Electronics",
        "condition": "Good",
        "listed_price": 750.0,
        "ai_tags": "esp32, iot, devkit, dht11, sensor, arduino, wifi, bluetooth",
        "image_url": f"https://images.unsplash.com/photo-1550745165-9bc0b252726f{_IMG}",
    },
    {
        "seller_uid": "seed-rohan",
        "title": "Arduino Uno Starter Kit",
        "description": (
            "Genuine Arduino Uno R3 with breadboard, LED/resistor pack, "
            "servo, and USB cable. Fair condition - board works perfectly, "
            "some wires are bent from lab use. Great entry point for "
            "electronics club workshops."
        ),
        "category": "Electronics",
        "condition": "Fair",
        "listed_price": 500.0,
        "ai_tags": "arduino, uno, starter kit, breadboard, servo, robotics",
        "image_url": f"https://images.unsplash.com/photo-1505740420928-5e560c06d30e{_IMG}",
    },
    {
        "seller_uid": "seed-meera",
        "title": "Thermodynamics & Fluid Mechanics Notes Bundle",
        "description": (
            "Handwritten semester notes covering the full thermo + FM "
            "syllabus: worked derivations, PV diagrams, and previous-year "
            "solved papers. Photocopied set of my originals - fair condition "
            "with staple holes, content complete."
        ),
        "category": "Academic Material",
        "condition": "Fair",
        "listed_price": 150.0,
        "ai_tags": "notes, thermodynamics, fluid mechanics, handwritten, solved papers",
        "image_url": f"https://images.unsplash.com/photo-1497633762265-9d179a990aa6{_IMG}",
    },
]


def suggested_price_for(condition: str, category: str) -> float:
    """Compute the AI fair-value price (â‚¹) using the price agent's own table.

    Mirrors app/ai/price_agent.py exactly (category base x condition
    factor), so seeded listings show the same suggested_price a live POST
    /products/ would produce for the same category + condition.
    """
    factor = CONDITION_FACTORS.get(condition.strip().lower(), 0.50)
    return round(base_price_for(category) * factor, 2)


def _seed_users(db: Session, append: bool) -> dict[str, User]:
    """Insert seed sellers; return firebase_uid -> User. Skips existing rows
    in --append mode (idempotent on the UNIQUE firebase_uid column)."""
    users: dict[str, User] = {}
    for row in SEED_USERS:
        existing = (
            db.query(User).filter(User.firebase_uid == row["firebase_uid"]).first()
        )
        if existing is not None:
            users[row["firebase_uid"]] = existing
            print(f"  user   skip (exists): {existing.name} "
                  f"[trust {existing.trust_score}]")
            continue
        user = User(**row)
        db.add(user)
        db.flush()  # assign UUID before we reference user.id for products
        users[row["firebase_uid"]] = user
        print(f"  user   created: {user.name} <{user.email}> "
              f"[trust {user.trust_score}] [password: {SEED_PASSWORD}]")
    if not append:
        assert len(users) == len(SEED_USERS)
    return users


def _seed_products(db: Session, users: dict[str, User], append: bool) -> int:
    """Insert seed listings (idempotent on title in --append mode)."""
    created = 0
    for row in SEED_PRODUCTS:
        seller = users[row["seller_uid"]]
        if append:
            exists = (
                db.query(Product).filter(Product.title == row["title"]).first()
            )
            if exists is not None:
                print(f"  item   skip (exists): {exists.title}")
                continue
        suggested = suggested_price_for(row["condition"], row["category"])
        product = Product(
            seller_id=seller.id,
            title=row["title"],
            description=row["description"],
            category=row["category"],
            condition=row["condition"],
            image_url=row["image_url"],
            image_urls=[row["image_url"]],
            ai_tags=row.get("ai_tags", ""),        # vision-agent search tags
            suggested_price=suggested,   # pricing-agent logic
            listed_price=row["listed_price"],
            status="active",             # visible in the public feed
        )
        db.add(product)
        created += 1
        print(f"  item   created: {product.title} | {product.category} | "
              f"{product.condition} | listed â‚¹{product.listed_price:.2f} | "
              f"AI fair â‚¹{suggested:.2f} | seller {seller.name}")
    return created


def run(append: bool = False) -> tuple[int, int]:
    """Reset (or extend) the database and seed it. Returns (users, products).

    Exposed as a function so verification harnesses can call it programmatically.
    """
    if not append:
        # FK-safe wipe: drop_all tears down transactions -> products -> users.
        Base.metadata.drop_all(bind=engine)
        print("Database wiped (users, products, transactions).")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        users = _seed_users(db, append=append)
        count = _seed_products(db, users, append=append)

        # Super-admin unblock protection: whatever mode we ran in, the Master
        # Admin's account must never leave this seeder blocked. (The same
        # re-assert runs on every server boot in app/main.py lifespan.)
        for admin_email in PROTECTED_ADMIN_EMAILS:
            admin_user = (
                db.query(User).filter(User.email.ilike(admin_email)).first()
            )
            if admin_user is not None and admin_user.status != "active":
                admin_user.status = "active"
                print(f"  guard  super-admin re-activated: {admin_user.email}")

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return len(users), count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed CampusMart AI demo data (students + listings).",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Keep existing data and only add missing users/listings "
             "(idempotent). Default wipes first for a clean demo state.",
    )
    args = parser.parse_args()

    print("Seeding CampusMart AI demo data...")
    user_count, product_count = run(append=args.append)
    print(
        f"\nDone: {user_count} seller profile(s), {product_count} listing(s). "
        "Transaction history intentionally empty (checkout is Phase 6)."
    )
    print("Start the API with: python -m uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
