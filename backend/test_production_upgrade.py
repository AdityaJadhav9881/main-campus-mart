"""
test_production_upgrade.py - pytest suite for the 8-task production upgrade.

Covers the behaviors added this round (all offline: in-memory SQLite via the
dependency override, no vision API key -> heuristic path, AUTH_DEV_BYPASS on):

    Task 1/2 - POST /products/analyze-images:
               < 4 photos -> actionable 400; 4 photos -> INR (₹) analysis.
    Task 3   - GET /products/?q=...&category=... feed search/filter.
    Task 4   - Canonical 403 ACCOUNT_TERMINATED on every blocked-account path
               (profile, login, create listing, chat inbox).
    Task 5   - Buyer-seller chat: send, inbox grouping, read-marking; and
               POST /ai/chat catalog-aware assistant fallback (source='catalog').
    Task 7   - GET/PUT /admin/ai-config with masked key (never leaks secrets).

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
from app.models import User

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

# 4 distinct CDN photos (never actually fetched: no API key -> heuristic path
# short-circuits before any download, so these stay offline-friendly).
FOUR_PHOTOS = [
    f"https://cdn.example.com/angle-{index}.jpg" for index in range(1, 5)
]


def _register(client: TestClient, name: str, email: str, password: str) -> dict:
    """Register a campus student; return the API's user object (has .id)."""
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user": body["user"],
    }


