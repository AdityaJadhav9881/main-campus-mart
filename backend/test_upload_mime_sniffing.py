"""
test_upload_mime_sniffing.py - pytest suite for the image-upload MIME fix.

Background
----------
On physical Android devices `image_picker` hands the multipart part a content
type of `application/octet-stream` (or none at all), so POST
/products/upload-image/ used to answer 400 and the Sell flow could never
upload a photo. The backend now recovers the real type from magic bytes first
and the filename extension second; the Flutter client also sends an explicit
Content-Type.

Run (from /backend):
    pytest -q

These tests are fully offline: in-memory SQLite (dependency override), the
local /uploads fallback (Cloudinary disabled by conftest.py), and the mock
token bypass (AUTH_DEV_BYPASS=true set by conftest.py).
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.storage import sniff_image_mime

# --- In-memory SQLite + dependency override --------------------------------
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
    """Install this module's in-memory session for every test it owns."""
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client() -> TestClient:
    # No `with` block -> the FastAPI lifespan (Firebase init, DB connect)
    # is intentionally skipped, exactly like the other harnesses.
    return TestClient(app)


MOCK_HEADERS = {"Authorization": "Bearer mock-local-dev-token"}

# Minimal valid 1x1 red PNG (67 bytes).
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e"
    "44ae426082"
)
JPEG_PREFIX = b"\xff\xd8\xff\xe0"
WEBP_PREFIX = b"RIFF\x24\x00\x00\x00WEBPVP8 "
GIF_PREFIX = b"GIF89a\x01\x00"


# =============================================================================
# 1. Unit tests: sniff_image_mime()
# =============================================================================
@pytest.mark.parametrize(
    ("payload", "filename", "expected"),
    [
        (JPEG_PREFIX, "photo.jpg", "image/jpeg"),
        (JPEG_PREFIX, "photo.jpg", "image/jpeg"),
        (PNG_1PX, "shot.png", "image/png"),
        (WEBP_PREFIX, "pic.webp", "image/webp"),
        (GIF_PREFIX, "anim.gif", "image/gif"),
        # Bytes too short / generic to classify -> filename decides.
        (b"", "holiday.jpeg", "image/jpeg"),
        (b"", "holiday.heic", "image/heic"),
        (b"", "holiday.WEBP", "image/webp"),
        # Not an image at all -> no type (caller rejects with 400).
        (b"just some text", "notes.txt", None),
        (b"", "notes.txt", None),
        (b"", None, None),
    ],
)
def test_sniff_image_mime(payload, filename, expected):
    assert sniff_image_mime(payload, filename) == expected


def test_sniff_prefers_magic_bytes_over_extension():
    """A PNG mislabelled as .jpg must still be identified as a PNG."""
    assert sniff_image_mime(PNG_1PX, "mislabelled.jpg") == "image/png"


def test_jpeg_magic_detects_without_extension():
    assert sniff_image_mime(JPEG_PREFIX + b"\x00" * 32, None) == "image/jpeg"


