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
      Clients that send `application/octet-stream` / no content type (common
      on Android + web) get their real type recovered from magic bytes first,
      then from the filename extension - only genuinely non-image payloads
      are rejected.
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
    "image/heic": "heic",
}

# Filename extension -> MIME type, used when the client cannot tell us what
# it uploaded (application/octet-stream, missing content type, Android's
# image_picker on some devices, web blobs, ...).
_EXTENSION_MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heic",
}

# Leading-byte signatures checked BEFORE the filename extension, because a
# client can mislabel a file far more easily than it can rewrite its bytes.
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),          # JPEG / JPEG-EXIF / JPEG-2000 SOI
    (b"\x89PNG\r\n\x1a\n", "image/png"),      # PNG
    (b"GIF87a", "image/gif"),                 # GIF87a
    (b"GIF89a", "image/gif"),                 # GIF89a
)

_WEBP_RIFF_PREFIX = b"RIFF"
_WEBP_TYPE_OFFSET = 8   # bytes 0-3 "RIFF", 4-7 size, 8-11 "WEBP"
_WEBP_TYPE = b"WEBP"


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


def sniff_image_mime(data: bytes, filename: str | None = None) -> str | None:
    """Recover the real image MIME type for an ambiguous upload.

    Android's `image_picker` and browser blob plumbing frequently hand the
    backend `application/octet-stream` (or nothing at all) even though the
    bytes are a perfectly good photo. Rejecting those 400s would break the
    Sell flow on physical devices, so instead we identify the payload:

        1. Magic bytes: JPEG ``\\xff\\xd8\\xff``, PNG ``\\x89PNG``, GIF ``GIF8``,
           WebP ``RIFF....WEBP`` - authoritative, cannot be faked by a name.
        2. Filename extension: ``.jpg``/``.jpeg``/``.png``/``.webp``/``.gif``/
           ``.heic`` - the fallback when the bytes are too short to classify.

    Returns a content type that passes the allow-list, or None when the
    payload is not a recognised image (caller rejects with HTTP 400).
    """
    if data:
        for magic, mime in _MAGIC_SIGNATURES:
            if data.startswith(magic):
                return mime
        # WebP is RIFF-based, so the container and the format tag are split.
        if (
            len(data) >= _WEBP_TYPE_OFFSET + 4
            and data.startswith(_WEBP_RIFF_PREFIX)
            and data[_WEBP_TYPE_OFFSET:_WEBP_TYPE_OFFSET + 4] == _WEBP_TYPE
        ):
            return "image/webp"

    suffix = Path(filename or "").suffix.lower()
    return _EXTENSION_MIME_TYPES.get(suffix)


def _validated_image_bytes(file: UploadFile) -> tuple[bytes, str, str]:
    """Read and validate the upload; returns (bytes, mime_type, extension).

    A content type outside the image allow-list (including the empty string
    and ``application/octet-stream``) is not fatal on its own - it triggers
    magic-byte/extension sniffing first, and only a payload that still looks
    non-image is rejected.
    """
    declared = (file.content_type or "").split(";")[0].strip().lower()

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) == 0:
        raise StorageError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise StorageError(
            f"Image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit. "
            "Please resize and try again."
        )

    content_type = declared if declared in _CONTENT_TYPE_EXTENSIONS else None
    if content_type is None:
        content_type = sniff_image_mime(data, file.filename)
    if content_type is None or content_type not in _CONTENT_TYPE_EXTENSIONS:
        raise StorageError(
            f"Unsupported file type '{declared or 'unknown'}'. "
            "Upload a JPEG, PNG, WebP, GIF, or HEIC image."
        )

    return data, content_type, _CONTENT_TYPE_EXTENSIONS[content_type]


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


def save_upload(file: UploadFile, base_url: str) -> tuple[str, str]:
    """Validate + store one listing photo; return (absolute URL, MIME type).

    Args:
        file:        The uploaded multipart file (UploadFile from FastAPI).
                     Ambiguous content types (application/octet-stream / None)
                     are recovered from magic bytes or the filename extension.
        base_url:    Scheme+host+port the client used to reach this API
                     (str(request.base_url), always ends with "/"). Used to
                     absolutize local-fallback paths; Cloudinary URLs are
                     already absolute and ignore it.

    Returns:
        ``(url, content_type)`` where url is absolute, e.g.
        "https://res.cloudinary.com/..." or
        "http://127.0.0.1:8000/uploads/<uuid>.jpg", and content_type is the
        RESOLVED image MIME (not necessarily what the client declared).

    Raises:
        StorageError: bad MIME type, empty/oversized file, or backend failure.
    """
    data, content_type, extension = _validated_image_bytes(file)

    if _cloudinary_configured():
        return _upload_to_cloudinary(data, content_type), content_type

    # Local fallback: keep the dev flow working with zero cloud setup.
    relative = _upload_to_local(data, extension)
    normalized_base = base_url if base_url.endswith("/") else f"{base_url}/"
    return f"{normalized_base}{relative.lstrip('/')}", content_type
