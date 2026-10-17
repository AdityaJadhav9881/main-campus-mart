"""
routers/notifications.py
========================
Bell-icon notification feed for the logged-in student.

    GET  /notifications/                - latest alerts + unread badge count
    POST /notifications/{id}/read       - mark one as read
    POST /notifications/read-all        - clear the whole badge

Rows are created server-side by the feature that causes them:
    * same-college listing published  -> every active student of that college
    * order placed                     -> seller ("Order Received") + buyer
    * listing sold / cancelled         -> seller/buyer updates
    * new chat message                 -> receiver
    * finished / missed call           -> receiver

The Flutter `notification_service` polls GET /notifications/ every 15s and
mirrors new rows to the Android system tray (high-importance channel).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..auth import get_or_create_current_user, verify_firebase_token
from ..database import get_db
from ..models import Notification
from ..schemas import NotificationListResponse, NotificationRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="My notifications (newest first) + unread count",
)
@router.get(
    "/",
    response_model=NotificationListResponse,
    include_in_schema=False,
)
def list_notifications(
    limit: int = Query(default=60, ge=1, le=200),
    unread_only: bool = Query(default=False),
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> NotificationListResponse:
    """Feed for the notifications screen + bell badge."""
    me = get_or_create_current_user(db, token)

    query = db.query(Notification).filter(Notification.user_id == me.id)
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == me.id, Notification.is_read.is_(False))
        .count()
    )
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))

    rows = (
        query.order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return NotificationListResponse(
        notifications=[NotificationRead.model_validate(row) for row in rows],
        unread_count=unread_count,
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark one notification as read",
)
def mark_notification_read(
    notification_id: UUID,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> NotificationRead:
    """Owner-only; 404 for other students' rows (no existence leak)."""
    me = get_or_create_current_user(db, token)
    row = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == me.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    row.is_read = True
    db.commit()
    db.refresh(row)
    return NotificationRead.model_validate(row)


@router.post(
    "/read-all",
    summary="Mark every notification as read (clears the badge)",
)
def mark_all_notifications_read(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> dict:
    """Bulk read; returns how many rows changed."""
    me = get_or_create_current_user(db, token)
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == me.id, Notification.is_read.is_(False))
        .update({Notification.is_read: True}, synchronize_session=False)
    )
    db.commit()
    logger.info("notifications: marked %s read for %s", updated, me.email)
    return {"updated": int(updated), "unread_count": 0}
