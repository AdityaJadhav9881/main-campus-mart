"""
seed_db.py
==========
Phase 5 demo-data seeder for CampusMart AI.

Connects through app/database.py (same Session/engine the API uses) and
populates:
    * 3 student seller profiles with varying trust scores (4.9 / 4.2 / 3.1)
    * 8 realistic campus listings across Academic Material, Lab Gear &
      Instruments, and Electronics

Suggested prices are computed with the SAME condition table the LangGraph
price agent uses (app/ai/price_agent.py), so seeded data stays consistent
with live AI-processed listings:
        New 1.00 -> 100.00 | Like New 0.80 -> 80.00
        Good 0.60 -> 60.00 | Fair  0.40 -> 40.00

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

from app.ai.price_agent import BASE_MOCK_PRICE, CONDITION_FACTORS
from app.auth import hash_password
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
        "firebase_uid": "seed-aditya",
        "name": "Aditya Jadhav",
        "email": "aditya.jadhav@campus.edu",
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
        "seller_uid": "seed-aditya",
        "title": "Engineering Mathematics III",
        "description": (
            "B.S. Grewal Engineering Mathematics III, 4th edition. Used for "
            "one semester only - no highlights, no missing pages. Perfect for "
            "third-year mechanical/civil students. Includes my clean formula "
            "summary stickers on the inside cover."
        ),
        "category": "Academic Material",
        "condition": "Like New",
        "listed_price": 65.0,
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
        "listed_price": 55.0,
        "image_url": f"https://images.unsplash.com/photo-1512820790803-83ca734da794{_IMG}",
    },
    {
        "seller_uid": "seed-aditya",
        "title": "Mini Drafter & Engineering Sheet Tube",
        "description": (
            "Mini drafter with telescopic arm plus a rolled engineering "
            "drawing tube. Used through Engineering Graphics coursework only. "
            "Clamps tight, angles stay true, scale still legible."
        ),
        "category": "Lab Gear & Instruments",
        "condition": "Like New",
        "listed_price": 35.0,
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
        "listed_price": 42.0,
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
        "listed_price": 75.0,
        "image_url": f"https://images.unsplash.com/photo-1587145820266-a5951ee6f620{_IMG}",
    },
    {
        "seller_uid": "seed-aditya",
        "title": "ESP32 DevKit v1 + Sensor Bundle (10x)",
        "description": (
            "IoT starter bundle: 2x ESP32-WROOM DevKit v1 boards plus DHT11, "
            "HC-SR04, LDR, and MQTT-ready jumper harness. Everything tested "
            "with PlatformIO. Perfect for the IoT elective mini-project."
        ),
        "category": "Electronics",
        "condition": "Good",
        "listed_price": 55.0,
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
        "listed_price": 28.0,
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
        "listed_price": 20.0,
        "image_url": f"https://images.unsplash.com/photo-1497633762265-9d179a990aa6{_IMG}",
    },
]


def suggested_price_for(condition: str) -> float:
    """Compute the AI fair-value price using the price agent's own table.

    Mirrors app/ai/price_agent.py exactly (BASE_MOCK_PRICE x condition
    factor), so seeded listings show the same suggested_price a live POST
    /products/ would produce for the same condition.
    """
    factor = CONDITION_FACTORS.get(condition.strip().lower(), 0.50)
    return round(BASE_MOCK_PRICE * factor, 2)


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
        suggested = suggested_price_for(row["condition"])
        product = Product(
            seller_id=seller.id,
            title=row["title"],
            description=row["description"],
            category=row["category"],
            condition=row["condition"],
            image_url=row["image_url"],
            suggested_price=suggested,   # pricing-agent logic
            listed_price=row["listed_price"],
            status="active",             # visible in the public feed
        )
        db.add(product)
        created += 1
        print(f"  item   created: {product.title} | {product.category} | "
              f"{product.condition} | listed ${product.listed_price:.2f} | "
              f"AI fair ${suggested:.2f} | seller {seller.name}")
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
