"""
test_admin_master_crud.py - pytest suite for Master Admin CRUD/override
endpoints (users, products, transactions, chat moderation).

Offline by design (in-memory SQLite + dependency override, no external keys):
    /backend$ pytest -q test_admin_master_crud.py
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    ActionOTP,
    AiChatMessage,
    AiChatSession,
    CartItem,
    ChatMessage,
    EmailOTP,
    Notification,
    Product,
    Transaction,
    User,
)

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
    db = TestingSessionLocal()
    try:
        db.query(ChatMessage).delete()
        db.query(Notification).delete()
        db.query(CartItem).delete()
        db.query(Transaction).delete()
        db.query(Product).delete()
        db.query(AiChatMessage).delete()
        db.query(AiChatSession).delete()
        db.query(ActionOTP).delete()
        db.query(EmailOTP).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


COEP = "COEP Technological University, Pune"
VIT = "Vishwakarma Institute of Technology, Pune"
PICT = "Pune Institute of Computer Technology, Pune"
ADMIN_EMAIL = "martaicampus@gmail.com"


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


def _chat(client, headers, product_id, receiver_id, message) -> dict:
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


def _purchase(client, headers, product_id, **overrides) -> dict:
    payload = {
        "delivery_address": "Hostel B-204, COEP Campus",
        "hostel_or_landmark": "Main Gate Fountain",
        "contact_phone": "9876543210",
        "payment_method": "gpay_upi",
        "upi_reference": "UTR-445566",
        "otp_code": "123456",
        "notes": "Please bring the dongle too.",
    }
    payload.update(overrides)
    response = client.post(
        f"/products/{product_id}/purchase", json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


# =============================================================================
# Task 1 - user override + delete
# =============================================================================
def test_patch_user_updates_profile_fields(client):
    student = _register(client, "Old Name", "fields.t1@example.com")
    user_id = student["user"]["id"]

    response = client.patch(
        f"/admin/users/{user_id}",
        json={
            "name": "Corrected Name",
            "phone": "9123456780",
            "trust_score": 4.25,
            "status": "blocked",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Corrected Name"
    assert body["phone"] == "9123456780"
    assert body["trust_score"] == 4.25
    assert body["status"] == "blocked"

    # Round-trips through the dashboard list too.
    users = client.get("/admin/users").json()
    row = next(u for u in users if u["id"] == user_id)
    assert row["name"] == "Corrected Name"
    assert row["phone"] == "9123456780"
    assert row["status"] == "blocked"


def test_patch_user_email_conflict(client):
    first = _register(client, "First", "first.t1@example.com")
    _register(client, "Second", "second.t1@example.com")

    response = client.patch(
        f"/admin/users/{first['user']['id']}",
        json={"email": "second.t1@example.com"},
    )
    assert response.status_code == 409, response.text
    assert "already uses" in response.json()["detail"]

    # A free email is accepted.
    ok = client.patch(
        f"/admin/users/{first['user']['id']}",
        json={"email": "first.renamed@example.com"},
    )
    assert ok.status_code == 200
    assert ok.json()["email"] == "first.renamed@example.com"


def test_patch_user_new_password_roundtrip(client):
    _register(client, "Pass User", "pass.t1@example.com", password="campuspass123")

    old_login = client.post(
        "/auth/login",
        json={"email": "pass.t1@example.com", "password": "campuspass123"},
    )
    assert old_login.status_code == 200

    user_id = old_login.json()["user"]["id"]
    patch = client.patch(
        f"/admin/users/{user_id}",
        json={"new_password": "newcampus999"},
    )
    assert patch.status_code == 200, patch.text

    stale = client.post(
        "/auth/login",
        json={"email": "pass.t1@example.com", "password": "campuspass123"},
    )
    assert stale.status_code == 401, stale.text

    fresh = client.post(
        "/auth/login",
        json={"email": "pass.t1@example.com", "password": "newcampus999"},
    )
    assert fresh.status_code == 200, fresh.text


def test_patch_user_college_cascade_and_opt_out(client):
    seller = _register(
        client, "Cascade Seller", "cascade.t1@example.com",
        college_name=COEP, college_code="6006",
    )
    seller_id = seller["user"]["id"]
    listing = _create_listing(client, seller["headers"], "Lab Coat", 350.0)

    # Default cascade: correcting the college re-stamps their listings.
    patch = client.patch(
        f"/admin/users/{seller_id}",
        json={"college_name": VIT, "college_code": "6273"},
    )
    assert patch.status_code == 200
    assert patch.json()["college_name"] == VIT

    listings = client.get("/admin/listings").json()
    row = next(item for item in listings if item["id"] == listing["id"])
    assert row["college_name"] == VIT
    assert row["college_code"] == "6273"

    # Opt-out: user moves college but the listing keeps its campus snapshot.
    patch2 = client.patch(
        f"/admin/users/{seller_id}",
        json={
            "college_name": PICT,
            "college_code": "6271",
            "cascade_college_to_products": False,
        },
    )
    assert patch2.status_code == 200
    assert patch2.json()["college_name"] == PICT

    listings2 = client.get("/admin/listings").json()
    row2 = next(item for item in listings2 if item["id"] == listing["id"])
    assert row2["college_name"] == VIT
    assert row2["college_code"] == "6273"


def test_patch_user_not_found(client):
    response = client.patch(
        "/admin/users/11111111-1111-1111-1111-111111111111",
        json={"name": "Ghost"},
    )
    assert response.status_code == 404


def test_super_admin_reprofile_ok_block_forbidden(client):
    admin = _register(client, "CampusMart Team", ADMIN_EMAIL)
    admin_id = admin["user"]["id"]

    blocked = client.patch(
        f"/admin/users/{admin_id}", json={"status": "blocked"}
    )
    assert blocked.status_code == 403, blocked.text

    renamed = client.patch(
        f"/admin/users/{admin_id}",
        json={
            "name": "CampusMart Operations",
            "college_name": COEP,
            "college_code": "6006",
            "phone": "9800000000",
        },
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "CampusMart Operations"
    assert renamed.json()["status"] == "active"


def test_delete_user_removes_app_data(client):
    seller = _register(client, "Doomed Seller", "doomed.t1@example.com")
    buyer = _register(client, "Doomed Buyer", "doomedbuyer.t1@example.com")
    listing = _create_listing(client, seller["headers"], "Old Fan", 600.0)

    # Buyer leaves a cart item + a chat message behind.
    cart = client.post(f"/cart/{listing['id']}", headers=buyer["headers"])
    assert cart.status_code == 201, cart.text
    _chat(client, buyer["headers"], listing["id"], seller["user"]["id"], "Hi")

    # Delete the BUYER: their cart + messages go with them; the listing stays.
    response = client.delete(f"/admin/users/{buyer['user']['id']}")
    assert response.status_code == 204, response.text

    users = client.get("/admin/users").json()
    assert all(u["id"] != buyer["user"]["id"] for u in users)
    comms = client.get("/admin/communications").json()
    assert comms["count"] == 0
    listings = client.get("/admin/listings").json()
    assert any(item["id"] == listing["id"] for item in listings)

    # Now delete the SELLER: listing goes too (they have no order history).
    response2 = client.delete(f"/admin/users/{seller['user']['id']}")
    assert response2.status_code == 204, response2.text
    listings_after = client.get("/admin/listings").json()
    assert all(item["id"] != listing["id"] for item in listings_after)


def test_delete_user_with_history_conflict(client):
    seller = _register(client, "History Seller", "hseller.t1@example.com")
    buyer = _register(client, "History Buyer", "hbuyer.t1@example.com")
    listing = _create_listing(client, seller["headers"], "Sold Cello", 450.0)
    _purchase(client, buyer["headers"], listing["id"])

    buyer_delete = client.delete(f"/admin/users/{buyer['user']['id']}")
    assert buyer_delete.status_code == 409, buyer_delete.text

    seller_delete = client.delete(f"/admin/users/{seller['user']['id']}")
    assert seller_delete.status_code == 409, seller_delete.text


def test_delete_super_admin_forbidden(client):
    admin = _register(client, "CampusMart Team", ADMIN_EMAIL)
    response = client.delete(f"/admin/users/{admin['user']['id']}")
    assert response.status_code == 403, response.text


# =============================================================================
# Task 2 - product override
# =============================================================================
def test_patch_product_fields_and_flag_cycle(client):
    seller = _register(client, "Product Seller", "pseller.t2@example.com")
    listing = _create_listing(client, seller["headers"], "Plain Title", 500.0)

    patch = client.patch(
        f"/admin/products/{listing['id']}",
        json={
            "title": "Corrected Title",
            "listed_price": 1234.0,
            "category": "Electronics",
            "condition": "Like New",
            "ai_condition_notes": "Admin reviewed: no defects found.",
            "is_flagged": True,
            "flag_reason": "Manual counterfeit review",
        },
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["title"] == "Corrected Title"
    assert body["listed_price"] == 1234.0
    assert body["category"] == "Electronics"
    assert body["condition"] == "Like New"
    assert body["status"] == "flagged"
    assert body["trust_reason"] == "Manual counterfeit review"

    cleared = client.patch(
        f"/admin/products/{listing['id']}", json={"is_flagged": False}
    )
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "active"
    assert cleared.json()["trust_reason"] is None


def test_patch_product_reassign_seller(client):
    seller = _register(client, "Wrong Account", "wrong.t2@example.com")
    other = _register(client, "Right Account", "right.t2@example.com")
    listing = _create_listing(client, seller["headers"], "Misposted Item", 700.0)

    response = client.patch(
        f"/admin/products/{listing['id']}",
        json={"seller_id": other["user"]["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["seller_id"] == other["user"]["id"]

    listings = client.get("/admin/listings").json()
    row = next(item for item in listings if item["id"] == listing["id"])
    assert row["seller_email"] == "right.t2@example.com"

    ghost = client.patch(
        f"/admin/products/{listing['id']}",
        json={"seller_id": "22222222-2222-2222-2222-222222222222"},
    )
    assert ghost.status_code == 404

    missing = client.patch(
        "/admin/products/33333333-3333-3333-3333-333333333333",
        json={"title": "Nope"},
    )
    assert missing.status_code == 404


# =============================================================================
# Task 3 - transaction + chat moderation
# =============================================================================
def test_patch_transaction_overrides(client):
    seller = _register(client, "Tx Seller", "txseller.t3@example.com")
    buyer = _register(client, "Tx Buyer", "txbuyer.t3@example.com")
    listing = _create_listing(client, seller["headers"], "Exam Table", 1500.0)
    purchase = _purchase(client, buyer["headers"], listing["id"])
    tx_id = purchase["transaction_id"]

    response = client.patch(
        f"/admin/transactions/{tx_id}",
        json={
            "order_status": "Completed",
            "delivery_address": "New Hostel C-101, COEP Campus",
            "contact_phone": "9000000001",
            "payment_method": "cash_on_meetup",
            "final_price": 1350.0,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_status"] == "Completed"
    assert body["delivery_address"] == "New Hostel C-101, COEP Campus"
    assert body["contact_phone"] == "9000000001"
    assert body["payment_method"] == "cash_on_meetup"
    assert body["final_price"] == 1350.0
    assert body["product_title"] == "Exam Table"

    # The communications monitor sees the corrected order context.
    comms = client.get("/admin/communications").json()
    thread = next(
        t for t in comms["threads"] if t["product"]["id"] == listing["id"]
    )
    assert thread["has_order"] is True
    assert thread["payment_method"] == "cash_on_meetup"
    assert thread["delivery_address"] == "New Hostel C-101, COEP Campus"


def test_delete_message_removes_from_thread(client):
    seller = _register(client, "Del Seller", "delseller.t3@example.com")
    buyer = _register(client, "Del Buyer", "delbuyer.t3@example.com")
    listing = _create_listing(client, seller["headers"], "Chatty Item", 300.0)
    message = _chat(
        client, buyer["headers"], listing["id"], seller["user"]["id"], "Spam?"
    )

    response = client.delete(f"/admin/messages/{message['id']}")
    assert response.status_code == 204, response.text

    comms = client.get("/admin/communications").json()
    assert comms["count"] == 0

    again = client.delete(f"/admin/messages/{message['id']}")
    assert again.status_code == 404


def test_intervene_posts_official_message(client):
    admin = _register(client, "CampusMart Team", ADMIN_EMAIL)
    seller = _register(client, "Intervene Seller", "iseller.t3@example.com")
    buyer = _register(client, "Intervene Buyer", "ibuyer.t3@example.com")
    listing = _create_listing(client, seller["headers"], "Dispute Item", 900.0)
    _chat(client, buyer["headers"], listing["id"], seller["user"]["id"], "Help?")

    response = client.post(
        "/admin/messages/intervene",
        json={
            "product_id": listing["id"],
            "receiver_id": buyer["user"]["id"],
            "message": "CampusMart support: please share handover proof.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["sender_id"] == admin["user"]["id"]
    assert body["message"] == "CampusMart support: please share handover proof."

    comms = client.get("/admin/communications").json()
    thread = next(
        t for t in comms["threads"] if t["product"]["id"] == listing["id"]
    )
    assert thread["message_count"] == 2
    assert thread["last_message"] == (
        "CampusMart support: please share handover proof."
    )
    assert thread["messages"][-1]["sender_name"] == "CampusMart Team"

    bell = client.get("/notifications", headers=buyer["headers"]).json()
    titles = [n["title"] for n in bell["notifications"]]
    assert any("Official message from CampusMart Team" in t for t in titles)


def test_intervene_requires_admin_account(client):
    seller = _register(client, "No Admin Seller", "noadmin.t3@example.com")
    buyer = _register(client, "No Admin Buyer", "noadminbuyer.t3@example.com")
    listing = _create_listing(client, seller["headers"], "Lonely Item", 200.0)

    response = client.post(
        "/admin/messages/intervene",
        json={
            "product_id": listing["id"],
            "receiver_id": buyer["user"]["id"],
            "message": "Hello from the void",
        },
    )
    assert response.status_code == 409, response.text
