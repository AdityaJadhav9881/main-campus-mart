"""
auth.py
=======
Authentication layer for CampusMart AI (Phase 2 + Phase 7).

Provides:
    * init_firebase()           - idempotent SDK initialization. Called ONCE during
                                  FastAPI startup (see main.lifespan).
    * verify_firebase_token()   - FastAPI dependency that accepts EITHER a local
                                  JWT issued by POST /auth/register|login OR a
                                  Firebase ID token (both share one Bearer
                                  header contract).
    * extract_uid()             - small helper to pull the verified UID out of
                                  the decoded claims (used by routers).
    * create_access_token()     - mint a local JWT for campus email/password
                                  auth (Phase 7).
    * hash_password()/verify_password() - bcrypt helpers for password_hash.

Client contract (Flutter):
    Header: Authorization: Bearer <JWT from POST /auth/login>
            or Authorization: Bearer <Firebase ID token>

NOTE: The `tokenUrl="token"` value below only feeds the Swagger/OpenAPI docs.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import firebase_admin
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
# Aliased so `verify_id_token` reads clearly and never collides with THIS
# module's name (app/auth.py):
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from firebase_admin.exceptions import FirebaseError

logger = logging.getLogger(__name__)

# Load /backend/.env regardless of the working directory uvicorn was started
# from (this file lives in /backend/app -> climb two levels).
BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

# -----------------------------------------------------------------------------
# Service-account key configuration (placeholder path per spec)
# -----------------------------------------------------------------------------
# Default: /backend/firebase-adminsdk.json
# Override in /backend/.env, e.g.:
#     FIREBASE_SERVICE_ACCOUNT_KEY=C:\secrets\campusmart-firebase.json
# SECURITY: this JSON is a full-privilege credential -> it is git-ignored and
# must NEVER be committed or shipped inside the Flutter app.
FIREBASE_SERVICE_ACCOUNT_KEY: str = os.getenv(
    "FIREBASE_SERVICE_ACCOUNT_KEY",
    str(BACKEND_ROOT / "firebase-adminsdk.json"),
)

# -----------------------------------------------------------------------------
# Phase 4 LOCAL-DEV mock bypass - SECURE BY DEFAULT (off)
# -----------------------------------------------------------------------------
# When AUTH_DEV_BYPASS=true in /backend/.env, verify_firebase_token() accepts
# Bearer tokens that start with "mock-" WITHOUT Firebase verification. This
# exists solely so the Flutter app's useMockAuth mode can exercise the full
# create-listing flow on an emulator with no live Firebase project.
# BOTH conditions are required (env opt-in AND mock- prefix), so real Firebase
# tokens keep being verified normally even while the flag is on.
# SECURITY: NEVER set this to true in any shared/staging/production environment.
AUTH_DEV_BYPASS: bool = os.getenv("AUTH_DEV_BYPASS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}

# -----------------------------------------------------------------------------
# Phase 7 - local JWT (campus email/password auth alongside Firebase)
# -----------------------------------------------------------------------------
# HS256 secret. PRODUCTION: set JWT_SECRET_KEY in the environment to a long
# random value; the dev default below is generated per-boot if unset (tokens
# will not survive restarts, which is fine for local development only).
JWT_SECRET_KEY: str = os.getenv(
    "JWT_SECRET_KEY",
    "campusmart-dev-only-secret-change-in-production",
)
JWT_ALGORITHM = "HS256"
# Token lifetime: 7 days by default (campus-app convenience; override via env).
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", str(7 * 24 * 60)))


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (salted per-hash)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt comparison. Returns False on malformed hashes."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(*, uid: str, email: str, name: str) -> str:
    """Mint a signed local JWT whose claims mirror Firebase's id-token shape.

    `uid` is stored under both `uid` and `user_id` so `extract_uid()` and any
    Firebase-aware middleware work unchanged.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "uid": uid,
        "user_id": uid,
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
        "iss": "campusmart",
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_local_jwt(token: str) -> dict | None:
    """Try to decode a locally-issued JWT; return None if it is not one."""
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None


# -----------------------------------------------------------------------------
# Admin access control (Phase 7)
# -----------------------------------------------------------------------------
# The React Admin Dashboard calls /admin/* straight from the browser WITHOUT a
# student Bearer JWT. Auth on admin endpoints is therefore OPTIONAL:
#   * ADMIN_REQUIRE_AUTH=false (default) -> endpoints are open (dashboard
#     works out-of-the-box; still accepts a Bearer token if one is sent).
#   * ADMIN_REQUIRE_AUTH=true           -> a valid Bearer token is required,
#     and when ADMIN_EMAILS is also set (comma-separated), only those emails
#     may use the admin API.
ADMIN_REQUIRE_AUTH: bool = os.getenv("ADMIN_REQUIRE_AUTH", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
ADMIN_EMAILS: frozenset[str] = frozenset(
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "").split(",")
    if email.strip()
)


