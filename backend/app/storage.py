"""
storage.py
==========
Phase 6 cloud image-upload pipeline for CampusMart AI.

Responsibilities
----------------
1. Cloudinary primary storage: upload listing photos to a managed CDN when
   CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET are set.
2. Safe local fallback: when credentials are absent (fresh clone, local dev,
   CI), images are written to /backend/uploads/ and served back by the API
   itself (mounted at /uploads by main.py) - the app never crashes because
   Cloudinary is not configured yet.

Environment variables (all optional locally, REQUIRED in production):
    CLOUDINARY_CLOUD_NAME
    CLOUDINARY_API_KEY
    CLOUDINARY_API_SECRET

SECURITY notes:
    * Only image MIME types are accepted; anything else raises StorageError.
    * Uploads are capped at MAX_UPLOAD_BYTES (5 MB) before any write happens.
    * Local filenames are random UUIDs - user-controlled names never touch
      the filesystem (no path traversal).
    * Render/Heroku disks are EPHERMERAL: production MUST set the Cloudinary
      credentials, otherwise local-fallback uploads disappear on redeploy.
"""

import io
import os
import uuid
from pathlib import Path

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from fastapi import UploadFile

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

# Local-fallback storage folder, served by main.py at GET /uploads/<name>.
UPLOAD_DIR: Path = BACKEND_ROOT / "uploads"

# Hard cap per upload (5 MB) - keeps the API memory-safe against abuse.
MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024

# MIME type -> extension allow-list for the local fallback filenames.
_CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class StorageError(Exception):
    """Raised for validation failures or storage-backend errors.

    The upload endpoint maps this to HTTP 400/502 with the message intact so
    the Flutter client can show an actionable snackbar.
    """


def _cloudinary_configured() -> bool:
    """True when all three Cloudinary credentials are present."""
    return bool(
        os.getenv("CLOUDINARY_CLOUD_NAME")
        and os.getenv("CLOUDINARY_API_KEY")
        and os.getenv("CLOUDINARY_API_SECRET")
    )


def _validated_image_bytes(file: UploadFile) -> tuple[bytes, str]:
    """Read and validate the upload; returns (bytes, extension)."""
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _CONTENT_TYPE_EXTENSIONS:
        raise StorageError(
            f"Unsupported file type '{content_type or 'unknown'}'. "
            "Upload a JPEG, PNG, WebP, or GIF image."
        )

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) == 0:
        raise StorageError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise StorageError(
            f"Image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit. "
            "Please resize and try again."
        )
    return data, _CONTENT_TYPE_EXTENSIONS[content_type]


def _upload_to_cloudinary(data: bytes, content_type: str) -> str:
    """Push bytes to Cloudinary; returns the immutable CDN URL."""
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(data),
            folder="campusmart/listings",
            resource_type="image",
            overwrite=False,
        )
    except Exception as exc:  # noqa: BLE001 - normalized into StorageError
        raise StorageError(f"Cloudinary upload failed: {exc}") from exc

    url = result.get("secure_url")
    if not url:
        raise StorageError("Cloudinary returned no URL for the upload.")
    return str(url)


def _upload_to_local(data: bytes, extension: str) -> str:
    """Persist bytes under /backend/uploads and return a relative URL path."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    (UPLOAD_DIR / filename).write_bytes(data)
    # Relative path: main.py mounts StaticFiles at /uploads. The client
    # resolves this against whatever host it used to reach the API (emulator
    # 10.0.2.2, localhost, or the Render domain) - no hardcoded host.
    return f"/uploads/{filename}"


def save_upload(file: UploadFile, base_url: str) -> str:
    """Validate + store one listing photo; return an absolute image URL.

    Args:
        file:        The uploaded multipart file (UploadFile from FastAPI).
        base_url:    Scheme+host+port the client used to reach this API
                     (str(request.base_url), always ends with "/"). Used to
                     absolutize local-fallback paths; Cloudinary URLs are
                     already absolute and ignore it.

    Returns:
        Absolute URL string, e.g. "https://res.cloudinary.com/..." or
        "http://127.0.0.1:8000/uploads/<uuid>.jpg".

    Raises:
        StorageError: bad MIME type, empty/oversized file, or backend failure.
    """
    data, extension = _validated_image_bytes(file)

    if _cloudinary_configured():
        return _upload_to_cloudinary(data, file.content_type or "")

    # Local fallback: keep the dev flow working with zero cloud setup.
    relative = _upload_to_local(data, extension)
    normalized_base = base_url if base_url.endswith("/") else f"{base_url}/"
    return f"{normalized_base}{relative.lstrip('/')}"
