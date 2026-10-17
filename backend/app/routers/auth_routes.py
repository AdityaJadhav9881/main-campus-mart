"""
routers/auth_routes.py
======================
Real student email/password authentication (Phase 7 - zero mocks).

    POST /auth/register   - create a campus account (bcrypt-hashed password),
                            return a local JWT + profile.
    POST /auth/login      - verify credentials, return a local JWT + profile.
    POST /auth/send-otp   - start the 2-step signup: mail a 6-digit code
                            (Brevo) and park the hashed password for 10 min.
    POST /auth/verify-otp - check the code, create the active User, return JWT.
    POST /auth/resend-otp - issue + re-email a fresh code for a pending signup.

Both auth endpoints share the same Bearer-header contract as Firebase ID
tokens, so every protected route (products, transactions, users) works
unchanged for email/password students. Firebase auth remains fully active in
app/auth.py.
"""

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    account_terminated,
    create_access_token,
    get_or_create_current_user,
    hash_password,
    verify_firebase_token,
    verify_password,
)
from ..database import get_db
from ..email_service import send_action_otp_email, send_otp_email
from ..models import ActionOTP, EmailOTP, User
from ..schemas import (
    ActionOtpVerifiedResponse,
    LoginRequest,
    OtpSentResponse,
    RegisterRequest,
    ResendOtpRequest,
    SendActionOtpRequest,
    SendOtpRequest,
    TokenResponse,
    UserRead,
    VerifyActionOtpRequest,
    VerifyOtpRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Registration OTP lifetime (the email body states the same window).
OTP_TTL_MINUTES = 10


def _generate_otp() -> str:
    """Cryptographically random 6-digit code (100000-999999, no leading 0)."""
    return str(secrets.randbelow(900000) + 100000)


def _find_user(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email.ilike(email)).first()


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
        college_name=(payload.college_name or "").strip() or None,
        college_code=(payload.college_code or "").strip() or None,
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
        # Canonical Task-4 body: the client string-matches the
        # `ACCOUNT_TERMINATED:` prefix and locks the app immediately.
        raise account_terminated()

    token = create_access_token(uid=user.firebase_uid, email=user.email, name=user.name)
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


# =============================================================================
# 2-step Email OTP signup (6-digit verification code via Brevo)
# =============================================================================
@router.post(
    "/send-otp",
    response_model=OtpSentResponse,
    summary="Start signup: email a 6-digit verification code",
)
def send_otp(payload: SendOtpRequest, db: Session = Depends(get_db)) -> OtpSentResponse:
    """Step 1 - validate the address, park the signup, mail the code.

    Contract:
        * 409 when the email already has an account (no code wasted).
        * Generates a 6-digit OTP (100000-999999), bcrypt-hashes the chosen
          password ONCE and stores both on `email_otps` for 10 minutes.
        * Calls Brevo's send_otp_email() (non-blocking: a mail hiccup never
          fails the request - the code still works, resend is available).
    """
    email = payload.email.strip().lower()
    if _find_user(db, email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Try logging in.",
        )

    name = payload.name.strip()
    otp_code = _generate_otp()
    password_hash = hash_password(payload.password)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    college_name = (payload.college_name or "").strip() or None
    college_code = (payload.college_code or "").strip() or None

    # One pending row per email: resend/overwrite instead of stacking rows.
    row = db.query(EmailOTP).filter(EmailOTP.email == email).first()
    if row is None:
        row = EmailOTP(
            email=email,
            otp_code=otp_code,
            name=name,
            password_hash=password_hash,
            college_name=college_name,
            college_code=college_code,
            expires_at=expires_at,
        )
        db.add(row)
    else:
        row.otp_code = otp_code
        row.name = name
        row.password_hash = password_hash
        row.college_name = college_name
        row.college_code = college_code
        row.expires_at = expires_at
    db.commit()

    # Deliberately after commit: even if Brevo is down, the code is stored and
    # the student can use instant verification (email_service never raises).
    delivered = send_otp_email(email, name, otp_code)
    logger.info("OTP issued for %s (delivered=%s)", email, delivered)
    return OtpSentResponse(
        message="Verification code sent to your email",
        email=email,
        email_delivered=delivered,
        fallback_otp_code=None if delivered else otp_code,
    )


@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Verify the 6-digit code and create the account",
)
def verify_otp(payload: VerifyOtpRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Step 2 - check the code, create the active User, return the JWT.

    Contract:
        * 400 for missing / expired / wrong codes (actionable detail text).
        * The User is created exactly like POST /auth/register: active,
          trust_score 5.0, `local-<uuid>` firebase_uid, bcrypt password.
        * The OTP row is DELETED on success - each code is single-use.
    """
    email = payload.email.strip().lower()
    row = db.query(EmailOTP).filter(EmailOTP.email == email).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code found for this email. Request a new one.",
        )

    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # SQLite returns naive datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code expired. Request a new one.",
        )

    if not secrets.compare_digest(row.otp_code, payload.otp_code.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Check the email and try again.",
        )

    if _find_user(db, email) is not None:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Try logging in.",
        )

    user = User(
        firebase_uid=f"local-{uuid.uuid4().hex}",
        name=row.name,
        email=email,
        password_hash=row.password_hash,
        status="active",
        trust_score=5.0,
        college_name=row.college_name,
        college_code=row.college_code,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent double-submit on the same email
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Try logging in.",
        ) from exc

    db.delete(row)
    db.commit()
    db.refresh(user)

    token = create_access_token(uid=user.firebase_uid, email=user.email, name=user.name)
    logger.info("OTP verified; account created for %s", email)
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.post(
    "/resend-otp",
    response_model=OtpSentResponse,
    summary="Resend a fresh 6-digit code for a pending signup",
)
def resend_otp(payload: ResendOtpRequest, db: Session = Depends(get_db)) -> OtpSentResponse:
    """Issue a NEW code (and expiry) for a signup already waiting on step 2.

    The original name/password_hash stay parked on the row - only the code
    and the 10-minute window are rotated. 400 when nothing is pending, so the
    Flutter 30s resend button always knows when resending is possible.
    """
    email = payload.email.strip().lower()
    row = db.query(EmailOTP).filter(EmailOTP.email == email).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending verification for this email. Start sign up again.",
        )

    row.otp_code = _generate_otp()
    row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    db.commit()

    delivered = send_otp_email(row.email, row.name, row.otp_code)
    logger.info("OTP resent for %s (delivered=%s)", email, delivered)
    return OtpSentResponse(
        message="Verification code sent to your email",
        email=email,
        email_delivered=delivered,
        fallback_otp_code=None if delivered else row.otp_code,
    )


# =============================================================================
# Action OTP - verify before publishing a listing / placing an order
# =============================================================================
@router.post(
    "/send-action-otp",
    response_model=OtpSentResponse,
    summary="Email a 6-digit code that authorises a sell/purchase action",
)
def send_action_otp(
    payload: SendActionOtpRequest,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> OtpSentResponse:
    """Mint + email an action code for the LOGGED-IN student.

    Called right before:
        * "Publish Listing"  (action_type='sell')
        * "Place Order"      (action_type='purchase')
    The code (10-minute TTL) is stored on `action_otps` keyed by
    (email, action_type); requesting again simply rotates it.
    """
    user = get_or_create_current_user(db, token)
    email = user.email

    otp_code = _generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)

    # Replace any pending code for this action (resend = fresh code).
    db.query(ActionOTP).filter(
        ActionOTP.email == email,
        ActionOTP.action_type == payload.action_type,
    ).delete(synchronize_session=False)
    row = ActionOTP(
        email=email,
        otp_code=otp_code,
        action_type=payload.action_type,
        item_title=(payload.item_title or "").strip()[:200] or None,
        expires_at=expires_at,
        verified=False,
    )
    db.add(row)
    db.commit()

    delivered = send_action_otp_email(
        email,
        user.name,
        otp_code,
        action_type=payload.action_type,
        item_title=row.item_title,
    )
    logger.info(
        "Action OTP issued for %s (%s, delivered=%s)",
        email, payload.action_type, delivered,
    )
    return OtpSentResponse(
        message="Verification code sent to your email",
        email=email,
        email_delivered=delivered,
        fallback_otp_code=None if delivered else otp_code,
    )


@router.post(
    "/verify-action-otp",
    response_model=ActionOtpVerifiedResponse,
    summary="Verify the action code and mint a one-shot action token",
)
def verify_action_otp(
    payload: VerifyActionOtpRequest,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> ActionOtpVerifiedResponse:
    """Check the 6-digit action code for the logged-in student.

    On success the row is marked verified and an opaque `action_token` is
    minted. The client then proceeds with the publish/purchase call; the
    token (or the raw code) is accepted there as proof of verification.
    """
    user = get_or_create_current_user(db, token)
    email = user.email

    row = (
        db.query(ActionOTP)
        .filter(
            ActionOTP.email == email,
            ActionOTP.action_type == payload.action_type,
        )
        .order_by(ActionOTP.created_at.desc())
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code found for this action. Request a new one.",
        )

    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # SQLite returns naive datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code expired. Request a new one.",
        )

    if not secrets.compare_digest(row.otp_code, payload.otp_code.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Check the email and try again.",
        )

    row.verified = True
    row.action_token = secrets.token_urlsafe(24)
    db.commit()

    logger.info("Action OTP verified for %s (%s)", email, payload.action_type)
    return ActionOtpVerifiedResponse(
        verified=True,
        action_type=payload.action_type,
        action_token=row.action_token,
    )
