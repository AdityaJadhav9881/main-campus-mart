"""
routers/chat.py
===============
Buyer-Seller messaging + the "Ask CampusMart AI" student assistant (Task 5)
plus saved AI conversations, call logs, and chat notifications.

    POST /chats/messages                                 - send one message
    GET  /chats/conversations                            - inbox threads
    GET  /chats/messages/{product_id}/{other_user_id}    - full thread history
    POST /chats/call-event                               - voice/video call log
    POST /ai/chat                                        - assistant replies
    GET  /ai/sessions                                    - saved conversations
    POST /ai/sessions                                    - create a session
    GET  /ai/sessions/{session_id}                       - full transcript
    DELETE /ai/sessions/{session_id}                     - delete a conversation

Design notes
------------
* A THREAD is scoped to (product_id, other_user_id): the same two students
  talking about two different products are two separate conversations, which
  is exactly how the Messages tab groups them.
* Opening a thread (GET history) marks the messages the caller RECEIVED as
  read (`read_at`), which drives the unread badge on the inbox.
* Every chat endpoint runs through `verify_firebase_token`, so a terminated
  (blocked) account gets the canonical 403 ACCOUNT_TERMINATED before it can
  read or write anything.
* POST /ai/chat is catalog-aware: the active listings from PostgreSQL (with
  ₹ prices) are injected into the system prompt so the assistant can recommend
  REAL campus items. When no LLM API key is configured - or the provider
  fails - a deterministic local catalog assistant answers instead (source:
  'catalog'), so the tab always replies.
* Every AI turn is persisted to AiChatSession/AiChatMessage so the Gemini-
  style history drawer can replay conversations; new sessions get a smart
  4-word title derived from the first prompt.
* Sending a message (or finishing a call) creates a Notification for the
  receiver, which the Flutter bell icon polls.
"""

import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..ai import vision_master
from ..auth import extract_uid, get_or_create_current_user, verify_firebase_token
from ..database import get_db
from ..models import (
    AiChatMessage,
    AiChatSession,
    ChatMessage,
    Notification,
    Product,
    User,
)
from ..schemas import (
    AiChatRequest,
    AiChatResponse,
    AiSessionDetail,
    AiSessionMessageRead,
    AiSessionRead,
    CallEventRequest,
    ChatMessageCreate,
    ChatMessageRead,
    ConversationRead,
    PriceEstimateRequest,
    PriceEstimateResponse,
)

logger = logging.getLogger(__name__)

# Prefix + path combine to "POST /chats/messages" etc.
router = APIRouter(prefix="/chats", tags=["chats"])

# Separate router so the assistant lives at "POST /ai/chat" (registered in
# main.py alongside the chats router).
ai_router = APIRouter(prefix="/ai", tags=["ai"])

# How many recent active listings are handed to the assistant as context.
CATALOG_CONTEXT_LIMIT = 40


def _current_user(db: Session, token: dict) -> User:
    """Resolve the caller's profile row (auto-provisions if missing)."""
    return get_or_create_current_user(db, token)


def _serialize(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=message.id,
        product_id=message.product_id,
        sender_id=message.sender_id,
        receiver_id=message.receiver_id,
        message=message.message,
        image_url=message.image_url,
        created_at=message.created_at,
        is_read=message.read_at is not None,
    )


def _notify(
    db: Session,
    user_id: UUID,
    title: str,
    body: str,
    type_: str,
    reference_id: str | None = None,
) -> None:
    """Create one bell-icon notification (never blocks the calling request)."""
    try:
        db.add(
            Notification(
                user_id=user_id,
                title=title[:200],
                body=body[:500],
                type=type_,
                reference_id=reference_id,
                is_read=False,
            )
        )
    except Exception as exc:  # noqa: BLE001 - notifications are best-effort
        logger.warning("notification insert failed (%s): %s", type_, exc)


