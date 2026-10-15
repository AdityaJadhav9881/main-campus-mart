"""
test_ai_pipeline.py - Phase 3 verification harness (manual test).

Verifies the LangGraph pipeline end-to-end against the REAL API stack:
Firebase auth is bypassed via a mocked token verification, while everything
else is production code - FastAPI, SQLAlchemy, PostgreSQL, and LangGraph.

What it checks:
    1. POST /users/  creates the test seller's profile (idempotent).
    2. Clean listing ("book" + "Like New"):
         -> category "Academic Material", suggested_price 80.0, status "active"
    3. Fraud listing ("free money" + "urgent wire transfer"):
         -> status "flagged" (and hidden from the public feed)
    4. Non-book listing without age:
         -> category "Electronics", price from the condition table
    5. GET /products/ serves ONLY active listings.

Prerequisites (run these first):
    1. From the repo root : docker compose up -d      # start PostgreSQL
    2. From /backend       : pip install -r requirements.txt

Run (from /backend):
    python test_ai_pipeline.py

Exit code 0 = all checks passed; 1 = at least one check failed.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

# Mocked identity: the endpoint still calls verify_firebase_token, but token
# verification is replaced so no real Firebase project/key is required.
MOCK_TOKEN = {"uid": "ai_pipeline_test_seller", "email": "seller@uni.edu"}
HEADERS = {"Authorization": "Bearer local-test-token"}

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
    # `with TestClient(app)` runs the FastAPI lifespan:
    #   init_firebase() + Base.metadata.create_all() against PostgreSQL.
    with TestClient(app) as client:
        with patch(
            "firebase_admin.auth.verify_id_token", return_value=MOCK_TOKEN
        ):
            # --- 1. Ensure the test seller has a profile ---------------------
            r = client.post(
                "/users/",
                json={"name": "AI Pipeline Tester", "email": "seller@uni.edu"},
                headers=HEADERS,
            )
            check("POST /users/ profile ready", r.status_code in (200, 201),
                  str(r.status_code))

            # --- 2. Clean academic listing -----------------------------------
            r = client.post(
                "/products/",
                json={
                    "title": "Calculus Textbook",
                    "description": "Barely used, great shape",
                    "category": "IGNORED-CLIENT-CATEGORY",  # AI must override
                    "condition": "Like New",
                    "age": "1 year",
                    "image_url": "https://cdn.example.com/book.jpg",
                    "listed_price": 45.0,
                },
                headers=HEADERS,
            )
            body = r.json()
            print("        clean listing response:", body)
            check("clean listing -> 201", r.status_code == 201, str(r.status_code))
            check("AI category = 'Academic Material'",
                  body.get("category") == "Academic Material",
                  str(body.get("category")))
            check("suggested_price = 80.0 (Like New = 80% of base)",
                  body.get("suggested_price") == 80.0,
                  str(body.get("suggested_price")))
            check("status = 'active'", body.get("status") == "active",
                  str(body.get("status")))

            # --- 3. Fraud listing --------------------------------------------
            r = client.post(
                "/products/",
                json={
                    "title": "Cheap Laptop",
                    "description": "Send free money now via urgent wire transfer",
                    "condition": "good",
                    "age": "2 years",
                    "image_url": "https://cdn.example.com/laptop.jpg",
                    "listed_price": 300.0,
                },
                headers=HEADERS,
            )
            body = r.json()
            print("        fraud listing response:", body)
            check("fraud listing -> 201", r.status_code == 201, str(r.status_code))
            check("status = 'flagged'", body.get("status") == "flagged",
                  str(body.get("status")))
            check("suggested_price = 60.0 (good = 60% of base)",
                  body.get("suggested_price") == 60.0,
                  str(body.get("suggested_price")))

            # --- 4. Non-book listing, no age ---------------------------------
            r = client.post(
                "/products/",
                json={
                    "title": "HP Calculator",
                    "description": "works fine",
                    "condition": "fair",
                    "image_url": "https://cdn.example.com/calc.jpg",
                    "listed_price": 15.0,
                },
                headers=HEADERS,
            )
            body = r.json()
            check("listing without age -> 201", r.status_code == 201,
                  str(r.status_code))
            check("category = 'Electronics'", body.get("category") == "Electronics",
                  str(body.get("category")))
            check("suggested_price = 40.0 (fair = 40% of base)",
                  body.get("suggested_price") == 40.0,
                  str(body.get("suggested_price")))

        # --- 5. Public feed serves active listings only ----------------------
        r = client.get("/products/")
        titles = [item["title"] for item in r.json()]
        print("        public feed titles:", titles)
        check("flagged listing hidden from public feed",
              "Cheap Laptop" not in titles, str(titles))
        check("clean listing visible in public feed",
              "Calculus Textbook" in titles, str(titles))

    print(f"\n{passed}/{passed + failed} checks passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
