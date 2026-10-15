"""
test_phase4_auth_trust.py - Phase 4 verification harness (manual test).

Verifies the two Phase 4 backend additions end-to-end WITHOUT Docker:

  1. AUTH_DEV_BYPASS: `mock-` Bearer tokens are accepted without Firebase
     verification (secure non-mock tokens still hit the Firebase guard).
  2. Seller trust indicators: ProductRead.seller_trust_score on create,
     list (joinedload), and detail reads.

Setup notes:
  * In-memory SQLite replaces PostgreSQL (no Docker on this machine).
  * TestClient is used WITHOUT a `with` block -> FastAPI lifespan is skipped,
    so init_firebase()/Postgres create_all never run.
  * Only the get_db dependency is overridden to a fresh in-memory engine.

Run (from /backend):
    python test_phase4_auth_trust.py

Exit code 0 = all checks passed; 1 = at least one check failed.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import AUTH_DEV_BYPASS
from app.database import Base, get_db
from app.main import app

# --- In-memory SQLite + dependency override -------------------------------
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,          # single shared connection for threads
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

MOCK_HEADERS = {"Authorization": "Bearer mock-local-dev-token"}
PLAIN_HEADERS = {"Authorization": "Bearer not-a-mock-token"}

passed = 0
failed = 0


def check(name: str, condition: bool, detail="") -> None:
    """Print a PASS/FAIL line and track totals."""
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS - {name} | {detail}")
    else:
        failed += 1
        print(f"FAIL - {name} | {detail}")


def main() -> None:
    # --- 0. Dev-bypass flag actually loaded from /backend/.env -------------
    check("AUTH_DEV_BYPASS enabled via .env", AUTH_DEV_BYPASS is True,
          str(AUTH_DEV_BYPASS))

    # --- 1. Mock token creates the dev profile (no Firebase) ---------------
    r = client.post(
        "/users/",
        json={"name": "Demo Student", "email": "ignored@fallback.dev"},
        headers=MOCK_HEADERS,
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    print("        profile response:", body)
    check("POST /users/ via mock token -> 201", r.status_code == 201,
          str(r.status_code))
    check("profile firebase_uid = 'dev-mock-user'",
          body.get("firebase_uid") == "dev-mock-user",
          str(body.get("firebase_uid")))
    check("email claim taken from mock identity (not request body)",
          body.get("email") == "demo.student@campus.edu",
          str(body.get("email")))

    # --- 2. Non-mock token still hits the Firebase guard -------------------
    # Firebase is unconfigured in this harness (lifespan skipped) -> 503;
    # if a stray default app exists it would be 401. Both prove the bypass
    # did NOT accept a non-mock token.
    r = client.post(
        "/users/",
        json={"name": "Nope", "email": "nope@x.dev"},
        headers=PLAIN_HEADERS,
    )
    check("non-mock token rejected (401/503, no bypass)",
          r.status_code in (401, 503), str(r.status_code))

    # --- 3. Listing via mock token -> seller_trust_score on create ---------
    r = client.post(
        "/products/",
        json={
            "title": "Calculus Textbook",
            "description": "Barely used, great shape",
            "condition": "Like New",
            "image_url": "https://cdn.example.com/book.jpg",
            "listed_price": 45.0,
        },
        headers=MOCK_HEADERS,
    )
    body = r.json()
    print("        create listing response:", body)
    check("POST /products/ via mock token -> 201", r.status_code == 201,
          str(r.status_code))
    check("create response has seller_trust_score = 5.0 (default)",
          body.get("seller_trust_score") == 5.0,
          str(body.get("seller_trust_score")))
    check("AI status = 'active'", body.get("status") == "active",
          str(body.get("status")))

    # --- 4. List feed: every item carries the trust field ------------------
    r = client.get("/products/")
    items = r.json()
    print("        feed trust scores:",
          [i.get("seller_trust_score") for i in items])
    check("GET /products/ -> 200", r.status_code == 200, str(r.status_code))
    check("feed non-empty", len(items) >= 1, f"{len(items)} items")
    check("every feed item exposes seller_trust_score",
          all("seller_trust_score" in i for i in items),
          str([i.get("seller_trust_score") for i in items]))

    # --- 5. Detail reads are feed-based by design ---------------------------
    # There is intentionally NO GET /products/{id} route: the Flutter app
    # opens ProductDetailScreen with the Product object selected from the
    # feed (which already carries seller_trust_score). Covered by check 4.

    # --- 6. Public profile lookup (trust score is public) ------------------
    r = client.get("/users/dev-mock-user")
    body = r.json()
    check("GET /users/dev-mock-user -> 200", r.status_code == 200,
          str(r.status_code))
    check("profile trust_score = 5.0", body.get("trust_score") == 5.0,
          str(body.get("trust_score")))

    print(f"\n{passed}/{passed + failed} checks passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
