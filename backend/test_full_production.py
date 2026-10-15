"""
test_full_production.py - Phase 7 full-production E2E verification harness.

Walks the ENTIRE live student journey with ZERO mocks (JWT auth only, no
mock-* tokens, no AUTH_DEV_BYPASS reliance):

    1.  Student registration (A = seller, B = buyer, C = to-be-blocked)
    2.  Login round-trip for both students
    3.  JWT-authenticated image upload (local /uploads fallback)
    4.  AI listing creation: clean listing + fraud-flagged listing
    5.  Admin overview real counts + flagged queue
    6.  Admin AI-agent runtime toggle (trust agent OFF -> fraud passes;
        back ON -> next fraud listing is flagged)
    7.  Admin approve (trust +0.2, trust_reason cleared)
    8.  User blocking: blocked student gets 403 on create + purchase
    9.  Item purchase: transaction row, product sold, seller trust +0.1
    10. Double-buy rejection (400)
    11. GET /transactions/my for both buyer and seller
    12. Admin delete listing (trust -0.8)
    13. Admin endpoints reachable without Bearer (dashboard default)
    14. Flutter analyze (subprocess; skipped gracefully if Flutter absent)

Run (from /backend):
    python test_full_production.py

Exit code 0 = all checks passed; 1 = at least one check failed.
"""

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.orchestrator import get_agent_flags, reset_agent_flags
from app.database import Base, get_db
from app.main import app

# --- In-memory SQLite + dependency override (lifespan skipped) ---------------
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)  # NO context manager -> lifespan intentionally skipped

# Minimal valid 1x1 red PNG (67 bytes) for the upload step.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e"
    "44ae426082"
)

passed = 0
failed = 0


def check(name: str, condition: bool, detail="") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS - {name} | {detail}")
    else:
        failed += 1
        print(f"FAIL - {name} | {detail}")


def register(name: str, email: str, password: str = "password123") -> dict:
    r = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert r.status_code == 201, f"register {email}: {r.status_code} {r.text}"
    return r.json()


def login(email: str, password: str = "password123") -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    return r.json()


def auth_headers(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}


def create_listing(headers: dict, title: str, description: str,
                   price: float = 50.0, image_url: str = "https://cdn.example.com/x.jpg"):
    return client.post(
        "/products/",
        headers=headers,
        json={
            "title": title,
            "description": description,
            "condition": "Good",
            "image_url": image_url,
            "listed_price": price,
        },
    )