def require_admin_access(
    token: str | None = Depends(OAuth2PasswordBearer(tokenUrl="token", auto_error=False)),
) -> dict | None:
    """Optional admin gate (see ADMIN_REQUIRE_AUTH above).

    Returns the decoded claims dict when a token was supplied, else None.
    Raises 401/403 only when admin auth is required and the check fails.
    """
    if not ADMIN_REQUIRE_AUTH:
        return None  # dashboard open-by-default

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required (ADMIN_REQUIRE_AUTH=true).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_local_jwt(token)
    if claims is not None:
        pass  # local JWT accepted
    else:
        try:
            firebase_admin.get_app()
            claims = firebase_auth.verify_id_token(token)
        except (ValueError, FirebaseError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired admin token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if ADMIN_EMAILS:
        email = (claims.get("email") or "").lower()
        if email not in ADMIN_EMAILS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not on the ADMIN_EMAILS allowlist.",
            )
    return claims


def init_firebase() -> None:
    """Initialize the firebase_admin SDK exactly once (idempotent).

    Behavior:
        1. If a Firebase app already exists -> no-op (safe double-call).
        2. If the service-account file exists -> credentials.Certificate(path).
        3. Else try Google Application Default Credentials (ADC), which
           honors the GOOGLE_APPLICATION_CREDENTIALS environment variable.
        4. Else log a warning and leave Firebase UNCONFIGURED; protected
           endpoints will then return 503 with an actionable message instead
           of crashing the whole server.
    """
    try:
        firebase_admin.get_app()          # already initialized -> nothing to do
        return
    except ValueError:
        pass                              # no default app yet -> initialize below

    key_path = Path(FIREBASE_SERVICE_ACCOUNT_KEY)

    if key_path.is_file():
        firebase_admin.initialize_app(credentials.Certificate(str(key_path)))
        logger.info("firebase-admin initialized from service account key: %s", key_path)
        return

    # Key file absent -> fall back to ADC (e.g. GOOGLE_APPLICATION_CREDENTIALS).
    try:
        firebase_admin.initialize_app(credentials.ApplicationDefault())
        logger.info("firebase-admin initialized via Application Default Credentials")
    except Exception:                     # noqa: BLE001 - deliberate startup resilience
        logger.warning(
            "Firebase credentials not found at '%s' and no Application Default "
            "Credentials are configured. Auth is DISABLED: protected endpoints "
            "will return 503 until a service-account key is provided.",
            key_path,
        )


# -----------------------------------------------------------------------------
# OAuth2 bearer scheme
# -----------------------------------------------------------------------------
# `tokenUrl` documents the expected header location in Swagger UI.
# auto_error=True -> FastAPI automatically answers 401 "Not authenticated"
# when the Authorization header is completely missing.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_firebase_token(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: validate the caller's Bearer token.

    Accepts EITHER token type through one contract:
        1. Local JWT issued by POST /auth/register|login (Phase 7 campus
           email/password auth).
        2. Firebase ID token (verified cryptographically against Google's
           certificates) - unchanged from Phase 2.
        3. `mock-*` tokens when AUTH_DEV_BYPASS=true (local dev only).

    Returns:
        dict: Decoded claims. Fields used downstream:
                - `uid` / `user_id` : stable user identifier
                - `email`, `name`   : profile claims

    Raises:
        HTTPException 401: token missing, malformed, expired, bad signature.
        HTTPException 503: Firebase not configured and token is not a local JWT.
    """
    # -------------------------------------------------------------------------
    # LOCAL DEV BYPASS (Phase 4 Flutter testing) - requires AUTH_DEV_BYPASS
    # -------------------------------------------------------------------------
    if AUTH_DEV_BYPASS and token.startswith("mock-"):
        logger.warning(
            "AUTH_DEV_BYPASS is ON: accepted a mock token WITHOUT Firebase "
            "verification (local development only - disable before deploying)."
        )
        return {
            "uid": "dev-mock-user",
            "email": "demo.student@campus.edu",
            "name": "Demo Student",
        }

    # -------------------------------------------------------------------------
    # Phase 7: local JWT first (campus email/password auth)
    # -------------------------------------------------------------------------
    local_claims = _decode_local_jwt(token)
    if local_claims is not None:
        return local_claims

    # -------------------------------------------------------------------------
    # Firebase ID token path (unchanged)
    # -------------------------------------------------------------------------
    # Guard clause: turns a confusing stack trace into an actionable message
    # when the service-account key has not been dropped in yet.
    try:
        firebase_admin.get_app()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Firebase authentication is not configured on this server. "
                "Add FIREBASE_SERVICE_ACCOUNT_KEY to /backend/.env and place "
                "the service-account JSON at /backend/firebase-adminsdk.json, "
                "or use POST /auth/register|login for campus email/password."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Core requirement: verify signature, expiry, audience and issuer
        # against Google's public certificates.
        decoded_token = firebase_auth.verify_id_token(token)
        return decoded_token
    except (ValueError, FirebaseError) as exc:
        # ValueError    -> malformed / expired / bad signature / wrong audience
        # FirebaseError -> backend-side certificate fetch or SDK failure.
        # Both surface as 401 so clients simply re-authenticate, and no
        # infrastructure details leak to unauthenticated callers.
        logger.warning("Rejected Firebase ID token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_uid(decoded_token: dict) -> str:
    """Return the verified Firebase UID from decoded claims.

    Firebase ID tokens carry the subject as `user_id`, while the Admin SDK
    documentation refers to `uid`. Accept either so the routers stay robust
    across SDK versions. Raises 401 if neither claim is present.
    """
    uid = decoded_token.get("uid") or decoded_token.get("user_id")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return uid