def _create_listing(
    client: TestClient,
    headers: dict,
    *,
    title: str,
    description: str,
    condition: str = "Good",
    listed_price: float = 500.0,
    **extra,
) -> dict:
    response = client.post(
        "/products/",
        json={
            "title": title,
            "description": description,
            "condition": condition,
            "image_url": "https://cdn.example.com/front.jpg",
            "listed_price": listed_price,
            **extra,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# =============================================================================
# Task 2 - analyze-images: strict 4-photo gate + INR heuristic
# =============================================================================
def test_analyze_images_rejects_fewer_than_four_photos(client):
    for payload in (
        {"image_urls": []},
        {"image_urls": FOUR_PHOTOS[:1]},
        {"image_urls": FOUR_PHOTOS[:3]},
    ):
        response = client.post(
            "/products/analyze-images", json=payload, headers=MOCK_HEADERS,
        )
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert "at least 4 photos" in detail
        assert "of 4" in detail  # names the shortfall, not a generic error


def test_analyze_images_four_photos_returns_inr_analysis(client):
    response = client.post(
        "/products/analyze-images",
        json={
            "image_urls": FOUR_PHOTOS,
            "title": "Bose SoundLink Flex portable speaker",
            "description": "Waterproof bluetooth speaker, barely used.",
            "condition": "Good",
        },
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["source"] == "heuristic"  # no API key stored in tests
    assert body["category"] == "Electronics"
    assert body["condition"] == "Good"
    # Indian Rupees: used speaker band is ₹4,000-7,500 - never the old "$80".
    assert 3000.0 <= body["suggested_price_inr"] <= 6500.0
    assert body["listed_price_inr"] >= 1000.0
    assert 5 <= len(body["ai_tags"]) <= 20
    assert body["image_urls"] == FOUR_PHOTOS
    assert body["ai_tags"][0] in {"bose", "soundlink"}


# =============================================================================
# Task 3 - feed search (?q=) and category filter (?category=)
# =============================================================================
def test_feed_search_and_category_filters(client):
    client.post(
        "/users/",
        json={"name": "Search Tester", "email": "search.tester@campus.edu"},
        headers=MOCK_HEADERS,
    )
    textbook = _create_listing(
        client,
        MOCK_HEADERS,
        title="Engineering Mathematics Textbook",
        description="B.S. Grewal, one semester of clean use.",
        condition="Like New",
        listed_price=350.0,
        ai_tags="textbook, mathematics, grewal, calculus, exam",
    )
    speaker = _create_listing(
        client,
        MOCK_HEADERS,
        title="Portable party speaker",
        description="Loud bass, weekend events.",
        condition="Good",
        listed_price=2500.0,
        ai_tags="speaker, bluetooth audio, music box, wireless, electronics",
    )

    all_active = client.get("/products/").json()
    assert {p["id"] for p in all_active} >= {textbook["id"], speaker["id"]}

    # ?q= matches ai_tags (semantic synonyms the vision AI stored).
    by_tag = client.get("/products/", params={"q": "bluetooth audio"}).json()
    assert [p["id"] for p in by_tag] == [speaker["id"]]

    by_title = client.get("/products/", params={"q": "mathematics"}).json()
    assert textbook["id"] in {p["id"] for p in by_title}
    assert speaker["id"] not in {p["id"] for p in by_title}

    # ?category= exact, case-insensitive chip filter.
    electronics = client.get(
        "/products/", params={"category": "electronics"}
    ).json()
    assert speaker["id"] in {p["id"] for p in electronics}
    assert textbook["id"] not in {p["id"] for p in electronics}

    # Combined q + category narrows further.
    combined = client.get(
        "/products/", params={"q": "bluetooth", "category": "Academic Material"}
    ).json()
    assert all(p["id"] != speaker["id"] for p in combined)


# =============================================================================
# Task 7 - admin AI config control plane (masked key, live apply)
# =============================================================================
def test_admin_ai_config_roundtrip(client):
    initial = client.get("/admin/ai-config")
    assert initial.status_code == 200, initial.text
    defaults = initial.json()
    assert defaults["ai_provider"] == "gemini"
    assert defaults["has_api_key"] is False
    assert defaults["masked_key"] is None

    # Save a provider + key: applies immediately, response MASKS the secret.
    updated = client.put(
        "/admin/ai-config",
        json={
            "ai_provider": "groq",
            "ai_model": "llama-3.3-70b-versatile",
            "ai_api_key": "gsk_live_key_1234567890abcd",
        },
    )
    assert updated.status_code == 200, updated.text
    masked = updated.json()
    assert masked["ai_provider"] == "groq"
    assert masked["has_api_key"] is True
    assert masked["masked_key"] == "gsk_...abcd"
    assert "1234567890" not in masked["masked_key"]  # raw key never leaks

    # Persists across reads.
    reread = client.get("/admin/ai-config").json()
    assert reread["ai_model"] == "llama-3.3-70b-versatile"
    assert reread["has_api_key"] is True

    # ai_api_key omitted (null) -> stored key KEPT (model-only change).
    kept = client.put(
        "/admin/ai-config",
        json={"ai_provider": "groq", "ai_model": "llama-3.1-8b-instant"},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["has_api_key"] is True

    # Bad base URL -> 400 (not stored).
    bad_url = client.put(
        "/admin/ai-config",
        json={
            "ai_provider": "groq",
            "ai_model": "llama-3.1-8b-instant",
            "ai_base_url": "not-a-url",
        },
    )
    assert bad_url.status_code == 400, bad_url.text

    # Unsupported provider -> pydantic rejects (422) before it reaches storage.
    bad_provider = client.put(
        "/admin/ai-config",
        json={"ai_provider": "deepseek", "ai_model": "deepseek-chat"},
    )
    assert bad_provider.status_code == 422, bad_provider.text

    # Empty key string CLEARS the key (fresh-install state restored).
    cleared = client.put(
        "/admin/ai-config",
        json={"ai_provider": "gemini", "ai_model": "gemini-2.5-flash",
              "ai_api_key": ""},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["has_api_key"] is False
    assert cleared.json()["masked_key"] is None


# =============================================================================
# Task 5 - buyer-seller chat (two real registered students)
# =============================================================================
def test_chat_flow_between_two_students(client):
    seller = _register(
        client, "Sara Seller", "sara.seller@campus.edu", "password123"
    )
    buyer = _register(
        client, "Bittu Buyer", "bittu.buyer@campus.edu", "password123"
    )
    listing = _create_listing(
        client,
        seller["headers"],
        title="HP Scientific Calculator",
        description="Exam-ready, batteries included.",
        condition="Like New",
        listed_price=650.0,
    )

    # Buyer sends the first message on the seller's listing.
    sent = client.post(
        "/chats/messages",
        json={
            "product_id": listing["id"],
            "receiver_id": seller["user"]["id"],
            "message": "Hi! Is this still available? I can pick it up today.",
        },
        headers=buyer["headers"],
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["is_read"] is False

    # Messaging yourself about your own listing is rejected.
    self_msg = client.post(
        "/chats/messages",
        json={
            "product_id": listing["id"],
            "receiver_id": seller["user"]["id"],
            "message": "note to self",
        },
        headers=seller["headers"],
    )
    assert self_msg.status_code == 400, self_msg.text

    # Seller's inbox groups by product + counterparty, with the unread badge.
    inbox = client.get("/chats/conversations", headers=seller["headers"])
    assert inbox.status_code == 200, inbox.text
    threads = inbox.json()
    assert len(threads) == 1
    thread = threads[0]
    assert thread["other_user_name"] == "Bittu Buyer"
    assert thread["product_title"] == "HP Scientific Calculator"
    assert thread["product_price"] == 650.0
    assert thread["unread_count"] == 1
    assert thread["unread"] is True
    assert thread["last_message_is_mine"] is False

    # Seller replies -> the buyer now has an UNREAD badge on their inbox.
    reply = client.post(
        "/chats/messages",
        json={
            "product_id": listing["id"],
            "receiver_id": buyer["user"]["id"],
            "message": "Yes! Available, ping me when you reach the hostel.",
        },
        headers=seller["headers"],
    )
    assert reply.status_code == 201, reply.text

    buyer_inbox = client.get(
        "/chats/conversations", headers=buyer["headers"]
    ).json()
    assert len(buyer_inbox) == 1
    assert buyer_inbox[0]["other_user_name"] == "Sara Seller"
    assert buyer_inbox[0]["last_message_is_mine"] is False
    assert buyer_inbox[0]["unread"] is True
    assert buyer_inbox[0]["unread_count"] == 1

    # Buyer opens the thread: full history, oldest first, and read-marking
    # clears their unread badge.
    history = client.get(
        f"/chats/messages/{listing['id']}/{seller['user']['id']}",
        headers=buyer["headers"],
    )
    assert history.status_code == 200, history.text
    messages = history.json()
    assert len(messages) == 2
    assert messages[0]["message"].startswith("Hi!")
    assert messages[1]["message"].startswith("Yes!")
    assert messages[1]["is_read"] is True  # received message got marked read

    cleared = client.get(
        "/chats/conversations", headers=buyer["headers"]
    ).json()
    assert cleared[0]["unread_count"] == 0
    assert cleared[0]["unread"] is False


# =============================================================================
# Task 5 - Ask CampusMart AI assistant (offline catalog fallback)
# =============================================================================
def test_ai_chat_answers_from_live_catalog(client):
    client.post(
        "/users/",
        json={"name": "AI Student", "email": "ai.student@campus.edu"},
        headers=MOCK_HEADERS,
    )
    _create_listing(
        client,
        MOCK_HEADERS,
        title="Bose SoundLink Flex speaker",
        description="Portable waterproof bluetooth speaker for hostel parties.",
        condition="Good",
        listed_price=5500.0,
        ai_tags="bose, soundlink, bluetooth speaker, wireless audio, music box",
    )

    response = client.post(
        "/ai/chat",
        json={"message": "Any bluetooth speaker under 6000?"},
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # No API key in tests -> deterministic local catalog assistant answers.
    assert body["source"] == "catalog"
    assert "₹" in body["reply"]  # currency is INR, never USD
    assert "Bose SoundLink Flex speaker" in body["reply"]
    assert len(body["recommended_product_ids"]) >= 1

    # Nonsense query still gets a helpful answer instead of an error.
    fallback = client.post(
        "/ai/chat",
        json={"message": "zqxvbnm rare thing"},
        headers=MOCK_HEADERS,
    )
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()["source"] == "catalog"


# =============================================================================
# Task 4 - blocked accounts: canonical 403 ACCOUNT_TERMINATED everywhere
# =============================================================================
def test_blocked_account_gets_canonical_403_everywhere(client):
    student = _register(
        client, "Rogue Student", "rogue.blocked@campus.edu", "password123"
    )
    uid = student["user"]["firebase_uid"]

    # Flip status directly (mirrors PATCH /admin/users/{id}/status).
    session = TestingSessionLocal()
    try:
        row = (
            session.query(User)
            .filter(User.firebase_uid == uid)
            .one()
        )
        row.status = "blocked"
        session.commit()
    finally:
        session.close()

    def assert_terminated(response):
        assert response.status_code == 403, response.text
        assert response.json()["detail"].startswith("ACCOUNT_TERMINATED:")

    # 1. Profile lookup (what the app calls on boot -> trips the lock screen).
    assert_terminated(client.get(f"/users/{uid}", headers=student["headers"]))

    # 2. Password login cannot re-enter a banned account.
    assert_terminated(
        client.post(
            "/auth/login",
            json={
                "email": "rogue.blocked@campus.edu",
                "password": "password123",
            },
        )
    )

    # 3. Listing creation.
    assert_terminated(
        client.post(
            "/products/",
            json={
                "title": "Blocked listing attempt",
                "description": "Should never be created.",
                "condition": "Good",
                "image_url": "https://cdn.example.com/x.jpg",
                "listed_price": 100.0,
            },
            headers=student["headers"],
        )
    )

    # 4. Chat endpoints (inbox + send) - the bearer layer rejects first.
    assert_terminated(
        client.get("/chats/conversations", headers=student["headers"])
    )

    # Unblocking restores access (same canonical check reads live status).
    session = TestingSessionLocal()
    try:
        row = session.query(User).filter(User.firebase_uid == uid).one()
        row.status = "active"
        session.commit()
    finally:
        session.close()
    assert client.get(
        f"/users/{uid}", headers=student["headers"]
    ).status_code == 200


# =============================================================================
# Task 1/6 - product create persists the 4-angle gallery + vision fair value
# =============================================================================
def test_product_create_persists_gallery_and_vision_price(client):
    client.post(
        "/users/",
        json={"name": "Gallery Seller", "email": "gallery.seller@campus.edu"},
        headers=MOCK_HEADERS,
    )
    photos = [f"https://uploads.local/p{index}.jpg" for index in range(4)]
    listing = _create_listing(
        client,
        MOCK_HEADERS,
        title="Casio fx-991EX Classwiz",
        description="Exam-allowed scientific calculator, screen protector on.",
        condition="Like New",
        listed_price=850.0,
        image_url=photos[0],
        image_urls=photos,
        ai_tags="casio, fx-991EX, classwiz, calculator, scientific, exam",
        ai_condition_notes="Front clean; back has one small scuff; keys crisp.",
        ai_suggested_price=900.0,
    )

    assert listing["image_urls"] == photos
    assert listing["ai_tags"].startswith("casio")
    assert listing["ai_condition_notes"].startswith("Front clean")
    assert listing["suggested_price"] == 900.0  # vision fair value adopted

    # A wildly inconsistent AI price is ignored: the server keeps the price
    # agent's fair value (Electronics ₹1500 base x Fair 0.40 = ₹600).
    clamped = _create_listing(
        client,
        MOCK_HEADERS,
        title="Cheap USB cable",
        description="Short charging cable, works fine.",
        condition="Fair",
        listed_price=100.0,
        ai_suggested_price=9_999_999.0,
    )
    assert clamped["suggested_price"] == 600.0

    # The read model backfills the gallery even when image_urls was omitted.
    legacy_shaped = _create_listing(
        client,
        MOCK_HEADERS,
        title="Legacy single photo listing",
        description="Only the front cover was uploaded.",
        condition="Good",
        listed_price=200.0,
    )
    # The gallery is always 4 slots: the single cover URL is cycled to fill
    # all of them so the detail screen's 4-angle carousel never branches.
    assert len(legacy_shaped["image_urls"]) == 4
    assert set(legacy_shaped["image_urls"]) == {legacy_shaped["image_url"]}
