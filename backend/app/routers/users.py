"""
routers/users.py
================
User profile endpoints (Phase 2, Task 3 + college network).

    POST  /users/                  (protected) - create profile right after a
                                    student registers on the mobile app.
    GET   /users/{firebase_uid}    (public)    - fetch profile + trust score.
    PATCH /users/me                (protected) - update the caller's own
                                    profile (college picker in the Profile tab).

SECURITY MODEL
    On creation the `firebase_uid` is ALWAYS taken from the *verified* ID
    token - never from the request body - so no student can create or claim a
    profile belonging to someone else. PATCH /users/me only ever edits the
    caller's own row (same verified-identity rule).
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from ..auth import (
    account_terminated,
    extract_uid,
    get_or_create_current_user,
    verify_firebase_token,
)
from ..database import get_db
from ..models import User
from ..schemas import UserCollegeUpdate, UserCreate, UserRead

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
    email = (token.get("email") or payload.email).strip().lower()
    if existing is None and email:
        existing = db.query(User).filter(User.email.ilike(email)).first()
        if existing:
            existing.firebase_uid = firebase_uid
            db.commit()
            db.refresh(existing)

    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    user = User(firebase_uid=firebase_uid, name=payload.name, email=email)
    db.add(user)
    db.commit()          # explicit commit (autocommit=False in database.py)
    db.refresh(user)     # reload server-generated id + created_at defaults
    return user


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update my profile (college network)",
)
def update_my_profile(
    payload: UserCollegeUpdate,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> User:
    """Update the CALLER's own profile.

    Currently used by the Profile tab's college editor: the student picks a
    different CET college (or types a custom one) and their listings inherit
    it from the next publish onward. Only the caller's row is ever touched.
    """
    user = get_or_create_current_user(db, token)

    if payload.college_name is not None:
        user.college_name = payload.college_name.strip() or None
    if payload.college_code is not None:
        user.college_code = payload.college_code.strip() or None

    db.commit()
    db.refresh(user)
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