# =============================================================================
# Send
# =============================================================================
@router.post(
    "/messages",
    response_model=ChatMessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send a buyer-seller message",
)
def send_message(
    payload: ChatMessageCreate,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> ChatMessageRead:
    """Store one message on a product's thread.

    Guards: product must exist, receiver must be a different student with a
    profile, and the caller must own a profile (all mapped to actionable 400s).
    """
    sender = _current_user(db, token)

    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found (it may have been removed).",
        )

    if payload.receiver_id == sender.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot message yourself about your own listing.",
        )

    receiver = db.query(User).filter(User.id == payload.receiver_id).first()
    if receiver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found.",
        )

    image_url = (payload.image_url or "").strip() or None
    message = ChatMessage(
        product_id=product.id,
        sender_id=sender.id,
        receiver_id=receiver.id,
        message=payload.message.strip(),
        image_url=image_url,
    )
    db.add(message)

    # A4: mirror the message into the receiver's bell-icon feed.
    preview = message.message.strip()[:80] or "Sent a photo"
    _notify(
        db,
        receiver.id,
        f"💬 New message from {sender.name}",
        f"{preview} · re: {product.title}",
        "chat_message",
        reference_id=str(sender.id),
    )

    db.commit()
    db.refresh(message)
    logger.info(
        "Chat: %s -> %s on '%s'%s",
        sender.email,
        receiver.email,
        product.title,
        " (photo)" if image_url else "",
    )
    return _serialize(message)


