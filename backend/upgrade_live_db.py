"""
upgrade_live_db.py
==================
One-shot production database upgrade for CampusMart AI (production upgrade
round: INR currency + schema columns + super-admin protection).

The live Render deployment talks to a Neon Postgres provisioned BEFORE the
current release, so three things must happen once, in order:

    1. Migrate  - add every missing column/table idempotently
                  (`app.schema_upgrade.upgrade_schema`: users.status,
                   users.password_hash, products.trust_reason/image_urls/
                   ai_tags/ai_condition_notes, chat_messages.read_at, and
                   the brand-new system_config / chat_messages / email_otps
                   tables).
    2. Clean    - delete junk listings priced under ₹1 (USD-era 0.xx duds
                  that never represented a real item).
    3. Rescale  - every pre-upgrade price was in USD; reprice the whole
                  book against the INR fair-value table
                  (price_agent.CATEGORY_BASE_PRICE_INR x condition factor),
                  preserving each seller's intent by keeping the
                  listed-vs-fair ratio, and refresh suggested_price to the
                  INR fair value. Sold transactions are carried over with the
                  same per-product factor so history stays consistent.
    4. Unblock  - force the protected super-admin account active again
                  (aditya.jadhav@campus.edu can never stay blocked).

Usage (read-only inspection first, then apply):

    cd backend
    python upgrade_live_db.py            # report only - makes NO changes
    python upgrade_live_db.py --apply    # migrate + clean + rescale + unblock

Safety:
    * The rescale writes a `inr_rescale_applied_at` marker into
      system_config, so re-running --apply never double-converts prices.
    * Every other step is naturally idempotent (IF NOT EXISTS / skip-if-done).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Allow `python backend/upgrade_live_db.py` from the repo root as well as
# `python upgrade_live_db.py` from inside backend/.
BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, inspect, select, text  # noqa: E402

from app.ai.price_agent import CONDITION_FACTORS, base_price_for  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.models import Product, SystemConfig, Transaction, User  # noqa: E402
from app.schema_upgrade import upgrade_schema  # noqa: E402

# Must match `app.auth.PROTECTED_ADMIN_EMAILS`
SUPER_ADMIN_EMAILS = ("martaicampus@gmail.com", "aditya.jadhav@campus.edu")

# Listings under ₹1 are data duds (0.xx USD leftovers), never real items.
JUNK_PRICE_LIMIT = 1.0

# system_config marker guarding the rescale against double conversion.
RESCALE_MARKER_KEY = "inr_rescale_applied_at"

# Fallback condition factor when the label is missing/unknown.
_DEFAULT_FACTOR = 0.50


# ---------------------------------------------------------------------------
# Inspection (read-only - always runs)
# ---------------------------------------------------------------------------
def report(engine_) -> dict:
    """Print a read-only snapshot of the live database. Returns key stats.

    Tolerant of a pre-migration schema: metrics that need missing tables or
    columns come back as `n/a` instead of crashing the inspection.
    """
    inspector = inspect(engine_)
    tables = sorted(inspector.get_table_names())

    print("=" * 72)
    print("CAMPUSMART AI - LIVE DATABASE INSPECTION (read-only)")
    print(f"dialect: {engine_.dialect.name}")
    print("=" * 72)
    print(f"tables ({len(tables)}): {', '.join(tables)}")

    def safe(db, label: str, fn):
        """Run one inspection query, mapping pre-migration failures to 'n/a'."""
        try:
            return fn()
        except Exception as error:  # noqa: BLE001 - report, never crash
            if "-v" in sys.argv:
                print(f"debug {label.strip()}: {error}")
            return "n/a"

    stats: dict = {}
    with SessionLocal() as db:
        users = safe(db, "users          ", lambda: db.scalar(
            select(func.count()).select_from(User)))
        blocked = safe(db, "blocked users  ", lambda: db.scalar(
            select(func.count()).select_from(User).where(User.status == "blocked")))
        products = safe(db, "products       ", lambda: db.scalar(
            select(func.count()).select_from(Product)))
        transactions = safe(db, "transactions   ", lambda: db.scalar(
            select(func.count()).select_from(Transaction)))
        junk = safe(db, "junk (< ₹1)    ", lambda: db.scalar(
            select(func.count()).select_from(Product)
            .where(Product.listed_price < JUNK_PRICE_LIMIT)))
        price_row = safe(db, "price stats    ", lambda: db.execute(
            select(
                func.min(Product.listed_price),
                func.max(Product.listed_price),
                func.avg(Product.listed_price),
            )).one())
        rescale_done = safe(db, "rescale marker ", lambda: (
            db.get(SystemConfig, RESCALE_MARKER_KEY) is not None))
        super_admin = safe(db, "super-admin    ", lambda: db.scalar(
            select(User).where(func.lower(User.email) == SUPER_ADMIN_EMAIL)))

    if isinstance(price_row, tuple):
        price_min, price_max, price_avg = price_row
        price_line = (
            "min {min:,.2f} | max {max:,.2f} | avg {avg:,.2f}".format(
                min=float(price_min or 0),
                max=float(price_max or 0),
                avg=float(price_avg or 0),
            )
        )
        stats["price_min"] = float(price_min or 0)
        stats["price_max"] = float(price_max or 0)
        stats["price_avg"] = float(price_avg or 0)
    else:
        price_line = price_row  # 'n/a'

    if isinstance(super_admin, User):
        super_admin_status = super_admin.status
    else:
        super_admin_status = str(super_admin)

    stats.update(
        users=users,
        blocked=blocked,
        products=products,
        transactions=transactions,
        junk=junk,
        rescale_done=rescale_done,
        super_admin_status=super_admin_status,
    )

    print(f"users            : {users} ({blocked} blocked)")
    print(f"products         : {products}")
    print(f"transactions     : {transactions}")
    print(f"listed price     : {price_line}")
    print(f"junk (< ₹1)      : {junk} listings")
    if rescale_done is True:
        rescale_line = "yes"
    elif rescale_done is False:
        rescale_line = "no"
    else:
        rescale_line = "n/a (pending migration)"
    print(f"INR rescale done : {rescale_line}")
    print(f"super-admin      : {super_admin_status}")

    # Column-level preview so a DB missing upgrade columns is obvious.
    if "products" in tables:
        cols = {c["name"] for c in inspector.get_columns("products")}
        expected = {
            "image_urls",
            "ai_tags",
            "ai_condition_notes",
            "trust_reason",
        }
        missing = sorted(expected - cols)
        print(
            "products columns : "
            + ("all present" if not missing else f"MISSING {', '.join(missing)}")
        )
        stats["missing_columns"] = missing
    print("=" * 72)
    return stats


# ---------------------------------------------------------------------------
# Apply steps
# ---------------------------------------------------------------------------
def step_migrate() -> None:
    print("[1/4] schema migration (idempotent) ...")
    upgrade_schema(engine)
    print("      done - columns/tables verified by a fresh inspect below.")


def step_clean_junk(db) -> int:
    """Delete unreferenced listings priced under ₹1."""
    result = db.execute(
        text(
            "DELETE FROM products p "
            "WHERE p.listed_price < :limit "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM transactions t WHERE t.product_id = p.id"
            ")"
        ),
        {"limit": JUNK_PRICE_LIMIT},
    )
    removed = result.rowcount or 0
    print(f"[2/4] junk cleanup - removed {removed} sub-₹ listings")
    return removed


def _inr_prices(product: Product) -> tuple[float, float]:
    """(fair_value_inr, new_listed_inr) for one USD-era product.

    The fair value comes straight from the INR table (category base x
    condition factor); the asking price keeps the seller's intent by
    preserving the old listed/fair ratio, clamped to a sane band.
    """
    factor = CONDITION_FACTORS.get(
        (product.condition or "").strip().lower(), _DEFAULT_FACTOR
    )
    fair = round(base_price_for(product.category) * factor, 2)

    old_listed = float(product.listed_price or 0.0)
    old_suggested = float(product.suggested_price or 0.0)
    if old_listed > 0 and old_suggested > 0:
        ratio = old_listed / old_suggested
    elif old_listed > 0 and old_listed < 100:
        # USD ask without an AI estimate: assume ~$1..$99 was a typical
        # campus ask; scale onto the fair INR value at the same magnitude
        # band (e.g. $29.99 of a $50 fair -> ~60% of the INR fair).
        ratio = min(max(old_listed / 50.0, 0.5), 1.4)
    else:
        ratio = 1.0
    ratio = min(max(ratio, 0.5), 1.4)

    # Clean rupee amounts: nearest ₹10, floor ₹10 (paise never help here).
    new_listed = max(10.0, round((fair * ratio) / 10.0) * 10.0)
    return fair, new_listed


def step_rescale(db) -> int:
    """Reprice every pre-INR listing (and refresh its suggested price).

    Guarded by a system_config marker so a second --apply is a no-op.
    """
    marker = db.get(SystemConfig, RESCALE_MARKER_KEY)
    if marker is not None:
        print(
            f"[3/4] INR rescale - already applied at {marker.value} "
            "(skipping)"
        )
        return 0

    products = list(db.scalars(select(Product)))
    changed = 0
    for product in products:
        old_listed = float(product.listed_price or 0.0)
        old_suggested = float(product.suggested_price or 0.0)
        fair, new_listed = _inr_prices(product)

        ratio = (new_listed / old_listed) if old_listed > 0 else 1.0

        product.listed_price = float(new_listed)
        product.suggested_price = float(fair)
        changed += 1

        # Carry the purchase history over with the same factor so a "Paid"
        # line on the Profile tab matches the item's new currency scale.
        if old_listed > 0 and ratio != 1.0:
            for transaction in db.scalars(
                select(Transaction).where(Transaction.product_id == product.id)
            ):
                transaction.final_price = round(
                    float(transaction.final_price or 0.0) * ratio, 2
                )

    db.add(
        SystemConfig(
            key=RESCALE_MARKER_KEY,
            value=datetime.now(timezone.utc).isoformat(),
        )
    )
    print(
        f"[3/4] INR rescale - repriced {changed} listings "
        "(marker written; future runs skip)"
    )
    return changed


def step_unblock_super_admin(db) -> int:
    changed = 0
    for email in SUPER_ADMIN_EMAILS:
        result = db.execute(
            text("UPDATE users SET status = 'active' WHERE lower(email) = :email"),
            {"email": email.lower()},
        )
        changed += result.rowcount or 0
    print(
        f"[4/4] super-admin guard - {SUPER_ADMIN_EMAILS} forced active "
        f"({changed} row(s))"
    )
    return changed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or apply the CampusMart AI live DB upgrade."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="run migration + cleanup + INR rescale + super-admin unblock",
    )
    args = parser.parse_args()

    try:
        report(engine)
    except Exception as error:  # noqa: BLE001 - surface any connection issue
        print(f"ERROR: cannot reach the database: {error}")
        print("Check DATABASE_URL in backend/.env (Neon) and try again.")
        return 1

    if not args.apply:
        print("Read-only run (no changes). Re-run with --apply to upgrade.")
        return 0

    try:
        step_migrate()
        with SessionLocal() as db:
            step_clean_junk(db)
            step_rescale(db)
            step_unblock_super_admin(db)
            db.commit()
    except Exception as error:  # noqa: BLE001 - rollback happens via context
        print(f"ERROR during apply: {error}")
        raise

    print("-" * 72)
    report(engine)
    print("APPLY COMPLETE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
