"""
test_college_network_upgrade.py - pytest suite for the college network +
order handover release (A1-A6).

Offline by design (in-memory SQLite via the dependency override, no Brevo key
-> fallback OTP codes returned, no vision key -> catalog assistant):

    A1 - GET /colleges search/city/custom + college fields on register.
    A2 - POST /auth/send-action-otp + /auth/verify-action-otp.
    A3 - POST /ai/chat session persistence + /ai/sessions CRUD.
    A4 - Same-college listing notifications + order/chat notifications.
    A5 - Cart CRUD + structured checkout (order card + notifications).
    A6 - POST /chats/call-event call bubbles.

Run (from /backend):
    pytest -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# --- In-memory SQLite + dependency override (same pattern as the others) -----
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _db_override():
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


COEP = "COEP Technological University, Pune"
VJTI = "Veermata Jijabai Technological Institute (VJTI), Matunga, Mumbai"


def _register(
    client: TestClient,
    name: str,
    email: str,
    password: str = "campuspass123",
    college_name: str | None = None,
    college_code: str | None = None,
) -> dict:
    body = {
        "name": name,
        "email": email,
        "password": password,
        "college_name": college_name,
        "college_code": college_code,
    }
    response = client.post("/auth/register", json=body)
    assert response.status_code == 201, response.text
    payload = response.json()
    return {
        "token": payload["access_token"],
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user": payload["user"],
    }


def _create_listing(client: TestClient, headers: dict, title: str, price: float) -> dict:
    response = client.post(
        "/products/",
        json={
            "title": title,
            "description": f"{title} in good campus condition.",
            "condition": "Good",
            "image_url": "https://cdn.example.com/front.jpg",
            "listed_price": price,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# =============================================================================
# A1 - College directory + register college fields
# =============================================================================
def test_college_search_city_and_custom(client):
    response = client.get("/colleges", params={"q": "coep"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] >= 1
    assert body["colleges"][0]["code"] == "6006"
    assert "COEP" in body["colleges"][0]["short_name"]
    assert body["cities"][0] == "All"

    city = client.get("/colleges", params={"q": "pict", "city": "Pune"}).json()
    assert city["count"] >= 1
    assert city["colleges"][0]["city"] == "Pune"

    custom = client.get(
        "/colleges", params={"q": "Zilla Tech Institute Ulhasnagar", "allow_custom": True}
    ).json()
    assert custom["count"] == 1
    assert custom["colleges"][0]["custom"] is True
    assert "Zilla" in custom["colleges"][0]["name"]


def test_register_stores_college(client):
    student = _register(
        client, "Riya", "riya.a1@example.com",
        college_name=COEP, college_code="6006",
    )
    assert student["user"]["college_name"] == COEP
    assert student["user"]["college_code"] == "6006"


# =============================================================================
# A2 - Action OTP (offline: fallback code returned when Brevo is unkeyed)
# =============================================================================
def test_action_otp_flow(client):
    seller = _register(client, "Aarav", "aarav.a2@example.com", college_name=COEP)

    sent = client.post(
        "/auth/send-action-otp",
        json={"action_type": "sell", "item_title": "Casio FX-991ES"},
        headers=seller["headers"],
    )
    assert sent.status_code == 200, sent.text
    sent_body = sent.json()
    assert sent_body["email_delivered"] is False  # no BREVO_API_KEY in tests
    code = sent_body["fallback_otp_code"]
    assert code and code.isdigit() and len(code) == 6

    wrong = client.post(
        "/auth/verify-action-otp",
        json={"otp_code": "000000", "action_type": "sell"},
        headers=seller["headers"],
    )
    assert wrong.status_code == 400

    ok = client.post(
        "/auth/verify-action-otp",
        json={"otp_code": code, "action_type": "sell"},
        headers=seller["headers"],
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["verified"] is True
    assert body["action_token"]


# =============================================================================
# A3 - Saved AI sessions
# =============================================================================
def test_ai_sessions_created_and_deletable(client):
    headers = _register(client, "Neha", "neha.a3@example.com")["headers"]

    response = client.post(
        "/ai/chat",
        json={"message": "best budget laptop for coding under 30000"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"]
    assert body["session_title"]  # auto 4-word title
    assert body["source"] == "catalog"  # offline fallback

    sessions = client.get("/ai/sessions", headers=headers).json()
    assert len(sessions) == 1
    assert sessions[0]["message_count"] == 2

    detail = client.get(
        f"/ai/sessions/{body['session_id']}", headers=headers
    ).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]

    created = client.post("/ai/sessions", headers=headers)
    assert created.status_code == 201
    assert created.json()["title"] == "New chat"

    deleted = client.delete(
        f"/ai/sessions/{body['session_id']}", headers=headers
    )
    assert deleted.status_code == 204
    gone = client.get(f"/ai/sessions/{body['session_id']}", headers=headers)
    assert gone.status_code == 404


# =============================================================================
# A4 - Same-college listing notification
# =============================================================================
def test_same_college_listing_notification(client):
    seller = _register(
        client, "Kabir", "kabir.a4@example.com",
        college_name=COEP, college_code="6006",
    )
    classmate = _register(
        client, "Isha", "isha.a4@example.com",
        college_name=COEP, college_code="6006",
    )
    outsider = _register(
        client, "Rohan", "rohan.a4@example.com",
        college_name=VJTI, college_code="3012",
    )

    listing = _create_listing(client, seller["headers"], "Drafter Table Lamp", 650.0)
    assert listing["college_name"] == COEP

    classmate_feed = client.get("/notifications/", headers=classmate["headers"]).json()
    assert classmate_feed["unread_count"] == 1
    note = classmate_feed["notifications"][0]
    assert note["type"] == "college_listing"
    assert note["title"] == f"🎓 New at {COEP}"
    assert "Drafter Table Lamp" in note["body"]

    outsider_feed = client.get("/notifications/", headers=outsider["headers"]).json()
    assert outsider_feed["unread_count"] == 0

    read = client.post(
        f"/notifications/{note['id']}/read", headers=classmate["headers"]
    )
    assert read.status_code == 200
    assert read.json()["is_read"] is True
    assert client.get(
        "/notifications/", headers=classmate["headers"]
    ).json()["unread_count"] == 0


# =============================================================================
# A5 - Cart + structured checkout
# =============================================================================
def test_cart_add_remove(client):
    seller = _register(client, "Dev", "dev.a5@example.com")
    buyer = _register(client, "Tara", "tara.a5@example.com")
    listing = _create_listing(client, seller["headers"], "Study Table", 1200.0)

    added = client.post(f"/cart/{listing['id']}", headers=buyer["headers"])
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["count"] == 1
    assert body["total_price"] == 1200.0
    assert body["items"][0]["product"]["title"] == "Study Table"

    again = client.post(f"/cart/{listing['id']}", headers=buyer["headers"])
    assert again.status_code == 201
    assert again.json()["count"] == 1  # idempotent

    removed = client.delete(f"/cart/{listing['id']}", headers=buyer["headers"])
    assert removed.json()["count"] == 0


def test_checkout_with_details_posts_order_card_and_notifies(client):
    seller = _register(client, "Vikram", "vikram.a5@example.com")
    buyer = _register(client, "Mira", "mira.a5@example.com")
    listing = _create_listing(client, seller["headers"], "Gaming Mouse", 900.0)

    client.post(f"/cart/{listing['id']}", headers=buyer["headers"])

    purchase = client.post(
        f"/products/{listing['id']}/purchase",
        json={
            "delivery_address": "Hostel B-204, COEP Campus",
            "hostel_or_landmark": "Main Gate Fountain",
            "contact_phone": "9876543210",
            "payment_method": "gpay_upi",
            "upi_reference": "UTR-445566",
            "otp_code": "123456",
            "notes": "Please bring the dongle too.",
        },
        headers=buyer["headers"],
    )
    assert purchase.status_code == 200, purchase.text
    body = purchase.json()
    assert body["product_status"] == "sold"
    assert body["order_status"] == "Requested / Processing"
    assert body["seller_id"] == seller["user"]["id"]
    assert body["auto_chat_message_id"]

    # Order card landed in the buyer -> seller thread.
    thread = client.get(
        f"/chats/messages/{listing['id']}/{seller['user']['id']}",
        headers=buyer["headers"],
    ).json()
    assert len(thread) == 1
    assert "📦 NEW ORDER PLACED" in thread[0]["message"]
    assert "Gaming Mouse" in thread[0]["message"]
    assert "GPay UPI" in thread[0]["message"]

    # Seller notified with an order_placed alert; cart auto-cleared.
    seller_feed = client.get("/notifications/", headers=seller["headers"]).json()
    assert any(n["type"] == "order_placed" for n in seller_feed["notifications"])
    assert client.get("/cart/", headers=buyer["headers"]).json()["count"] == 0

    # Buying again is refused (listing is sold).
    rebuy = client.post(
        f"/products/{listing['id']}/purchase", headers=buyer["headers"]
    )
    assert rebuy.status_code == 400


# =============================================================================
# A6 - Call events
# =============================================================================
def test_call_event_logs_bubble_and_notification(client):
    seller = _register(client, "Nikhil", "nikhil.a6@example.com")
    buyer = _register(client, "Asha", "asha.a6@example.com")
    listing = _create_listing(client, seller["headers"], "Table Lamp", 400.0)

    response = client.post(
        "/chats/call-event",
        json={
            "product_id": listing["id"],
            "receiver_id": seller["user"]["id"],
            "call_type": "voice",
            "status": "completed",
            "duration_seconds": 84,
        },
        headers=buyer["headers"],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["message"] == "📞 Voice call · 1m 24s"

    feed = client.get("/notifications/", headers=seller["headers"]).json()
    call_notes = [n for n in feed["notifications"] if n["type"] == "call"]
    assert len(call_notes) == 1
    assert "Nikhil" not in call_notes[0]["title"]  # caller is Asha
    assert "Asha" in call_notes[0]["title"]

    missed = client.post(
        "/chats/call-event",
        json={
            "product_id": listing["id"],
            "receiver_id": seller["user"]["id"],
            "call_type": "video",
            "status": "missed",
            "duration_seconds": 0,
        },
        headers=buyer["headers"],
    )
    assert missed.status_code == 201
    assert "Missed" in missed.json()["message"]
