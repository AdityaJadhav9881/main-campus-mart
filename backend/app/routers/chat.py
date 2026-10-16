"""
routers/chat.py
===============
Buyer-Seller messaging + the "Ask CampusMart AI" student assistant (Task 5).

    POST /chats/messages                                 - send one message
    GET  /chats/conversations                            - inbox threads
    GET  /chats/messages/{product_id}/{other_user_id}    - full thread history
    POST /ai/chat                                        - assistant replies

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
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..ai import vision_master
from ..auth import extract_uid, get_or_create_current_user, verify_firebase_token
from ..database import get_db
from ..models import ChatMessage, Product, User
from ..schemas import (
    AiChatRequest,
    AiChatResponse,
    ChatMessageCreate,
    ChatMessageRead,
    ConversationRead,
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
        created_at=message.created_at,
        is_read=message.read_at is not None,
    )


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

    message = ChatMessage(
        product_id=product.id,
        sender_id=sender.id,
        receiver_id=receiver.id,
        message=payload.message.strip(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    logger.info(
        "Chat: %s -> %s on '%s'",
        sender.email,
        receiver.email,
        product.title,
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
                last_message=last.message,
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


_ASSISTANT_SYSTEM = """You are "CampusMart AI", the helpful shopping assistant \
inside Campus Mart Ai - a second-hand marketplace for Indian college students.

Rules:
  * Prices are ALWAYS Indian Rupees (₹). Never use $ or USD.
  * Be concise and friendly (2-5 sentences unless the student asks for detail).
  * Recommend ONLY from the LIVE LISTINGS below when asked for items; quote the \
exact ₹ price and mention why it is a good deal. If nothing matches, say so and \
suggest what to search for instead.
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


def _local_catalog_reply(
    message: str,
    products: list[Product],
) -> tuple[str, list[UUID]]:
    """Smart campus marketplace assistant engine for live active products."""
    msg_lower = (message or "").strip().lower()
    tokens = [
        token
        for token in msg_lower.split()
        if len(token) > 2 and token not in {"the", "and", "for", "with", "want", "show", "tell", "give", "please"}
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

    scored: list[tuple[int, Product]] = []
    for product in products:
        haystack = " ".join(
            filter(
                None,
                [
                    product.title.lower(),
                    product.description.lower(),
                    product.category.lower(),
                    (product.ai_tags or "").lower(),
                ],
            )
        )
        score = sum(1 for token in tokens if token in haystack)
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
                "Feel free to ask about specific gear (e.g., 'calculator', 'electronics', 'books') or ask for price advice in ₹!"
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
    """Ids of live products the LLM reply actually mentioned (by title)."""
    lowered = reply.lower()
    ids: list[UUID] = []
    for product in products:
        title = product.title.strip()
        if len(title) > 6 and title.lower() in lowered:
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
    _current_user(db, token)  # profile required; blocked users already 403'd

    catalog, products = _catalog_lines(db)
    system = _ASSISTANT_SYSTEM.format(catalog=catalog or "(no active listings yet)")
    history: list[dict[str, str]] = [
        {"role": turn.role, "content": turn.content} for turn in payload.history
    ]

    try:
        reply = vision_master.chat_completion(
            db,
            system=system,
            history=history,
            user_message=payload.message,
        )
        return AiChatResponse(
            reply=reply.strip(),
            source="llm",
            recommended_product_ids=_recommended_ids(reply, products),
        )
    except Exception as exc:  # noqa: BLE001 - upstream/outage -> local assistant
        logger.warning("AI chat LLM unavailable (%s); catalog assistant answers", exc)
        reply, ids = _local_catalog_reply(payload.message, products)
        return AiChatResponse(reply=reply, source="catalog", recommended_product_ids=ids)
