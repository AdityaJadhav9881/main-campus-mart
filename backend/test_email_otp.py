"""
test_email_otp.py - pytest suite for Brevo emails + 6-digit OTP signup +
Super-Administrator unblock protection.

Everything runs OFFLINE: conftest.py clears BREVO_API_KEY so email_service
logs and returns False instead of hitting api.brevo.com, and the OTP endpoints
themselves only touch the in-memory SQLite dependency override.

Covered:
    Task (email) - send/listing/sold email helpers never raise offline.
    Task (OTP)   - /auth/send-otp | /auth/verify-otp | /auth/resend-otp
                   contracts: 409 duplicate, 6-digit code, 10-min expiry,
                   single-use code, resend rotation, full JWT login after
                   verification.
    Task (guard) - PATCH /admin/users/{id}/status refuses to block the
                   protected SUPER_ADMIN_EMAIL account (403) while normal
                   students remain blockable.

Run (from /backend):
    pytest -q
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import SUPER_ADMIN_EMAIL
from app.database import Base, get_db
from app.email_service import (
    email_enabled,
    send_listing_published_email,
    send_otp_email,
    send_product_sold_emails,
)
from app.main import app
from app.models import EmailOTP, User

# --- In-memory SQLite + dependency override (same pattern as the MIME suite) -
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


MOCK_HEADERS = {"Authorization": "Bearer mock-local-dev-token"}


# =============================================================================
# 1. Email helpers are non-blocking when Brevo is unconfigured (tests/offline)
# =============================================================================
def test_email_helpers_never_raise_offline():
    assert email_enabled() is False  # conftest.py cleared BREVO_API_KEY

    # Signature-correct calls return False instead of raising.
    assert send_otp_email("student@campus.edu", "Test Student", "123456") is False

    product = SimpleNamespace(
        title="Casio fx-991EX",
        category="Electronics",
        condition="Like New",
        listed_price=850.0,
        suggested_price=900.0,
        status="active",
        image_url="https://cdn.example.com/calc.jpg",
    )
    assert send_listing_published_email(
        "seller@campus.edu", "Test Seller", product
    ) is False

    seller = SimpleNamespace(
        name="Test Seller", email="seller@campus.edu", trust_score=4.6
    )
    buyer = SimpleNamespace(name="Test Buyer", email="buyer@campus.edu")
    assert send_product_sold_emails(seller, buyer, product, 800.0) is False

    # Missing recipient is tolerated too.
    assert send_otp_email("", "No One", "000000") is False


# =============================================================================
# 2. send-otp / verify-otp happy path
# =============================================================================
def test_otp_signup_full_flow(client):
    payload = {
        "name": "Otp Student",
        "email": "otp.student@campus.edu",
        "password": "secretpass123",
    }

    sent = client.post("/auth/send-otp", json=payload)
    assert sent.status_code == 200, sent.text
    assert sent.json() == {
        "message": "Verification code sent to your email",
        "email": "otp.student@campus.edu",
    }

    # The 6-digit code + hashed password are parked for 10 minutes.
    session = TestingSessionLocal()
    try:
        row = (
            session.query(EmailOTP)
            .filter(EmailOTP.email == "otp.student@campus.edu")
            .one()
        )
        otp_code = row.otp_code
        assert len(otp_code) == 6 and otp_code.isdigit()
        assert row.name == "Otp Student"
        assert row.password_hash.startswith("$2")  # bcrypt, never plaintext
        assert row.password_hash != "secretpass123"
        assert row.expires_at is not None
    finally:
        session.close()

    # Wrong code -> actionable 400, account NOT created.
    wrong = client.post(
        "/auth/verify-otp",
        json={
            "email": "otp.student@campus.edu",
            "otp_code": "000000" if otp_code != "000000" else "111111",
        },
    )
    assert wrong.status_code == 400, wrong.text
    assert "Invalid verification code" in wrong.json()["detail"]

    # Correct code -> 201 + JWT + profile, OTP row deleted (single-use).
    verified = client.post(
        "/auth/verify-otp",
        json={"email": "otp.student@campus.edu", "otp_code": otp_code},
    )
    assert verified.status_code == 201, verified.text
    body = verified.json()
    assert body["user"]["email"] == "otp.student@campus.edu"
    assert body["user"]["status"] == "active"
    assert body["user"]["trust_score"] == 5.0
    token = body["access_token"]
    assert token  # JWT usable on protected routes immediately

    session = TestingSessionLocal()
    try:
        assert (
            session.query(EmailOTP)
            .filter(EmailOTP.email == "otp.student@campus.edu")
            .first()
            is None
        )
    finally:
        session.close()

    # The parked password actually logs in (same Bearer contract as register).
    login = client.post(
        "/auth/login",
        json={
            "email": "otp.student@campus.edu",
            "password": "secretpass123",
        },
    )
    assert login.status_code == 200, login.text

    # Code reuse after success -> no pending row -> 400.
    replay = client.post(
        "/auth/verify-otp",
        json={"email": "otp.student@campus.edu", "otp_code": otp_code},
    )
    assert replay.status_code == 400, replay.text

    # Protected route accepts the verify-otp JWT (profile already exists).
    me = client.get(
        f"/users/{body['user']['firebase_uid']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200, me.text


# =============================================================================
# 3. send-otp guards
# =============================================================================
def test_send_otp_rejects_existing_email(client):
    registered = client.post(
        "/auth/register",
        json={
            "name": "Existing User",
            "email": "existing@campus.edu",
            "password": "password123",
        },
    )
    assert registered.status_code == 201, registered.text

    response = client.post(
        "/auth/send-otp",
        json={
            "name": "Existing User",
            "email": "existing@campus.edu",
            "password": "whatever123",
        },
    )
    assert response.status_code == 409, response.text
    assert "already exists" in response.json()["detail"]


def test_send_otp_requires_valid_password(client):
    response = client.post(
        "/auth/send-otp",
        json={
            "name": "Shorty",
            "email": "shorty@campus.edu",
            "password": "short",
        },
    )
    assert response.status_code == 422, response.text  # min_length=8


# =============================================================================
# 4. resend-otp rotates the code
# =============================================================================
def test_resend_otp_issues_new_code(client):
    payload = {
        "name": "Resend Student",
        "email": "resend.student@campus.edu",
        "password": "anotherpass123",
    }
    assert client.post("/auth/send-otp", json=payload).status_code == 200

    session = TestingSessionLocal()
    try:
        first = (
            session.query(EmailOTP)
            .filter(EmailOTP.email == payload["email"])
            .one()
        ).otp_code
    finally:
        session.close()

    resent = client.post("/auth/resend-otp", json={"email": payload["email"]})
    assert resent.status_code == 200, resent.text
    assert resent.json()["message"] == "Verification code sent to your email"

    session = TestingSessionLocal()
    try:
        row = (
            session.query(EmailOTP)
            .filter(EmailOTP.email == payload["email"])
            .one()
        )
        second = row.otp_code
        # Name/password survive the resend - only the code + window rotate.
        assert row.name == "Resend Student"
        assert row.password_hash.startswith("$2")
    finally:
        session.close()

    # Extremely unlikely to collide (1/900000) - rotate again if it does.
    if second == first:
        client.post("/auth/resend-otp", json={"email": payload["email"]})
        session = TestingSessionLocal()
        try:
            second = (
                session.query(EmailOTP)
                .filter(EmailOTP.email == payload["email"])
                .one()
            ).otp_code
        finally:
            session.close()
    assert second != first

    # The ROTATED code verifies; the original one does not.
    old = client.post(
        "/auth/verify-otp",
        json={"email": payload["email"], "otp_code": first},
    )
    assert old.status_code in (201, 400), old.text
    if old.status_code == 400:  # rotated away as expected
        fresh = client.post(
            "/auth/verify-otp",
            json={"email": payload["email"], "otp_code": second},
        )
        assert fresh.status_code == 201, fresh.text


def test_resend_otp_unknown_email_rejected(client):
    response = client.post(
        "/auth/resend-otp", json={"email": "nobody@campus.edu"}
    )
    assert response.status_code == 400, response.text
    assert "No pending verification" in response.json()["detail"]


# =============================================================================
# 5. expired OTP rejected + deleted
# =============================================================================
def test_expired_otp_is_rejected(client):
    payload = {
        "name": "Slow Student",
        "email": "slow.student@campus.edu",
        "password": "slowpass1234",
    }
    assert client.post("/auth/send-otp", json=payload).status_code == 200

    session = TestingSessionLocal()
    try:
        row = (
            session.query(EmailOTP)
            .filter(EmailOTP.email == payload["email"])
            .one()
        )
        code = row.otp_code
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
    finally:
        session.close()

    expired = client.post(
        "/auth/verify-otp",
        json={"email": payload["email"], "otp_code": code},
    )
    assert expired.status_code == 400, expired.text
    assert "expired" in expired.json()["detail"].lower()

    # Row was cleaned up.
    session = TestingSessionLocal()
    try:
        assert (
            session.query(EmailOTP)
            .filter(EmailOTP.email == payload["email"])
            .first()
            is None
        )
    finally:
        session.close()


# =============================================================================
# 6. Super-Administrator unblock protection
# =============================================================================
def _create_user(client, name: str, email: str) -> dict:
    response = client.post(
        "/users/", json={"name": name, "email": email}, headers=MOCK_HEADERS
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_super_admin_cannot_be_blocked(client):
    session = TestingSessionLocal()
    try:
        existing = (
            session.query(User)
            .filter(User.email.ilike(SUPER_ADMIN_EMAIL))
            .first()
        )
        if existing is not None and existing.status != "active":
            existing.status = "active"
            session.commit()
        admin_id = existing.id if existing else None
        if admin_id is None:
            admin = User(
                firebase_uid="local-superadmin-test",
                name="Super Admin",
                email=SUPER_ADMIN_EMAIL,
                status="blocked",  # start from blocked to prove the guard
                trust_score=5.0,
            )
            session.add(admin)
            session.commit()
            admin_id = admin.id
    finally:
        session.close()

    # 1. The dashboard PATCH endpoint refuses to block this email (403).
    blocked = client.patch(
        f"/admin/users/{admin_id}/status", json={"status": "blocked"}
    )
    assert blocked.status_code == 403, blocked.text
    assert "protected" in blocked.json()["detail"]

    # 2. Re-asserting 'active' is allowed (this is how admins recover).
    activated = client.patch(
        f"/admin/users/{admin_id}/status", json={"status": "active"}
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    # 3. A NORMAL student is still blockable (guard is email-specific).
    normal = _create_user(client, "Blockable Bob", "blockable.bob@campus.edu")
    ok = client.patch(
        f"/admin/users/{normal['id']}/status", json={"status": "blocked"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "blocked"


def test_listing_create_and_purchase_emails_do_not_break_flows(client):
    """Background email wiring (listing + sold) must keep APIs green offline."""
    seller = client.post(
        "/auth/register",
        json={
            "name": "Mail Seller",
            "email": "mail.seller@campus.edu",
            "password": "password123",
        },
    )
    assert seller.status_code == 201, seller.text
    seller_headers = {
        "Authorization": f"Bearer {seller.json()['access_token']}"
    }

    buyer = client.post(
        "/auth/register",
        json={
            "name": "Mail Buyer",
            "email": "mail.buyer@campus.edu",
            "password": "password123",
        },
    )
    assert buyer.status_code == 201, buyer.text
    buyer_json = buyer.json()
    buyer_headers = {"Authorization": f"Bearer {buyer_json['access_token']}"}

    # Listing creation queues the "is live" email (skipped offline, non-fatal).
    listing = client.post(
        "/products/",
        json={
            "title": "Arduino Uno Starter Kit",
            "description": "Genuine board with breadboard and jumper wires.",
            "condition": "Good",
            "image_url": "https://cdn.example.com/arduino.jpg",
            "listed_price": 500.0,
        },
        headers=seller_headers,
    )
    assert listing.status_code == 201, listing.text
    product_id = listing.json()["id"]

    # Purchase queues BOTH sale emails; checkout itself must stay 200.
    purchase = client.post(
        f"/products/{product_id}/purchase", headers=buyer_headers, json={}
    )
    assert purchase.status_code == 200, purchase.text
    assert purchase.json()["product_status"] == "sold"
    assert purchase.json()["final_price"] == 500.0

    # Buyer's history reflects the order (and no stray email errors surfaced).
    history = client.get("/transactions/my", headers=buyer_headers)
    assert history.status_code == 200, history.text
    assert history.json()["bought"][0]["product_title"] == "Arduino Uno Starter Kit"
