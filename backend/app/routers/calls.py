"""
calls.py
========
Two-phone call signaling, ringing, audio relay, and call history router.

Powers real-time voice and video calls between students with:
  1. Ringing state machine ('ringing' -> 'connected' | 'declined' | 'ended' | 'missed').
  2. Incoming call polling endpoint (/calls/incoming) for foreground UI + background service.
  3. Live status polling (/calls/{call_id}) so Phone 1 knows when Phone 2 answers.
  4. WebRTC signaling & low-latency audio chunk exchange (/calls/{call_id}/signal).
  5. Automatic call logging into chat_messages on decline / end.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_or_create_current_user, verify_firebase_token
from ..database import get_db
from ..models import CallSession, ChatMessage, Notification, Product, User
from ..schemas import (
    CallInitiateRequest,
    CallSessionRead,
    CallSignalRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["Calls & Signaling"])


def _current_user(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> User:
    return get_or_create_current_user(db, token)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _diff_seconds(t_end: datetime | None, t_start: datetime | None) -> int:
    if not t_end or not t_start:
        return 0
    if t_end.tzinfo is not None and t_start.tzinfo is None:
        t_start = t_start.replace(tzinfo=timezone.utc)
    elif t_end.tzinfo is None and t_start.tzinfo is not None:
        t_end = t_end.replace(tzinfo=timezone.utc)
    return max(0, int((t_end - t_start).total_seconds()))


def _to_read(session: CallSession) -> CallSessionRead:
    return CallSessionRead(
        id=session.id,
        caller_id=session.caller_id,
        caller_name=session.caller_name,
        receiver_id=session.receiver_id,
        receiver_name=session.receiver_name,
        product_id=session.product_id,
        call_type=session.call_type,
        status=session.status,
        sdp_offer=session.sdp_offer,
        sdp_answer=session.sdp_answer,
        started_at=session.started_at,
        connected_at=session.connected_at,
        ended_at=session.ended_at,
        product_title=session.product.title if session.product else None,
    )


@router.post(
    "/initiate",
    response_model=CallSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate a call (Caller -> Receiver)",
)
def initiate_call(
    payload: CallInitiateRequest,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> CallSessionRead:
    """Caller places a call. Sets status to 'ringing' and notifies the receiver."""
    if current_user.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is blocked from placing calls.",
        )

    if current_user.id == payload.receiver_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot place a call to yourself.",
        )

    receiver = db.query(User).filter(User.id == payload.receiver_id).first()
    if not receiver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receiver not found.",
        )

    product = None
    if payload.product_id:
        product = db.query(Product).filter(Product.id == payload.product_id).first()

    session = CallSession(
        caller_id=current_user.id,
        caller_name=current_user.name,
        receiver_id=receiver.id,
        receiver_name=receiver.name,
        product_id=product.id if product else None,
        call_type=payload.call_type,
        status="ringing",
        sdp_offer=payload.sdp_offer,
        started_at=_utcnow(),
    )
    db.add(session)

    # Trigger high-priority incoming call notification for Phone 2
    product_hint = f" · re: {product.title}" if product else ""
    db.add(
        Notification(
            user_id=receiver.id,
            title=f"📞 Incoming {payload.call_type.capitalize()} Call",
            body=f"{current_user.name} is calling you{product_hint}",
            type="incoming_call",
            reference_id=str(session.id),
        )
    )

    db.commit()
    db.refresh(session)
    logger.info("Call %s initiated by %s to %s", session.id, current_user.email, receiver.email)
    return _to_read(session)


@router.get(
    "/incoming",
    response_model=CallSessionRead | None,
    summary="Poll for incoming ringing calls (Phone 2)",
)
def get_incoming_call(
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> CallSessionRead | None:
    """Returns the most recent active 'ringing' call within the last 45 seconds."""
    cutoff = _utcnow() - timedelta(seconds=45)
    call = (
        db.query(CallSession)
        .filter(
            CallSession.receiver_id == current_user.id,
            CallSession.status == "ringing",
            CallSession.started_at >= cutoff,
        )
        .order_by(CallSession.started_at.desc())
        .first()
    )
    return _to_read(call) if call else None


@router.get(
    "/{call_id}",
    response_model=CallSessionRead,
    summary="Poll call status & signaling",
)
def get_call_session(
    call_id: UUID,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> CallSessionRead:
    """Returns live call state so Phone 1 detects when Phone 2 answers/declines."""
    call = db.query(CallSession).filter(CallSession.id == call_id).first()
    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call session not found.",
        )
    if current_user.id not in (call.caller_id, call.receiver_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to inspect this call.",
        )

    # Auto-expire calls ringing longer than 45 seconds to 'missed'
    if call.status == "ringing" and _diff_seconds(_utcnow(), call.started_at) > 45:
        call.status = "missed"
        call.ended_at = _utcnow()
        db.commit()
        db.refresh(call)

    return _to_read(call)


@router.post(
    "/{call_id}/answer",
    response_model=CallSessionRead,
    summary="Answer an incoming call (Phone 2)",
)
def answer_call(
    call_id: UUID,
    payload: CallSignalRequest | None = None,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> CallSessionRead:
    """Phone 2 accepts the call. Switches status to 'connected'."""
    call = db.query(CallSession).filter(CallSession.id == call_id).first()
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found.")
    if call.receiver_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only receiver can answer.")

    call.status = "connected"
    call.connected_at = _utcnow()
    if payload and payload.sdp_answer:
        call.sdp_answer = payload.sdp_answer

    db.commit()
    db.refresh(call)
    logger.info("Call %s answered by receiver %s", call.id, current_user.email)
    return _to_read(call)


@router.post(
    "/{call_id}/decline",
    response_model=CallSessionRead,
    summary="Decline an incoming call (Phone 2)",
)
def decline_call(
    call_id: UUID,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> CallSessionRead:
    """Phone 2 declines the call."""
    call = db.query(CallSession).filter(CallSession.id == call_id).first()
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found.")
    if call.receiver_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only receiver can decline.")

    call.status = "declined"
    call.ended_at = _utcnow()

    # Log into chat thread if product is attached
    if call.product_id:
        db.add(
            ChatMessage(
                product_id=call.product_id,
                sender_id=call.caller_id,
                receiver_id=call.receiver_id,
                message=f"📞 Missed / Declined {call.call_type} call",
            )
        )

    db.commit()
    db.refresh(call)
    logger.info("Call %s declined by %s", call.id, current_user.email)
    return _to_read(call)


@router.post(
    "/{call_id}/end",
    response_model=CallSessionRead,
    summary="End an active or ringing call",
)
def end_call(
    call_id: UUID,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> CallSessionRead:
    """Either phone hangs up. Calculates duration and logs summary in chat."""
    call = db.query(CallSession).filter(CallSession.id == call_id).first()
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found.")
    if current_user.id not in (call.caller_id, call.receiver_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant.")

    now = _utcnow()
    call.ended_at = now
    duration_sec = _diff_seconds(now, call.connected_at)

    call.status = "ended"

    # Log call duration in chat if product is associated
    if call.product_id:
        m, s = divmod(duration_sec, 60)
        time_str = f"{m}m {s}s" if m > 0 else f"{s}s"
        label = f"📞 {call.call_type.capitalize()} call · {time_str}" if duration_sec > 0 else f"📞 Missed {call.call_type} call"
        db.add(
            ChatMessage(
                product_id=call.product_id,
                sender_id=call.caller_id,
                receiver_id=call.receiver_id,
                message=label,
            )
        )

    db.commit()
    db.refresh(call)
    logger.info("Call %s ended (duration: %ss)", call.id, duration_sec)
    return _to_read(call)


@router.post(
    "/{call_id}/signal",
    summary="Exchange WebRTC SDP or audio chunks",
)
def send_call_signal(
    call_id: UUID,
    payload: CallSignalRequest,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Saves SDP offer/answer or appends audio chunk for the other peer."""
    call = db.query(CallSession).filter(CallSession.id == call_id).first()
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found.")
    if current_user.id not in (call.caller_id, call.receiver_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")

    if payload.sdp_offer:
        call.sdp_offer = payload.sdp_offer
    if payload.sdp_answer:
        call.sdp_answer = payload.sdp_answer
    if payload.audio_chunk:
        try:
            chunks = json.loads(call.audio_chunks_json or "[]")
        except Exception:
            chunks = []
        chunks.append({
            "sender_id": str(current_user.id),
            "chunk": payload.audio_chunk,
            "ts": _utcnow().isoformat(),
        })
        # Keep buffer bounded to last 20 chunks
        call.audio_chunks_json = json.dumps(chunks[-20:])

    db.commit()
    return {"status": "ok"}


@router.get(
    "/{call_id}/signal",
    summary="Read latest WebRTC SDP and audio chunks",
)
def get_call_signal(
    call_id: UUID,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Fetches SDP offer, answer, and audio chunks from peer."""
    call = db.query(CallSession).filter(CallSession.id == call_id).first()
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found.")
    if current_user.id not in (call.caller_id, call.receiver_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")

    try:
        chunks = json.loads(call.audio_chunks_json or "[]")
    except Exception:
        chunks = []

    # Filter chunks from the other peer
    peer_chunks = [c for c in chunks if c.get("sender_id") != str(current_user.id)]

    return {
        "call_id": str(call.id),
        "status": call.status,
        "sdp_offer": call.sdp_offer,
        "sdp_answer": call.sdp_answer,
        "peer_audio_chunks": peer_chunks,
    }
