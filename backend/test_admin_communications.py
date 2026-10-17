"""
test_admin_communications.py - pytest suite for the Admin Communications
task (T1 dashboard college serialization + T2 thread monitor).

Offline by design (in-memory SQLite + dependency override, AUTH_DEV_BYPASS
mock tokens, no Brevo/Cloudinary/vision keys):

    T1 - /admin/users & /admin/listings fill NULL college fields with a
         deterministic REAL CET college; real colleges are preserved.
    T2 - GET /admin/communications groups chat_messages + transactions into
         (product, buyer, seller) threads with order context.

Run (from /backend):
    pytest -q test_admin_communications.py
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cet_colleges import get_college_by_code
from app.database import Base, get_db
from app.main import app
from app.models import (
    CartItem,
    ChatMessage,
    Notification,
    Product,
    Transaction,
    User,
)

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
    # /admin/communications returns EVERY thread, so each test starts from an
    # empty database (FK-safe delete order: children first).
    db = TestingSessionLocal()
    try:
        db.query(ChatMessage).delete()
        db.query(Notification).delete()
        db.query(CartItem).delete()
        db.query(Transaction).delete()
        db.query(Product).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


COEP = "COEP Technological University, Pune"


def _register(
    client: TestClient,
    name: str,
    email: str,
    password: str = "campuspass123",
    college_name: str | None = None,
    college_code: str | None = None,
) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": password,
            "college_name": college_name,
            "college_code": college_code,
        },
    )
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


def _chat(
    client: TestClient,
    headers: dict,
    product_id: str,
    receiver_id: str,
    message: str,
) -> dict:
    response = client.post(
        "/chats/messages",
        json={
            "product_id": product_id,
            "receiver_id": receiver_id,
            "message": message,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# =============================================================================
# T1 - deterministic college defaults on admin views
# =============================================================================
def test_admin_users_fill_null_college_deterministically(client):
    legacy = _register(client, "Legacy Kumar", "legacy.t1@example.com")
    assert legacy["user"]["college_name"] is None

    first = client.get("/admin/users").json()
    row = next(u for u in first if u["email"] == "legacy.t1@example.com")
    assert row["college_name"]
    assert row["college_code"]
    catalog = get_college_by_code(row["college_code"])
    assert catalog is not None
    assert catalog.name == row["college_name"]

    # Same account -> same campus on every reload (deterministic default).
    second = client.get("/admin/users").json()
    row_again = next(u for u in second if u["email"] == "legacy.t1@example.com")
    assert row_again["college_name"] == row["college_name"]
    assert row_again["college_code"] == row["college_code"]


def test_admin_users_preserve_real_college(client):
    _register(
        client, "Riya Shah", "riya.t1@example.com",
        college_name=COEP, college_code="6006",
    )
    users = client.get("/admin/users").json()
    row = next(u for u in users if u["email"] == "riya.t1@example.com")
    assert row["college_name"] == COEP
    assert row["college_code"] == "6006"


def test_admin_status_patch_returns_college_filled(client):
    student = _register(client, "Blocked Guy", "blocked.t1@example.com")
    response = client.patch(
        f"/admin/users/{student['user']['id']}/status",
        json={"status": "blocked"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blocked"
    assert body["college_name"]  # filled for the dashboard
    assert body["college_code"]


def test_admin_listings_fill_null_college_from_seller(client):
    seller = _register(client, "Null Seller", "nullseller.t1@example.com")
    listing = _create_listing(client, seller["headers"], "Study Lamp", 450.0)

    listings = client.get("/admin/listings").json()
    row = next(item for item in listings if item["id"] == listing["id"])
    assert row["college_name"]
    assert row["college_code"]

    # Must match the seller's own deterministic default (single story per
    # student across the dashboard).
    users = client.get("/admin/users").json()
    seller_row = next(u for u in users if u["email"] == "nullseller.t1@example.com")
    assert row["college_name"] == seller_row["college_name"]
    assert row["college_code"] == seller_row["college_code"]


def test_admin_listings_preserve_real_college(client):
    seller = _register(
        client, "Real Seller", "realseller.t1@example.com",
        college_name=COEP, college_code="6006",
    )
    listing = _create_listing(client, seller["headers"], "Cycle Helmet", 700.0)
    listings = client.get("/admin/listings").json()
    row = next(item for item in listings if item["id"] == listing["id"])
    assert row["college_name"] == COEP
    assert row["college_code"] == "6006"


# =============================================================================
# T2 - GET /admin/communications
# =============================================================================
def test_communications_thread_with_order_and_call(client):
    seller = _register(
        client, "Arjun Seller", "arjun.t2@example.com",
        college_name=COEP, college_code="6006",
    )
    buyer = _register(client, "Priya Buyer", "priya.t2@example.com")

    listing = _create_listing(client, seller["headers"], "Gaming Mouse", 900.0)
    seller_id = seller["user"]["id"]
    buyer_id = buyer["user"]["id"]

    _chat(
        client, buyer["headers"], listing["id"], seller_id,
        "Is the dongle included?",
    )
    _chat(
        client, seller["headers"], listing["id"], buyer_id,
        "Yes - dongle, box and bill included.",
    )
    call = client.post(
        "/chats/call-event",
        json={
            "product_id": listing["id"],
            "receiver_id": seller_id,
            "call_type": "voice",
            "status": "completed",
            "duration_seconds": 84,
        },
        headers=buyer["headers"],
    )
    assert call.status_code == 201, call.text

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

    body = client.get("/admin/communications").json()
    assert body["count"] == 1
    thread = body["threads"][0]

    assert thread["id"] == f"{listing['id']}:{buyer_id}:{seller_id}"
    assert thread["buyer"]["id"] == buyer_id
    assert thread["buyer"]["name"] == "Priya Buyer"
    assert thread["buyer"]["college_name"]  # deterministic default filled
    assert thread["buyer"]["college_code"]
    assert thread["seller"]["name"] == "Arjun Seller"
    assert thread["seller"]["college_name"] == COEP
    assert thread["seller"]["college_code"] == "6006"
    assert thread["seller"]["trust_score"] is not None

    assert thread["product"]["id"] == listing["id"]
    assert thread["product"]["title"] == "Gaming Mouse"
    assert thread["product"]["listed_price"] == 900.0
    assert thread["product"]["price"] == 900.0
    assert thread["product"]["status"] == "sold"
    assert thread["product"]["college_name"] == COEP

    assert thread["message_count"] == 4  # 2 chats + call bubble + order card
    assert thread["call_count"] == 1
    assert thread["has_order"] is True
    assert thread["payment_method"] == "gpay_upi"
    assert thread["delivery_address"] == "Hostel B-204, COEP Campus"
    assert thread["order_status"] == "Requested / Processing"
    assert thread["order"] is not None
    assert thread["order"]["delivery_address"] == "Hostel B-204, COEP Campus"
    assert thread["order"]["final_price"] == 900.0
    assert thread["last_message"].startswith("📦 NEW ORDER PLACED")
    assert (
        thread["last_updated"] >= thread["messages"][-1]["created_at"]
    )

    messages = thread["messages"]
    assert len(messages) == 4
    assert messages[0]["message"] == "Is the dongle included?"
    assert messages[0]["sender_name"] == "Priya Buyer"
    assert messages[0]["sender_id"] == buyer_id
    assert messages[0]["receiver_id"] == seller_id
    assert messages[0]["is_call_log"] is False
    assert messages[1]["message"].startswith("Yes - dongle")
    assert messages[1]["sender_name"] == "Arjun Seller"
    assert messages[2]["message"].startswith("📞 Voice call")
    assert messages[2]["sender_id"] == buyer_id
    assert messages[2]["is_call_log"] is True
    assert messages[3]["is_order_card"] is True


def test_communications_chat_only_thread(client):
    seller = _register(client, "Solo Seller", "solo.t2@example.com")
    buyer = _register(client, "Query Buyer", "query.t2@example.com")
    listing = _create_listing(client, seller["headers"], "Casio FX-991ES", 800.0)

    _chat(
        client, buyer["headers"], listing["id"],
        seller["user"]["id"], "Still available?",
    )

    body = client.get("/admin/communications").json()
    assert body["count"] == 1
    thread = body["threads"][0]
    assert thread["has_order"] is False
    assert thread["payment_method"] is None
    assert thread["delivery_address"] is None
    assert thread["message_count"] == 1
    assert thread["call_count"] == 0
    assert thread["last_message"] == "Still available?"


def test_communications_two_directions_build_one_thread(client):
    seller = _register(client, "One Seller", "oneseller.t2@example.com")
    buyer = _register(client, "One Buyer", "onebuyer.t2@example.com")
    listing = _create_listing(client, seller["headers"], "Drafter Table", 1200.0)

    _chat(client, buyer["headers"], listing["id"], seller["user"]["id"], "Hi!")
    _chat(client, seller["headers"], listing["id"], buyer["user"]["id"], "Hello!")

    body = client.get("/admin/communications").json()
    assert body["count"] == 1  # not two half-threads
    assert body["threads"][0]["message_count"] == 2
    assert body["threads"][0]["id"] == (
        f"{listing['id']}:{buyer['user']['id']}:{seller['user']['id']}"
    )


def test_communications_sorted_newest_first(client):
    seller = _register(client, "Sort Seller", "sortseller.t2@example.com")
    buyer = _register(client, "Sort Buyer", "sortbuyer.t2@example.com")
    first = _create_listing(client, seller["headers"], "Item One", 100.0)
    second = _create_listing(client, seller["headers"], "Item Two", 200.0)

    _chat(client, buyer["headers"], first["id"], seller["user"]["id"], "One")
    time.sleep(0.02)
    _chat(client, buyer["headers"], second["id"], seller["user"]["id"], "Two")

    body = client.get("/admin/communications").json()
    assert body["count"] == 2
    assert body["threads"][0]["product"]["id"] == second["id"]
    assert body["threads"][1]["product"]["id"] == first["id"]
    assert (
        body["threads"][0]["last_updated"]
        >= body["threads"][1]["last_updated"]
    )


def test_communications_empty_database(client):
    body = client.get("/admin/communications").json()
    assert body == {"threads": [], "count": 0}
