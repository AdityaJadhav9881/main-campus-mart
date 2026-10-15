"""
test_image_upload.py - Phase 6 verification harness (manual test).

Verifies POST /products/upload-image/ end-to-end WITHOUT Docker or Cloudinary:
  * In-memory SQLite replaces PostgreSQL (get_db override).
  * TestClient is used WITHOUT a `with` block -> lifespan skipped (no
    firebase init, no Postgres connect).
  * Cloudinary credentials are unset locally -> the safe local-disk fallback
    in app/storage.py is what gets exercised; GET /uploads/<file> is served
    by the StaticFiles mount added to main.py.

Run (from /backend):
    python test_image_upload.py

Exit code 0 = all checks passed; 1 = at least one check failed.
"""

import io

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.storage import UPLOAD_DIR
from app import storage  # noqa: F401  (documents that storage is imported by app)

# --- In-memory SQLite + dependency override --------------------------------
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

MOCK_HEADERS = {"Authorization": "Bearer mock-local-dev-token"}

# Minimal valid 1x1 red PNG (67 bytes).
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


def main() -> None:
    # --- 0. Preconditions ---------------------------------------------------
    check("Cloudinary unset -> local fallback path", not storage._cloudinary_configured())

    # --- 1. Happy path: PNG upload -> 200 + /uploads URL --------------------
    r = client.post(
        "/products/upload-image/",
        files={"file": ("photo.png", io.BytesIO(PNG_1PX), "image/png")},
        headers=MOCK_HEADERS,
    )
    body = r.json()
    print("        upload response:", body)
    check("PNG upload -> 200", r.status_code == 200, str(r.status_code))
    url = body.get("image_url", "")
    check("response has image_url", bool(url), url)
    check("image_url points at /uploads/ (local fallback)", "/uploads/" in url, url)
    check("filename is UUID-based (no user path)", url.rsplit("/", 1)[-1] != "photo.png",
          url.rsplit("/", 1)[-1])

    # --- 2. Uploaded bytes are served back by the StaticFiles mount ---------
    r = client.get(url)
    check("GET uploaded file -> 200", r.status_code == 200, str(r.status_code))
    check("served bytes match the upload", r.content == PNG_1PX,
          f"{len(r.content)} bytes")
    check("served content-type is image/png",
          r.headers.get("content-type", "").startswith("image/png"),
          r.headers.get("content-type", ""))

    # --- 3. JPEG also accepted ---------------------------------------------
    r = client.post(
        "/products/upload-image/",
        files={"file": ("pic.jpg", io.BytesIO(b"\xff\xd8\xff\xe0fakejpeg"),
                        "image/jpeg")},
        headers=MOCK_HEADERS,
    )
    check("JPEG upload -> 200", r.status_code == 200, str(r.status_code))
    check("JPEG extension in URL", r.json().get("image_url", "").endswith(".jpg"),
          r.json().get("image_url", ""))

    # --- 4. Validation: wrong MIME, empty file, oversized file --------------
    r = client.post(
        "/products/upload-image/",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        headers=MOCK_HEADERS,
    )
    check("text/plain rejected -> 400", r.status_code == 400, str(r.status_code))

    r = client.post(
        "/products/upload-image/",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
        headers=MOCK_HEADERS,
    )
    check("empty file rejected -> 400", r.status_code == 400, str(r.status_code))

    big = io.BytesIO(b"\x89PNG" + b"\x00" * (5 * 1024 * 1024 + 1))
    r = client.post(
        "/products/upload-image/",
        files={"file": ("huge.png", big, "image/png")},
        headers=MOCK_HEADERS,
    )
    check("oversized (>5MB) rejected -> 400", r.status_code == 400,
          str(r.status_code))

    # --- 5. Auth is required -------------------------------------------------
    r = client.post(
        "/products/upload-image/",
        files={"file": ("photo.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    check("missing bearer token -> 401", r.status_code == 401, str(r.status_code))

    # --- 6. Files really landed under backend/uploads/ -----------------------
    on_disk = list(UPLOAD_DIR.glob("*.png")) + list(UPLOAD_DIR.glob("*.jpg"))
    check("files persisted under backend/uploads/", len(on_disk) >= 2,
          f"{len(on_disk)} image file(s)")

    print(f"\n{passed}/{passed + failed} checks passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