# =============================================================================
# Inbox
# =============================================================================
@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    summary="My chat threads (grouped by product + other student)",
)
def list_conversations(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> list[ConversationRead]:
    """Every thread the logged-in student participates in, newest first.

    Each row carries the counterparty name, the product title/image/price, the
    last message, whether it came from me, and the unread count for the badge.
    """
    me = _current_user(db, token)

    rows = (
        db.query(ChatMessage)
        .options(
            joinedload(ChatMessage.product),
            joinedload(ChatMessage.sender),
            joinedload(ChatMessage.receiver),
        )
        .filter(or_(ChatMessage.sender_id == me.id, ChatMessage.receiver_id == me.id))
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    # Ascending order -> the last write per key wins as the thread's latest.
    latest: dict[tuple[str, str], ChatMessage] = {}
    unread: dict[tuple[str, str], int] = {}
    for message in rows:
        other_id = (
            message.receiver_id if message.sender_id == me.id else message.sender_id
        )
        key = (str(message.product_id), str(other_id))
        latest[key] = message
        if message.receiver_id == me.id and message.read_at is None:
            unread[key] = unread.get(key, 0) + 1

    conversations: list[ConversationRead] = []
    for (product_id, other_id), last in latest.items():
        other = last.receiver if last.sender_id == me.id else last.sender
        product = last.product
        if product is None or other is None:
            continue  # cascade-deleted product/user; skip the dangling row
        photos = [u for u in (product.image_urls or []) if u]
        conversations.append(
            ConversationRead(
                product_id=product.id,
                other_user_id=other.id,
                other_user_name=other.name,
                product_title=product.title,
                product_image_url=(
                    photos[0] if photos else (product.image_url or None)
                ),
                product_price=product.listed_price,
                last_message=(
                    last.message
                    if last.message.strip()
                    else ("[Photo]" if last.image_url else "[Message]")
                ),
                last_message_at=last.created_at,
                last_message_is_mine=last.sender_id == me.id,
                unread_count=unread.get((product_id, other_id), 0),
                unread=unread.get((product_id, other_id), 0) > 0,
            )
        )

    conversations.sort(
        key=lambda item: item.last_message_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return conversations


# =============================================================================
# Thread history
# =============================================================================
@router.get(
    "/messages/{product_id}/{other_user_id}",
    response_model=list[ChatMessageRead],
    summary="Full message history for one product thread",
)
def list_thread_messages(
    product_id: UUID,
    other_user_id: UUID,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> list[ChatMessageRead]:
    """All messages between the caller and `other_user_id` on one product.

    Messages the caller RECEIVED are marked read here (opening the thread
    clears their unread badge). Returns oldest -> newest.
    """
    me = _current_user(db, token)

    rows = (
        db.query(ChatMessage)
        .options(
            joinedload(ChatMessage.product),
            joinedload(ChatMessage.sender),
            joinedload(ChatMessage.receiver),
        )
        .filter(
            ChatMessage.product_id == product_id,
            or_(
                (ChatMessage.sender_id == me.id) & (ChatMessage.receiver_id == other_user_id),
                (ChatMessage.sender_id == other_user_id) & (ChatMessage.receiver_id == me.id),
            ),
        )
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    changed = False
    now = datetime.now(timezone.utc)
    for message in rows:
        if message.receiver_id == me.id and message.read_at is None:
            message.read_at = now
            changed = True
    if changed:
        db.commit()

    return [_serialize(message) for message in rows]


# =============================================================================
# Voice / video call events (in-app call screen logs)
# =============================================================================
def _format_call_duration(seconds: int) -> str:
    """'1m 24s' / '45s' / '<1m' style label for the call bubble."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s" if seconds > 0 else "<1m"
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}m {remainder}s" if remainder else f"{minutes}m"


@router.post(
    "/call-event",
    response_model=ChatMessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Log a finished voice/video call into the product thread",
)
def record_call_event(
    payload: CallEventRequest,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> ChatMessageRead:
    """Persist the outcome of an in-app call as a thread bubble.

    Called by the Flutter call screen when the call ends. Produces a normal
    ChatMessage ("📞 Voice call · 1m 24s") plus a Notification for the
    receiver, so missed calls surface on the bell icon too.
    """
    caller = _current_user(db, token)

    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found (it may have been removed).",
        )

    if payload.receiver_id == caller.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot log a call with yourself.",
        )

    receiver = db.query(User).filter(User.id == payload.receiver_id).first()
    if receiver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found.",
        )

    icon = "📞 Voice call" if payload.call_type == "voice" else "📹 Video call"
    if payload.status == "completed":
        label = f"{icon} · {_format_call_duration(payload.duration_seconds)}"
    elif payload.status == "missed":
        label = f"{icon} · Missed"
    else:
        label = f"{icon} · Declined"

    message = ChatMessage(
        product_id=product.id,
        sender_id=caller.id,
        receiver_id=receiver.id,
        message=label,
        image_url=None,
    )
    db.add(message)

    if payload.status == "completed":
        title = f"{icon} with {caller.name}"
    else:
        title = f"Missed {payload.call_type} call from {caller.name}"
    _notify(
        db,
        receiver.id,
        title,
        f"{label} · re: {product.title}",
        "call",
        reference_id=str(caller.id),
    )

    db.commit()
    db.refresh(message)
    logger.info(
        "Call event: %s -> %s (%s, %ss) on '%s'",
        caller.email, receiver.email, payload.status,
        payload.duration_seconds, product.title,
    )
    return _serialize(message)


# =============================================================================
# Ask CampusMart AI assistant - saved sessions (history drawer)
# =============================================================================
# Filler words ignored when deriving a 4-word session title.
_TITLE_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "can", "could", "you", "me",
    "my", "i", "what", "which", "how", "do", "does", "did", "please", "tell",
    "about", "for", "of", "to", "in", "on", "it", "this", "that", "give",
    "show", "find", "help", "with", "and", "or", "am", "be",
}


def _derive_session_title(text: str) -> str:
    """Smart 4-word title from the student's first prompt."""
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    picked: list[str] = []
    for index, word in enumerate(words):
        # Skip filler words only while the title is still empty.
        if not picked and word.lower().strip("?!.,") in _TITLE_STOPWORDS and index < len(words) - 1:
            continue
        picked.append(word)
        if len(picked) >= 4:
            break
    if not picked:
        return "New chat"
    title = " ".join(picked).strip("?!.,")[:60]
    if not title:
        return "New chat"
    return title[0].upper() + title[1:]


def _session_read(session: AiChatSession) -> AiSessionRead:
    messages = list(session.messages or [])
    last = messages[-1] if messages else None
    return AiSessionRead(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=len(messages),
        last_message=(last.content.strip()[:120] or ("[Photo]" if last.image_url else None)) if last else None,
    )


@ai_router.get(
    "/sessions",
    response_model=list[AiSessionRead],
    summary="My saved AI conversations (newest first)",
)
def list_ai_sessions(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> list[AiSessionRead]:
    """History drawer payload: sessions grouped client-side by date."""
    me = _current_user(db, token)
    rows = (
        db.query(AiChatSession)
        .filter(AiChatSession.user_id == me.id)
        .order_by(AiChatSession.updated_at.desc())
        .limit(60)
        .all()
    )
    return [_session_read(session) for session in rows]


@ai_router.post(
    "/sessions",
    response_model=AiSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a fresh AI conversation",
)
def create_ai_session(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> AiSessionRead:
    """Create an empty session ("New chat"); the first /ai/chat call retitles it."""
    me = _current_user(db, token)
    session = AiChatSession(user_id=me.id, title="New chat")
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_read(session)


@ai_router.get(
    "/sessions/{session_id}",
    response_model=AiSessionDetail,
    summary="Full transcript of one saved AI conversation",
)
def get_ai_session(
    session_id: UUID,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> AiSessionDetail:
    """Replay a conversation (owner only; others get 404)."""
    me = _current_user(db, token)
    session = (
        db.query(AiChatSession)
        .filter(AiChatSession.id == session_id, AiChatSession.user_id == me.id)
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found.",
        )

    messages = [
        AiSessionMessageRead(
            id=message.id,
            role=message.role,
            content=message.content,
            image_url=message.image_url,
            matched_product_ids=[
                UUID(pid)
                for pid in _load_product_ids(message.matched_products_json)
            ],
            created_at=message.created_at,
        )
        for message in session.messages
    ]
    base = _session_read(session)
    return AiSessionDetail(**base.model_dump(), messages=messages)


@ai_router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved AI conversation",
)
def delete_ai_session(
    session_id: UUID,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> None:
    """Owner-only hard delete (messages cascade)."""
    me = _current_user(db, token)
    session = (
        db.query(AiChatSession)
        .filter(AiChatSession.id == session_id, AiChatSession.user_id == me.id)
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found.",
        )
    db.delete(session)
    db.commit()
    return None


def _load_product_ids(raw: str | None) -> list[str]:
    """Parse the matched-products JSON blob safely (never raises)."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item]


def _persist_ai_turn(
    db: Session,
    session: AiChatSession,
    user_message: str,
    image_url: str | None,
    reply: str,
    recommended_ids: list[UUID],
) -> None:
    """Append the user prompt + assistant reply to the session, retitle if new."""
    if session.title in ("", "New chat") and (user_message.strip() or image_url):
        session.title = _derive_session_title(user_message or "Photo inspection")

    db.add(
        AiChatMessage(
            session_id=session.id,
            role="user",
            content=user_message.strip(),
            image_url=image_url,
        )
    )
    db.add(
        AiChatMessage(
            session_id=session.id,
            role="assistant",
            content=reply.strip(),
            image_url=None,
            matched_products_json=json.dumps([str(pid) for pid in recommended_ids]),
        )
    )
    session.updated_at = datetime.now(timezone.utc)
    db.commit()


# =============================================================================
# Ask CampusMart AI assistant
# =============================================================================
def _catalog_lines(db: Session) -> tuple[str, list[Product]]:
    """Render the live marketplace as compact ₹ context lines for the LLM."""
    products = (
        db.query(Product)
        .options(joinedload(Product.seller))
        .filter(Product.status == "active")
        .order_by(Product.created_at.desc())
        .limit(CATALOG_CONTEXT_LIMIT)
        .all()
    )
    lines = []
    for index, product in enumerate(products, start=1):
        tags = f" | tags: {product.ai_tags}" if product.ai_tags else ""
        lines.append(
            f"{index}. {product.title} | {product.category} | "
            f"₹{product.listed_price:,.0f} | {product.condition} | "
            f"trust {(product.seller_trust_score if product.seller else 5.0):.1f}/5"
            f"{tags} | id={product.id}"
        )
    return "\n".join(lines), products


_ASSISTANT_SYSTEM = """You are "CampusMart AI", the friendly all-round companion \
inside Campus Mart Ai - a second-hand marketplace app for Indian college students.

You are a GENERAL assistant: answer ANY question the student asks - academics, \
hostel life, gadgets, study tips, comparisons, recommendations, general knowledge - \
not just marketplace questions. Be warm, upbeat and genuinely helpful.

Rules:
  * Prices are ALWAYS Indian Rupees (₹). Never use $ or USD.
  * Be concise and friendly (2-5 sentences unless the student asks for detail).
  * If the student attaches a PHOTO, inspect it carefully: identify the item, \
brand/model if visible, judge its condition from the image, and give an honest \
fair resale price in ₹ for the Indian campus market (compare with the item's \
current Indian retail price - a working used unit is usually worth 55-85% of \
retail, and never quote a tiny fraction of retail for a functional item). Also \
suggest a tempting marketplace title if they want to sell it.
  * When asked for items to buy, recommend ONLY from the LIVE LISTINGS below; \
quote the exact ₹ price and mention why it is a good deal. If nothing matches, \
say so and suggest what to search for instead.
  * For "is this price fair?" questions, compare against typical Indian campus \
second-hand prices (pen ₹10-50, used textbook ₹250-450, calculator ₹300-900, \
headphones ₹500-3,000, used Bluetooth speaker ₹4,000-7,500, laptop ₹12,000-45,000).
  * Never invent listings, ids, or features that are not in the data below.
  * You cannot buy items - direct students to the item's page to Chat with the \
seller or Buy Now.

LIVE LISTINGS:
{catalog}"""

_CATALOG_FALLBACK_INTRO = (
    "Here's what I found on Campus Mart Ai matching that"
)


STEM_SYNONYMS: dict[str, list[str]] = {
    "speaker": ["soundlink", "bose", "bluetooth", "audio", "jbl", "speaker", "soundbar"],
    "speakers": ["soundlink", "bose", "bluetooth", "audio", "jbl", "speaker", "soundbar"],
    "calculator": ["casio", "calculator", "fx-991", "scientific", "classwiz"],
    "calculators": ["casio", "calculator", "fx-991", "scientific", "classwiz"],
    "book": ["book", "textbook", "notes", "edition", "academic", "guide", "manual", "cengage"],
    "books": ["book", "textbook", "notes", "edition", "academic", "guide", "manual", "cengage"],
    "textbook": ["book", "textbook", "notes", "edition", "academic", "guide", "manual"],
    "textbooks": ["book", "textbook", "notes", "edition", "academic", "guide", "manual"],
    "laptop": ["laptop", "macbook", "notebook", "computer", "thinkpad", "dell", "hp", "pc"],
    "laptops": ["laptop", "macbook", "notebook", "computer", "thinkpad", "dell", "hp", "pc"],
    "lab": ["lab", "multimeter", "drafter", "instruments", "oscilloscope", "vernier", "calliper", "breadboard", "arduino"],
    "headphone": ["headphone", "earphone", "airpods", "earbuds", "audio", "tws", "wireless"],
    "headphones": ["headphone", "earphone", "airpods", "earbuds", "audio", "tws", "wireless"],
    "phone": ["phone", "smartphone", "iphone", "android", "mobile", "oneplus", "samsung"],
    "phones": ["phone", "smartphone", "iphone", "android", "mobile", "oneplus", "samsung"],
    "stationery": ["pen", "pencil", "stationery", "notebook", "register", "marker", "folder"],
}


def _local_catalog_reply(
    message: str,
    products: list[Product],
) -> tuple[str, list[UUID]]:
    """Smart campus marketplace assistant engine for live active products."""
    msg_lower = (message or "").strip().lower()
    raw_tokens = [
        token
        for token in msg_lower.split()
        if len(token) > 2 and token not in {"the", "and", "for", "with", "want", "show", "tell", "give", "please", "have", "you"}
    ]

    is_deal_query = any(
        w in msg_lower
        for w in [
            "deal", "deals", "best", "cheap", "offer", "discount", "save", "saving", "top", "recommend", "pick"
        ]
    )

    if is_deal_query and products:
        def _deal_score(p: Product) -> float:
            if p.suggested_price and p.suggested_price > p.listed_price:
                return (p.suggested_price - p.listed_price) / p.suggested_price
            return 0.0

        deals = sorted(
            products,
            key=lambda p: (-_deal_score(p), -(p.seller_trust_score or 4.0), p.listed_price),
        )
        top = deals[:5]
        lines = ["Here are the best verified deals currently live on Campus Mart Ai (prices in ₹):"]
        for rank, product in enumerate(top, start=1):
            savings_note = ""
            if product.suggested_price and product.listed_price < product.suggested_price:
                pct = int(((product.suggested_price - product.listed_price) / product.suggested_price) * 100)
                diff = int(product.suggested_price - product.listed_price)
                savings_note = f" (🔥 Save ₹{diff} • {pct}% below AI value)"
            lines.append(
                f"{rank}. {product.title} — ₹{product.listed_price:,.0f}{savings_note} "
                f"[{product.condition}, {product.category}]"
            )
        lines.append(
            "Open Discover to view verified photos, inspection reports, or to Chat with the seller directly!"
        )
        return "\n\n".join(lines), [product.id for product in top]

    # Gather search tokens including synonyms
    extra_tokens: set[str] = set()
    for word, syns in STEM_SYNONYMS.items():
        if word in msg_lower or any(t.startswith(word) for t in raw_tokens):
            extra_tokens.update(syns)

    all_search_tokens = set(raw_tokens) | extra_tokens

    scored: list[tuple[int, Product]] = []
    for product in products:
        title_lower = product.title.lower()
        haystack = " ".join(
            filter(
                None,
                [
                    title_lower,
                    product.description.lower(),
                    product.category.lower(),
                    (product.ai_tags or "").lower(),
                ],
            )
        )
        score = 0
        for token in all_search_tokens:
            if token in title_lower:
                score += 3
            elif token in haystack:
                score += 1
        if score:
            scored.append((score, product))
    scored.sort(key=lambda pair: (-pair[0], pair[1].listed_price))

    if not scored:
        if products:
            top_default = sorted(
                products,
                key=lambda p: (-(p.seller_trust_score or 4.0), p.listed_price),
            )[:4]
            lines = [
                "Here are some top-rated active listings on campus (prices in ₹):",
            ]
            for rank, product in enumerate(top_default, start=1):
                lines.append(
                    f"{rank}. {product.title} — ₹{product.listed_price:,.0f} "
                    f"({product.condition}, {product.category})"
                )
            lines.append(
                "Feel free to ask about specific gear (e.g., 'calculator', 'electronics', 'books', 'speaker') or ask for price advice in ₹!"
            )
            return "\n\n".join(lines), [product.id for product in top_default]
        return (
            "No active listings found on campus yet. Try asking again soon, or list your own gear on the Sell tab!",
            [],
        )

    top = [p for _, p in scored[:5]]
    lines = [f"{_CATALOG_FALLBACK_INTRO} (prices in ₹):"]
    for rank, product in enumerate(top, start=1):
        deal = (
            f" — 🔥 Great deal (AI fair value: ₹{product.suggested_price:,.0f})"
            if product.suggested_price and product.listed_price < product.suggested_price
            else ""
        )
        lines.append(
            f"{rank}. {product.title} — ₹{product.listed_price:,.0f} "
            f"({product.condition}, {product.category}){deal}"
        )
    lines.append(
        "Open Discover to view verified photos, check AI reports, and Chat with the seller!"
    )
    return "\n\n".join(lines), [product.id for product in top]


def _recommended_ids(reply: str, products: list[Product]) -> list[UUID]:
    """Ids of live products the LLM reply actually mentioned (by title, id or keyword)."""
    lowered = reply.lower()
    ids: list[UUID] = []
    # 1. Exact UUID or exact title match
    for product in products:
        if str(product.id) in reply:
            if product.id not in ids:
                ids.append(product.id)
        elif len(product.title.strip()) > 4 and product.title.strip().lower() in lowered:
            if product.id not in ids:
                ids.append(product.id)
        if len(ids) >= 5:
            return ids

    # 2. Key phrase match (e.g. brand + model or distinctive words in title)
    for product in products:
        title_words = [w for w in re.findall(r"[a-z0-9]+", product.title.lower()) if len(w) > 3]
        if len(title_words) >= 2:
            match_count = sum(1 for w in title_words if w in lowered)
            if match_count >= 2 and product.id not in ids:
                ids.append(product.id)
        if len(ids) >= 5:
            break
    return ids


@ai_router.post(
    "/chat",
    response_model=AiChatResponse,
    summary="Ask CampusMart AI (catalog-aware student assistant)",
)
def ai_chat(
    payload: AiChatRequest,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> AiChatResponse:
    """Chat with the campus assistant: product search, fair-price checks, help.

    Uses the SAME configured LLM provider as the vision engine (SystemConfig),
    seeded with the live PostgreSQL catalogue so answers reference real items
    and ₹ prices. Falls back to a local catalogue assistant when no key is
    configured or the provider errors - the tab never leaves students hanging.
    """
    me = _current_user(db, token)  # profile required; blocked users already 403'd

    # --- Resolve or create the saved session (history drawer) ----------------
    session: AiChatSession | None = None
    if payload.session_id is not None:
        session = (
            db.query(AiChatSession)
            .filter(
                AiChatSession.id == payload.session_id,
                AiChatSession.user_id == me.id,
            )
            .first()
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found.",
            )
    if session is None:
        session = AiChatSession(user_id=me.id, title="New chat")
        db.add(session)
        db.commit()
        db.refresh(session)

    catalog, products = _catalog_lines(db)
    system = _ASSISTANT_SYSTEM.format(catalog=catalog or "(no active listings yet)")
    history: list[dict[str, str]] = [
        {"role": turn.role, "content": turn.content} for turn in payload.history
    ]

    # Photo-only prompts get a default instruction so the model always has
    # text to act on (providers reject empty text parts).
    user_message = payload.message.strip()
    if not user_message and payload.image_url:
        user_message = (
            "I attached a photo - inspect it and tell me what it is, its "
            "condition, and a fair resale price in ₹."
        )

    try:
        reply = vision_master.chat_completion(
            db,
            system=system,
            history=history,
            user_message=user_message,
            image_url=payload.image_url,
        )
        reply = reply.strip()
        ids = _recommended_ids(reply, products)
        _persist_ai_turn(db, session, payload.message, payload.image_url, reply, ids)
        return AiChatResponse(
            reply=reply,
            source="llm",
            recommended_product_ids=ids,
            session_id=session.id,
            session_title=session.title,
        )
    except Exception as exc:  # noqa: BLE001 - upstream/outage -> local assistant
        logger.warning("AI chat LLM unavailable (%s); catalog assistant answers", exc)
        if payload.image_url and not payload.message.strip():
            fallback_reply = (
                "I received your photo! The online Vision AI is waking up "
                "right now, so I could not inspect it this second - ask me "
                "again in a moment for a full look (brand, condition, fair "
                "₹ price). Meanwhile, anything else I can help with?"
            )
            _persist_ai_turn(
                db, session, payload.message, payload.image_url,
                fallback_reply, [],
            )
            return AiChatResponse(
                reply=fallback_reply,
                source="catalog",
                recommended_product_ids=[],
                session_id=session.id,
                session_title=session.title,
            )
        reply, ids = _local_catalog_reply(payload.message, products)
        _persist_ai_turn(db, session, payload.message, payload.image_url, reply, ids)
        return AiChatResponse(
            reply=reply,
            source="catalog",
            recommended_product_ids=ids,
            session_id=session.id,
            session_title=session.title,
        )


@ai_router.post(
    "/estimate-price",
    response_model=PriceEstimateResponse,
    summary="Public web price estimator",
)
def estimate_price(
    payload: PriceEstimateRequest,
    db: Session = Depends(get_db),
) -> PriceEstimateResponse:
    """Public, unauthenticated single-item price estimator for the web sandbox.

    Uses Google Gemini Vision + Google Search Grounding (or active provider) to:
    1. Filter out phone/app screenshots, memes, selfies, and non-product images.
    2. Identify brand, model, and search Indian retail sites for new MRP in ₹.
    3. Calculate fair second-hand campus resale value in ₹.
    """
    res = vision_master.analyze_web_estimator_item(
        db,
        image_base64=payload.image_base64,
        image_url=payload.image_url,
        title=payload.title,
        condition=payload.condition,
        age_years=payload.age_years,
    )
    return PriceEstimateResponse(**res)