def main() -> None:
    reset_agent_flags()

    # =========================================================================
    # 1-2. Registration + login
    # =========================================================================
    print("\n--- 1-2. Student registration & login ---")
    seller = register("Aarav Sharma", "aarav.sharma@campus.edu")
    buyer = register("Diya Patel", "diya.patel@campus.edu")
    blocked = register("Rogue Student", "rogue.student@campus.edu")

    check("register seller -> 201 + JWT", bool(seller.get("access_token")))
    check("seller profile has active status", seller["user"]["status"] == "active")
    check("seller has no password_hash leak", "password_hash" not in seller["user"])
    check("register duplicate email -> 409",
          client.post("/auth/register",
                      json={"name": "Dup", "email": "aarav.sharma@campus.edu",
                            "password": "password123"}).status_code == 409)
    check("login wrong password -> 401",
          client.post("/auth/login",
                      json={"email": "aarav.sharma@campus.edu",
                            "password": "wrongpass"}).status_code == 401)

    seller_session = login("aarav.sharma@campus.edu")
    buyer_session = login("diya.patel@campus.edu")
    check("login returns JWT + profile", bool(seller_session.get("access_token")))
    check("JWT round-trip hits /users/{uid}",
          client.get(
              f"/users/{seller_session['user']['firebase_uid']}",
              headers=auth_headers(seller_session),
          ).status_code == 200)

    seller_h = auth_headers(seller_session)
    buyer_h = auth_headers(buyer_session)
    blocked_h = auth_headers(blocked)

    # =========================================================================
    # 3. Image upload with real JWT
    # =========================================================================
    print("\n--- 3. JWT-authenticated image upload ---")
    r = client.post(
        "/products/upload-image/",
        headers=seller_h,
        files={"file": ("listing.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    check("upload with JWT -> 200", r.status_code == 200, r.text[:80])
    image_url = r.json().get("image_url", "") if r.status_code == 200 else ""

    # =========================================================================
    # 4. AI listing creation: clean + fraud-flagged
    # =========================================================================
    print("\n--- 4. AI listing creation (clean + flagged) ---")
    clean = create_listing(
        seller_h,
        "Engineering Mechanics Textbook",
        "B.S. Grewal style mechanics book, great condition, no highlights.",
        price=45.0,
        image_url=image_url or "https://cdn.example.com/book.jpg",
    )
    check("clean listing -> 201 active", clean.status_code == 201
          and clean.json()["status"] == "active",
          f"{clean.status_code} {clean.json().get('status')}")
    check("clean listing has AI category",
          bool(clean.json().get("category")), clean.json().get("category"))
    check("clean listing trust_reason is null",
          clean.json().get("trust_reason") is None)
    clean_id = clean.json()["id"]

    fraud = create_listing(
        seller_h,
        "iPhone 15 Pro - urgent wire transfer only",
        "Send payment via urgent wire transfer, free money deal, no campus meetup.",
        price=900.0,
    )
    check("fraud listing -> 201 flagged", fraud.status_code == 201
          and fraud.json()["status"] == "flagged",
          f"{fraud.status_code} {fraud.json().get('status')}")
    check("flagged listing persists trust_reason",
          bool(fraud.json().get("trust_reason")),
          fraud.json().get("trust_reason", "")[:60])
    fraud_id = fraud.json()["id"]

    # =========================================================================
    # 5. Admin overview
    # =========================================================================
    print("\n--- 5. Admin overview ---")
    r = client.get("/admin/overview")
    check("GET /admin/overview -> 200 (no auth needed)", r.status_code == 200)
    overview = r.json()
    check("overview total_active_users >= 3", overview["total_active_users"] >= 3,
          overview["total_active_users"])
    check("overview listings_today >= 2", overview["listings_today"] >= 2,
          overview["listings_today"])
    check("overview flagged_count >= 1", overview["flagged_count"] >= 1,
          overview["flagged_count"])
    check("overview flagged_items populated",
          len(overview["flagged_items"]) >= 1)
    check("flagged item exposes seller + trust_reason",
          overview["flagged_items"][0].get("seller_email")
          == "aarav.sharma@campus.edu"
          and bool(overview["flagged_items"][0].get("trust_reason")))

    # =========================================================================
    # 6. AI agent runtime toggle
    # =========================================================================
    print("\n--- 6. AI agent runtime toggle ---")
    r = client.get("/admin/ai-agents")
    check("GET /admin/ai-agents -> 200", r.status_code == 200)
    check("all agents enabled by default",
          all(r.json()["agents"].values()), r.json())

    r = client.patch(
        "/admin/ai-agents/trust_fraud_detection",
        json={"enabled": False},
    )
    check("disable trust agent -> 200", r.status_code == 200)
    check("flag actually False in runtime state",
          get_agent_flags()["trust_fraud_detection"] is False)

    fraud2 = create_listing(
        seller_h,
        "MacBook - urgent wire transfer now",
        "Urgent wire transfer only, free money offer.",
        price=1200.0,
    )
    check("trust agent OFF -> fraud listing passes as active",
          fraud2.status_code == 201 and fraud2.json()["status"] == "active",
          f"{fraud2.status_code} {fraud2.json().get('status')}")
    fraud2_id = fraud2.json()["id"]

    r = client.patch(
        "/admin/ai-agents/trust_fraud_detection",
        json={"enabled": True},
    )
    check("re-enable trust agent -> 200", r.status_code == 200)
    check("flag restored", get_agent_flags()["trust_fraud_detection"] is True)

    fraud3 = create_listing(
        seller_h,
        "iPad Air - urgent wire transfer",
        "Only urgent wire transfer, free money guaranteed.",
        price=600.0,
    )
    check("trust agent ON -> next fraud listing flagged again",
          fraud3.status_code == 201 and fraud3.json()["status"] == "flagged",
          f"{fraud3.status_code} {fraud3.json().get('status')}")

    r = client.patch("/admin/ai-agents/not_a_real_agent", json={"enabled": False})
    check("unknown agent key -> 404", r.status_code == 404)

    # =========================================================================
    # 7. Admin approve (trust +0.2, reason cleared)
    # =========================================================================
    print("\n--- 7. Admin approve ---")
    r = client.get(f"/admin/listings")
    check("GET /admin/listings -> 200 all statuses",
          r.status_code == 200 and len(r.json()) >= 4)
    statuses = {item["status"] for item in r.json()}
    check("admin listings include active + flagged",
          "active" in statuses and "flagged" in statuses, statuses)
    check("admin listings expose seller_name/email/trust",
          all(key in r.json()[0] for key in
              ("seller_name", "seller_email", "seller_trust_score")))

    seller_trust_before = next(
        u["trust_score"] for u in client.get("/admin/users").json()
        if u["email"] == "aarav.sharma@campus.edu"
    )
    r = client.patch(f"/admin/listings/{fraud_id}/approve")
    check("approve flagged -> 200 active + reason cleared",
          r.status_code == 200 and r.json()["status"] == "active"
          and r.json()["trust_reason"] is None)
    seller_trust_after = next(
        u["trust_score"] for u in client.get("/admin/users").json()
        if u["email"] == "aarav.sharma@campus.edu"
    )
    check("approve bumps seller trust +0.2 (capped at 5.0)",
          abs(seller_trust_after - min(5.0, seller_trust_before + 0.2)) < 1e-6,
          f"{seller_trust_before} -> {seller_trust_after}")

    # =========================================================================
    # 8. User blocking -> 403 on create + purchase
    # =========================================================================
    print("\n--- 8. User blocking ---")
    blocked_user = next(
        u for u in client.get("/admin/users").json()
        if u["email"] == "rogue.student@campus.edu"
    )
    r = client.patch(
        f"/admin/users/{blocked_user['id']}/status",
        json={"status": "blocked"},
    )
    check("block user -> 200 blocked", r.status_code == 200
          and r.json()["status"] == "blocked")

    r = create_listing(blocked_h, "Blocked listing attempt", "Should 403.")
    check("blocked user create listing -> 403", r.status_code == 403,
          r.json().get("detail", ""))

    r = client.post(
        f"/products/{clean_id}/purchase",
        headers=blocked_h,
        json={},
    )
    check("blocked user purchase -> 403", r.status_code == 403)

    r = client.post("/auth/login",
                    json={"email": "rogue.student@campus.edu",
                          "password": "password123"})
    check("blocked user login -> 403", r.status_code == 403)

    r = client.patch(
        f"/admin/users/{blocked_user['id']}/status",
        json={"status": "active"},
    )
    check("unblock user -> 200 active", r.status_code == 200
          and r.json()["status"] == "active")

    # =========================================================================
    # 9-11. Purchase flow + history
    # =========================================================================
    print("\n--- 9-11. Purchase flow + transaction history ---")
    seller_trust_before = next(
        u["trust_score"] for u in client.get("/admin/users").json()
        if u["email"] == "aarav.sharma@campus.edu"
    )
    r = client.post(f"/products/{clean_id}/purchase", headers=buyer_h, json={})
    check("buyer purchase -> 200 sold", r.status_code == 200
          and r.json()["product_status"] == "sold",
          f"{r.status_code} {r.json() if r.status_code == 200 else r.text[:80]}")
    check("purchase returns transaction_id + final_price",
          bool(r.json().get("transaction_id")) and r.json().get("final_price") == 45.0)

    seller_trust_after = next(
        u["trust_score"] for u in client.get("/admin/users").json()
        if u["email"] == "aarav.sharma@campus.edu"
    )
    check("sale bumps seller trust +0.1 (capped at 5.0)",
          abs(seller_trust_after - min(5.0, seller_trust_before + 0.1)) < 1e-6,
          f"{seller_trust_before} -> {seller_trust_after}")

    r = client.post(f"/products/{clean_id}/purchase", headers=buyer_h, json={})
    check("double-buy -> 400 (already sold)", r.status_code == 400)

    r = client.post(f"/products/{clean_id}/purchase", headers=seller_h, json={})
    check("own-listing purchase -> 400", r.status_code == 400)

    r = client.get("/transactions/my", headers=buyer_h)
    check("buyer /transactions/my -> 200 with 1 bought",
          r.status_code == 200 and len(r.json()["bought"]) == 1
          and r.json()["sold"] == [],
          f"bought={len(r.json().get('bought', []))}")
    check("bought record has product_title + seller_name",
          r.json()["bought"][0]["product_title"] == "Engineering Mechanics Textbook"
          and r.json()["bought"][0]["seller_name"] == "Aarav Sharma")

    r = client.get("/transactions/my", headers=seller_h)
    check("seller /transactions/my -> 200 with 1 sold",
          r.status_code == 200 and len(r.json()["sold"]) == 1
          and r.json()["bought"] == [])
    check("sold record has buyer_name",
          r.json()["sold"][0]["buyer_name"] == "Diya Patel")

    # =========================================================================
    # 12. Admin delete listing (trust -0.8)
    # =========================================================================
    print("\n--- 12. Admin delete listing ---")
    seller_trust_before = next(
        u["trust_score"] for u in client.get("/admin/users").json()
        if u["email"] == "aarav.sharma@campus.edu"
    )
    r = client.delete(f"/admin/listings/{fraud2_id}")
    check("delete listing -> 204", r.status_code == 204)
    seller_trust_after = next(
        u["trust_score"] for u in client.get("/admin/users").json()
        if u["email"] == "aarav.sharma@campus.edu"
    )
    check("delete penalizes seller trust -0.8 (floor 0.0)",
          abs(seller_trust_after - max(0.0, seller_trust_before - 0.8)) < 1e-6,
          f"{seller_trust_before} -> {seller_trust_after}")

    # Trust is now below the 5.0 cap -> prove the +0.1 sale bonus actually
    # moves the score (the earlier +0.1 hit the cap and was a no-op).
    follow = create_listing(
        seller_h, "Circuit Theory Notes", "Clean handwritten notes.", price=15.0,
    )
    check("follow-up listing -> 201", follow.status_code == 201)
    r = client.post(
        f"/products/{follow.json()['id']}/purchase", headers=buyer_h, json={},
    )
    seller_trust_final = next(
        u["trust_score"] for u in client.get("/admin/users").json()
        if u["email"] == "aarav.sharma@campus.edu"
    )
    check("below-cap sale bumps seller trust +0.1",
          r.status_code == 200
          and abs(seller_trust_final - (seller_trust_after + 0.1)) < 1e-6,
          f"{seller_trust_after} -> {seller_trust_final}")

    # =========================================================================
    # 13. Admin auth modes
    # =========================================================================
    print("\n--- 13. Admin auth modes ---")
    check("admin overview open without Bearer (dashboard default)",
          client.get("/admin/overview").status_code == 200)
    check("admin overview also accepts Bearer when supplied",
          client.get("/admin/overview", headers=seller_h).status_code == 200)

    # =========================================================================
    # 14. Flutter analyze
    # =========================================================================
    print("\n--- 14. Flutter analyze ---")
    frontend = Path(__file__).resolve().parent.parent / "frontend"
    flutter_bin = Path(os.environ.get("FLUTTER_ROOT", r"C:\flutter")) / "bin"
    flutter_exe = flutter_bin / ("flutter.bat" if os.name == "nt" else "flutter")
    if flutter_exe.exists() or shutil.which("flutter"):
        exe = str(flutter_exe) if flutter_exe.exists() else "flutter"
        env = dict(os.environ)
        env["PATH"] = f"{flutter_bin};{env.get('PATH', '')}"
        result = subprocess.run(
            [exe, "analyze"],
            cwd=str(frontend),
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
        check("flutter analyze -> No issues found",
              result.returncode == 0 and "No issues found" in (result.stdout + result.stderr),
              (result.stdout + result.stderr).strip().splitlines()[-1]
              if (result.stdout + result.stderr).strip() else "")
    else:
        print("SKIP - flutter executable not found on this machine")

    # -------------------------------------------------------------------------
    reset_agent_flags()
    print(f"\n{'=' * 60}\n{passed}/{passed + failed} checks passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
