"""
routers/users.py
================
User profile endpoints (Phase 2, Task 3).

    POST /users/                   (protected) - create profile right after a
                                    student registers on the mobile app.
    GET  /users/{firebase_uid}     (public)    - fetch profile + trust score.

SECURITY MODEL
    On creation the `firebase_uid` is ALWAYS taken from the *verified* ID
    token - never from the request body - so no student can create or claim a
    profile belonging to someone else. The body only carries display data
    (name, email).
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from ..auth import account_terminated, extract_uid, verify_firebase_token
from ..database import get_db
from ..models import User
from ..schemas import UserCreate, UserRead

# Prefix + path "/" below combine to the spec path "POST /users/".
router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create user profile",
)
def create_user(
    payload: UserCreate,
    response: Response,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> User:
    """Create the profile row mirroring a newly registered Firebase user.

    Idempotent by design: mobile clients may retry after a network drop, so an
    already-existing profile returns 200 + current data instead of an error.
    """
    firebase_uid = extract_uid(token)  # verified identity, not client input

    existing = (
        db.query(User).filter(User.firebase_uid == firebase_uid).first()
    )
    if existing:
        # Profile already present (client retry / re-install). Deliberately do
        # NOT overwrite: trust_score and curated profile data must survive
        # re-registration.
        response.status_code = status.HTTP_200_OK
        return existing

    # Prefer the email claim from the VERIFIED token (Firebase owns identity);
    # fall back to the request body for providers that omit `email`
    # (e.g. phone or anonymous auth).
    email = token.get("email") or payload.email

    user = User(firebase_uid=firebase_uid, name=payload.name, email=email)
    db.add(user)
    db.commit()          # explicit commit (autocommit=False in database.py)
    db.refresh(user)     # reload server-generated id + created_at defaults
    return user


@router.get(
    "/{firebase_uid}",
    response_model=UserRead,
    summary="Get user profile",
)
def get_user(
    firebase_uid: str = Path(
        ...,
        min_length=1,
        max_length=128,  # matches the column width in models.User
        description="Firebase UID of the profile to fetch.",
    ),
    db: Session = Depends(get_db),
) -> User:
    """Public profile lookup - trust scores are public on the marketplace.

    Task 4: a TERMINATED (blocked) account answers 403
    `ACCOUNT_TERMINATED: ...` here too - the app fetches this profile on boot,
    so that response is what trips the client's non-dismissible lock screen
    for a student whose access the Master Admin revoked.
    """
    user = (
        db.query(User).filter(User.firebase_uid == firebase_uid).first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if user.status == "blocked":
        raise account_terminated()
    return user
