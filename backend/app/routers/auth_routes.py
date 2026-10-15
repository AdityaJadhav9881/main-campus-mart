"""
routers/auth_routes.py
======================
Real student email/password authentication (Phase 7 - zero mocks).

    POST /auth/register  - create a campus account (bcrypt-hashed password),
                           return a local JWT + profile.
    POST /auth/login     - verify credentials, return a local JWT + profile.

Both endpoints share the same Bearer-header contract as Firebase ID tokens,
so every protected route (products, transactions, users) works unchanged for
email/password students. Firebase auth remains fully active in app/auth.py.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import create_access_token, hash_password, verify_password
from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a campus student (email/password)",
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Create a new student account and issue a JWT.

    Identity model:
        * `firebase_uid` = "local-<uuid>" so the users table keeps its UNIQUE
          identity column working for both Firebase and local accounts.
        * Password is hashed with bcrypt before storage; the plaintext never
          touches the database.
        * Email is unique - a duplicate returns 409.
    """
    existing = (
        db.query(User)
        .filter(User.email.ilike(payload.email.strip().lower()))
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Try logging in.",
        )

    email = payload.email.strip().lower()
    user = User(
        firebase_uid=f"local-{uuid.uuid4().hex}",
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        status="active",
        trust_score=5.0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(uid=user.firebase_uid, email=user.email, name=user.name)
    logger.info("Student registered: %s <%s>", user.name, user.email)
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with campus email/password",
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Verify credentials and issue a JWT.

    Security notes:
        * Identical 401 message for unknown-email and wrong-password so the
          endpoint cannot be used to enumerate registered addresses.
        * Blocked accounts (user.status == 'blocked') receive 403 so a banned
          student cannot re-enter through the password flow.
    """
    user = (
        db.query(User)
        .filter(User.email.ilike(payload.email.strip().lower()))
        .first()
    )

    if (
        user is None
        or user.password_hash is None
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been blocked. Contact campus support.",
        )

    token = create_access_token(uid=user.firebase_uid, email=user.email, name=user.name)
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))
