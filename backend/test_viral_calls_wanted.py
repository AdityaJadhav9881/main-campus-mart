"""
test_viral_calls_wanted.py
==========================
Pytest suite verifying:
  1. PUT & POST /admin/ai-config with any single-key or multi-key pool payload (Task 1).
  2. Two-phone call signaling state machine & audio relay (/calls/*) (Task 2).
  3. Want to Buy board, AI quick-draft, and product listing reverse match (/wanted/*) (Task A2).
  4. Branch & Year filtering on GET /products/ and WhatsApp share card (Task A1, A3).
"""

from __future__ import annotations

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import CallSession, Notification, Product, User, WantedRequest

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


@pytest.fixture
def client():
    return TestClient(app)


def _register(client: TestClient, email: str, name: str, branch: str, year: str) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "Password123!",
            "college_name": "COEP Technological University, Pune",
            "college_code": "6006",
        },
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    return {
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
        "user": payload["user"],
    }


def test_admin_ai_config_accepts_any_payload(client):
    """Verify Task 1: PUT /admin/ai-config never returns 422 on any shape."""
    # 1. Empty body
    res = client.put("/admin/ai-config", json={})
    assert res.status_code == 200, res.text
    data = res.json()
    assert "ai_provider" in data

    # 2. Multi-key pool with missing top-level fields
    pool_payload = {
        "api_keys_pool": [
            {
                "id": str(uuid.uuid4()),
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "api_key": "AIzaSyTestKeyFromPool",
                "enabled": True,
            }
        ]
    }
    res = client.put("/admin/ai-config", json=pool_payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["has_api_key"] is True

    # 3. POST /admin/ai-config
    res_post = client.post("/admin/ai-config", json={"routing_mode": "round_robin"})
    assert res_post.status_code == 200, res_post.text


def test_call_session_signaling_flow(client):
    """Verify Task 2: Call state machine Phone 1 -> Phone 2."""
    s1 = _register(client, "caller.phone1@campus.edu", "Aarav Sharma", "Computer / IT", "SE (2nd Year)")
    s2 = _register(client, "receiver.phone2@campus.edu", "Ananya Patil", "Mechanical", "FE (1st Year)")

    # 1. Initiate call from s1 to s2
    init_res = client.post(
        "/calls/initiate",
        json={
            "receiver_id": s2["user"]["id"],
            "call_type": "voice",
            "sdp_offer": "v=0\r\no=caller 123 456...",
        },
        headers=s1["headers"],
    )
    assert init_res.status_code == 201, init_res.text
    call_data = init_res.json()
    assert call_data["status"] == "ringing"
    call_id = call_data["id"]

    # 2. Phone 2 polls for incoming call
    incoming_res = client.get("/calls/incoming", headers=s2["headers"])
    assert incoming_res.status_code == 200
    incoming_data = incoming_res.json()
    assert incoming_data is not None
    assert incoming_data["id"] == call_id
    assert incoming_data["status"] == "ringing"

    # 3. Phone 2 answers the call
    ans_res = client.post(
        f"/calls/{call_id}/answer",
        json={"sdp_answer": "v=0\r\no=receiver 789 101..."},
        headers=s2["headers"],
    )
    assert ans_res.status_code == 200
    assert ans_res.json()["status"] == "connected"

    # 4. Exchange signal / audio chunks
    sig_res = client.post(
        f"/calls/{call_id}/signal",
        json={"audio_chunk": "base64audiobytes123"},
        headers=s1["headers"],
    )
    assert sig_res.status_code == 200

    read_sig = client.get(f"/calls/{call_id}/signal", headers=s2["headers"])
    assert read_sig.status_code == 200
    assert len(read_sig.json()["peer_audio_chunks"]) > 0

    # 5. End call
    end_res = client.post(f"/calls/{call_id}/end", headers=s1["headers"])
    assert end_res.status_code == 200
    assert end_res.json()["status"] == "ended"


def test_wanted_board_and_reverse_match(client):
    """Verify Task A2: WTB Board creation, AI draft, and reverse trigger on product creation."""
    s1 = _register(client, "seller.drafter@campus.edu", "Rohan Gupta", "First Year (Common)", "FE (1st Year)")
    s2 = _register(client, "buyer.drafter@campus.edu", "Pooja Deshmukh", "Mechanical", "FE (1st Year)")

    # 1. AI Quick draft
    draft_res = client.post(
        "/wanted/ai-draft",
        json={"raw_text": "need mini drafter under 350 urgent for monday"},
        headers=s2["headers"],
    )
    assert draft_res.status_code == 200, draft_res.text
    draft_data = draft_res.json()
    assert draft_data["max_budget"] == 350.0
    assert "Urgent" in draft_data["urgency"]

    # 2. Post Wanted request
    create_res = client.post(
        "/wanted/",
        json={
            "title": "Looking for Mini Drafter",
            "description": "Urgent for Engineering Graphics sheet submission.",
            "max_budget": 400.0,
            "category": "Lab Gear & Instruments",
            "branch": "First Year (Common)",
            "academic_year": "FE (1st Year)",
            "urgency": "Urgent (24–48h)",
            "college_name": "COEP Technological University, Pune",
        },
        headers=s2["headers"],
    )
    assert create_res.status_code == 201, create_res.text
    wanted_id = create_res.json()["id"]

    # 3. Student 1 lists a matching drafter -> triggers reverse notification
    prod_res = client.post(
        "/products/",
        json={
            "title": "Omega Mini Drafter with Cover",
            "description": "Complete drafting tool set in good condition.",
            "condition": "good",
            "listed_price": 350.0,
            "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg",
            "image_urls": [
                "https://res.cloudinary.com/demo/image/upload/sample.jpg",
                "https://res.cloudinary.com/demo/image/upload/sample2.jpg",
                "https://res.cloudinary.com/demo/image/upload/sample3.jpg",
                "https://res.cloudinary.com/demo/image/upload/sample4.jpg",
            ],
            "branch": "First Year (Common)",
            "academic_year": "FE (1st Year)",
            "college_name": "COEP Technological University, Pune",
        },
        headers=s1["headers"],
    )
    assert prod_res.status_code == 201, prod_res.text
    prod_id = prod_res.json()["id"]

    # 4. Check that Student 2 received a 'wanted_match' notification!
    notif_res = client.get("/notifications/", headers=s2["headers"])
    assert notif_res.status_code == 200
    notif_payload = notif_res.json()
    notifs = notif_payload.get("notifications", [])
    match_notifs = [n for n in notifs if n["type"] == "wanted_match"]
    assert len(match_notifs) > 0
    assert "Omega Mini Drafter" in match_notifs[0]["title"] or "Match Found" in match_notifs[0]["title"]

    # 5. Share Card for product
    share_res = client.get(f"/products/{prod_id}/share-card")
    assert share_res.status_code == 200, share_res.text
    share_data = share_res.json()
    assert "whatsapp_share_text" in share_data
    assert "Omega Mini Drafter" in share_data["whatsapp_share_text"]
    assert "https://campus-mart-ivory.vercel.app/marketplace?item=" in share_data["whatsapp_share_text"]

    # 6. Branch & Year filtering on GET /products/
    feed_res = client.get("/products/?branch=First Year (Common)&academic_year=FE (1st Year)")
    assert feed_res.status_code == 200
    feed_items = feed_res.json()
    assert any(item["id"] == prod_id for item in feed_items)