# =============================================================================
# 2. End-to-end: /products/upload-image/ with ambiguous content types
# =============================================================================
def test_octet_stream_upload_is_accepted(client):
    """The Android bug: content type is application/octet-stream."""
    response = client.post(
        "/products/upload-image/",
        files={
            "file": ("photo.jpg", io.BytesIO(JPEG_PREFIX + b"body"),
                     "application/octet-stream"),
        },
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200, response.text
    url = response.json()["image_url"]
    assert "/uploads/" in url
    assert url.endswith(".jpg")


def test_missing_content_type_upload_is_accepted(client):
    """httpx picks the type from the filename; no explicit part type given."""
    response = client.post(
        "/products/upload-image/",
        files={"file": ("shot.png", io.BytesIO(PNG_1PX))},
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["image_url"].endswith(".png")


def test_octet_stream_png_keeps_png_extension(client):
    """The stored extension must follow the sniffed type, not 'octet'."""
    response = client.post(
        "/products/upload-image/",
        files={
            "file": ("anything.bin", io.BytesIO(PNG_1PX),
                     "application/octet-stream"),
        },
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["image_url"].endswith(".png")


def test_webp_bytes_with_octet_stream(client):
    response = client.post(
        "/products/upload-image/",
        files={
            "file": ("frame.webp", io.BytesIO(WEBP_PREFIX),
                     "application/octet-stream"),
        },
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["image_url"].endswith(".webp")


def test_non_image_still_rejected(client):
    """The fix must NOT become a bypass for real non-image payloads."""
    response = client.post(
        "/products/upload-image/",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 400, response.text


def test_empty_upload_still_rejected(client):
    response = client.post(
        "/products/upload-image/",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 400, response.text


def test_auth_still_required(client):
    response = client.post(
        "/products/upload-image/",
        files={"file": ("photo.jpg", io.BytesIO(JPEG_PREFIX), "image/jpeg")},
    )
    assert response.status_code == 401, response.text


def test_served_bytes_round_trip(client):
    response = client.post(
        "/products/upload-image/",
        files={
            "file": ("roundtrip.png", io.BytesIO(PNG_1PX),
                     "application/octet-stream"),
        },
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200, response.text
    url = response.json()["image_url"]

    fetched = client.get(url)
    assert fetched.status_code == 200
    assert fetched.content == PNG_1PX
    assert fetched.headers["content-type"].startswith("image/png")


# =============================================================================
# 3. Seller name exposure (product detail screen)
# =============================================================================
def test_feed_exposes_seller_name(client):
    """ProductRead now carries seller_name for the detail screen."""
    profile = client.post(
        "/users/",
        json={"name": "Meera Iyer", "email": "meera@campus.edu"},
        headers=MOCK_HEADERS,
    )
    assert profile.status_code in (200, 201), profile.text

    listing = client.post(
        "/products/",
        json={
            "title": "Oscilloscope probe set",
            "description": "Works perfectly, barely used in lab.",
            "condition": "Good",
            "age": "1 year",
            "image_url": "https://cdn.example.com/probe.jpg",
            "listed_price": 35.0,
        },
        headers=MOCK_HEADERS,
    )
    assert listing.status_code == 201, listing.text
    assert listing.json()["seller_name"] == "Meera Iyer"

    feed = client.get("/products/")
    assert feed.status_code == 200
    match = [p for p in feed.json() if p["id"] == listing.json()["id"]]
    assert match and match[0]["seller_name"] == "Meera Iyer"


# =============================================================================
# 4. Owner delete endpoint (Profile "My Listings" tab)
# =============================================================================
def test_delete_own_listing(client):
    client.post(
        "/users/",
        json={"name": "Rohan D", "email": "rohan@campus.edu"},
        headers=MOCK_HEADERS,
    )
    listing = client.post(
        "/products/",
        json={
            "title": "Drafting board",
            "description": "Sturdy wooden board, minor scratches.",
            "condition": "Fair",
            "age": "3 years",
            "image_url": "https://cdn.example.com/board.jpg",
            "listed_price": 20.0,
        },
        headers=MOCK_HEADERS,
    )
    assert listing.status_code == 201, listing.text
    product_id = listing.json()["id"]

    response = client.delete(f"/products/{product_id}", headers=MOCK_HEADERS)
    assert response.status_code == 204, response.text

    # Gone from the feed as well.
    feed = client.get("/products/")
    assert all(p["id"] != product_id for p in feed.json())


def test_delete_missing_listing_404(client):
    # Ensure the caller's profile row exists so the 404 comes from the
    # product lookup, not the "create your profile first" guard.
    client.post(
        "/users/",
        json={"name": "Dev Student", "email": "dev@campus.edu"},
        headers=MOCK_HEADERS,
    )
    response = client.delete(
        "/products/00000000-0000-0000-0000-000000000000",
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 404, response.text
