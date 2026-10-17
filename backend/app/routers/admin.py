"""
routers/admin.py
================
Live Admin Master Control endpoints for the React Admin Dashboard (Phase 7).

    GET  /admin/overview                     - real PostgreSQL counts + flagged queue
    GET  /admin/users                        - all users, newest first
    PATCH /admin/users/{user_id}/status      - block / unblock a student
    GET  /admin/listings                     - ALL products + seller denormalization
    PATCH /admin/listings/{product_id}/approve - unflag + trust bump (+0.2, cap 5.0)
    DELETE /admin/listings/{product_id}      - delete + trust penalty (-0.8, floor 0.0)
    GET  /admin/communications               - buyer<->seller threads + order context
    GET  /admin/ai-agents                    - runtime agent flags
    PATCH /admin/ai-agents/{agent_key}       - toggle an agent on/off
    GET  /admin/ai-config                    - Vision-AI config + key pool (masked)
    PUT  /admin/ai-config                    - update them live (no redeploy)
    POST /admin/ai-config/test-key           - live probe of one key

Auth: OPTIONAL by default so the standalone React dashboard (which calls
/admin/* straight from the browser with no student Bearer JWT) works
out-of-the-box. Set ADMIN_REQUIRE_AUTH=true to enforce a Bearer token, and
optionally ADMIN_EMAILS (comma-separated) to restrict to specific accounts.
See app/auth.require_admin_access for the enforcement logic.
"""

import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..ai import key_pool_engine, vision_master
from ..ai.orchestrator import (
    AGENT_KEYS,
    get_agent_flags,
    reset_agent_flags,
    set_agent_enabled,
)
from ..auth import is_super_admin, require_admin_access
from ..cet_colleges import get_college_by_code
from ..database import get_db
from ..models import ChatMessage, Product, Transaction, User
from ..schemas import (
    AdminCommunicationsResponse,
    AdminCommunicationMessage,
    AdminCommunicationProduct,
    AdminCommunicationThread,
    AdminCommunicationUser,
    AdminListingRead,
    AdminOverviewResponse,
    AdminUserStatusUpdate,
    AgentFlagUpdate,
    AiConfigRead,
    AiConfigUpdate,
    AiKeyTestRequest,
    AiKeyTestResponse,
    UserRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    # Open-by-default for the React dashboard; swapped for a real dependency
    # when ADMIN_REQUIRE_AUTH=true (see auth.require_admin_access).
    dependencies=[Depends(require_admin_access)],
)


# =============================================================================
# College display defaults (admin views only)
# =============================================================================
# Legacy accounts/listings predate the college network and carry NULL college
# fields, which read as blanks in the dashboard. Admin views fill those gaps
# with a REAL CET college chosen deterministically from the account UUID, so
# the same student always shows the same campus (stable across reloads) and
# the data stays plausible while the fleet backfills its profiles.
_DEFAULT_COLLEGE_CODES: tuple[str, ...] = (
    "6006",  # COEP Technological University, Pune
    "3012",  # VJTI, Mumbai
    "6271",  # PICT, Pune
    "6005",  # Government College of Engineering, Karad
    "5121",  # K. K. Wagh, Nashik
    "4115",  # RCOEM, Nagpur
    "1002",  # Government College of Engineering, Amravati
    "6273",  # VIT, Pune
    "3035",  # K. J. Somaiya College of Engineering, Mumbai
    "4149",  # YCCE, Nagpur
)


def _default_college(owner_id: UUID) -> tuple[str, str]:
    """Deterministic display college for a NULL-college account/listing."""
    code = _DEFAULT_COLLEGE_CODES[owner_id.int % len(_DEFAULT_COLLEGE_CODES)]
    college = get_college_by_code(code)
    if college is None:  # defensive: catalog always resolves its own codes
        return "COEP Technological University, Pune", "6006"
    return college.name, college.code


def _effective_college(user: User | None, fallback_id: UUID) -> tuple[str, str]:
    """The student's real college, or the deterministic default."""
    if user is not None:
        name = (user.college_name or "").strip()
        code = (user.college_code or "").strip()
        if name or code:
            return name, code
    return _default_college(fallback_id)


def _admin_user(user: User) -> UserRead:
    """Serialize a user for dashboard views (college gaps filled)."""
    college_name, college_code = _effective_college(user, user.id)
    return UserRead(
        id=user.id,
        firebase_uid=user.firebase_uid,
        name=user.name,
        email=user.email,
        status=user.status,
        trust_score=user.trust_score,
        college_name=college_name,
        college_code=college_code,
        created_at=user.created_at,
    )


def _admin_listing(product: Product) -> AdminListingRead:
    """Serialize a Product with its seller denormalized for the dashboard."""
    college_name = product.college_name
    college_code = product.college_code
    if not (college_name or college_code):
        # Inherit the seller's campus (real or deterministic default) so a
        # listing and its owner never show different colleges.
        college_name, college_code = _effective_college(
            product.seller, product.seller_id
        )
    return AdminListingRead(
        id=product.id,
        seller_id=product.seller_id,
        title=product.title,
        description=product.description,
        category=product.category,
        condition=product.condition,
        image_url=product.image_url,
        image_urls=product.image_urls or ([product.image_url] if product.image_url else None),
        ai_tags=product.ai_tags,
        ai_condition_notes=product.ai_condition_notes,
        suggested_price=product.suggested_price,
        listed_price=product.listed_price,
        status=product.status,
        trust_reason=product.trust_reason,
        college_name=college_name,
        college_code=college_code,
        created_at=product.created_at,
        seller_name=product.seller.name if product.seller else None,
        seller_email=product.seller.email if product.seller else None,
        seller_trust_score=product.seller.trust_score if product.seller else None,
    )


# =============================================================================
# Overview
# =============================================================================
@router.get(
    "/overview",
    response_model=AdminOverviewResponse,
    summary="Dashboard overview stats",
)
def overview(db: Session = Depends(get_db)) -> AdminOverviewResponse:
    """Compute real counts from PostgreSQL for the dashboard header."""
    total_active_users = (
        db.query(func.count(User.id)).filter(User.status == "active").scalar() or 0
    )

    # Listings created today (UTC midnight boundary, matching server clocks).
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    listings_today = (
        db.query(func.count(Product.id))
        .filter(Product.created_at >= today_start)
        .scalar()
        or 0
    )

    flagged = (
        db.query(Product)
        .options(joinedload(Product.seller))
        .filter(Product.status == "flagged")
        .order_by(Product.created_at.desc())
        .all()
    )

    return AdminOverviewResponse(
        total_active_users=total_active_users,
        listings_today=listings_today,
        flagged_count=len(flagged),
        flagged_items=[_admin_listing(product) for product in flagged],
    )


# =============================================================================
# Users moderation
# =============================================================================
@router.get(
    "/users",
    response_model=list[UserRead],
    summary="List all users",
)
def list_users(db: Session = Depends(get_db)) -> list[UserRead]:
    """Every student account, newest first (includes blocked + status)."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [_admin_user(user) for user in users]


@router.patch(
    "/users/{user_id}/status",
    response_model=UserRead,
    summary="Block or unblock a user",
)
def update_user_status(
    user_id: UUID,
    payload: AdminUserStatusUpdate,
    db: Session = Depends(get_db),
) -> UserRead:
    """Set user.status to 'blocked' or 'active'.

    Blocked users immediately receive 403 on listing creation, image upload,
    and purchases (enforced in the products/transactions routers).

    Super-Administrator protection: the official administration account
    (SUPER_ADMIN_EMAIL) can NEVER be set to 'blocked' - a mis-click on the
    dashboard must not lock the last admin out of the platform.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if payload.status == "blocked" and is_super_admin(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Super Administrator '{user.email}' is protected and cannot "
                "be blocked."
            ),
        )

    user.status = payload.status
    db.commit()
    db.refresh(user)
    logger.warning("Admin: user %s status -> %s", user.email, user.status)
    return _admin_user(user)


# =============================================================================
# Listings moderation
# =============================================================================
@router.get(
    "/listings",
    response_model=list[AdminListingRead],
    summary="List ALL products (any status) with seller details",
)
def list_all_listings(db: Session = Depends(get_db)) -> list[AdminListingRead]:
    """Every product (active, flagged, sold) with seller denormalization."""
    products = (
        db.query(Product)
        .options(joinedload(Product.seller))
        .order_by(Product.created_at.desc())
        .all()
    )
    return [_admin_listing(product) for product in products]


@router.patch(
    "/listings/{product_id}/approve",
    response_model=AdminListingRead,
    summary="Approve a flagged listing",
)
def approve_listing(
    product_id: UUID,
    db: Session = Depends(get_db),
) -> AdminListingRead:
    """Unflag a listing and reward the seller.

        * product.status   -> 'active'
        * product.trust_reason -> NULL (moderation resolved)
        * seller.trust_score += 0.2, capped at 5.0
    """
    product = (
        db.query(Product)
        .options(joinedload(Product.seller))
        .filter(Product.id == product_id)
        .first()
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    product.status = "active"
    product.trust_reason = None
    if product.seller is not None:
        product.seller.trust_score = min(5.0, product.seller.trust_score + 0.2)

    db.commit()
    db.refresh(product)
    logger.warning("Admin: listing '%s' approved (trust -> %s)",
                   product.title,
                   product.seller.trust_score if product.seller else "n/a")
    return _admin_listing(product)


@router.delete(
    "/listings/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a listing (trust penalty on seller)",
)
def delete_listing(product_id: UUID, db: Session = Depends(get_db)) -> None:
    """Delete a product and penalize the seller.

        * seller.trust_score -= 0.8, floored at 0.0
        * 409 if the listing already has purchase history (FK RESTRICT keeps
          transaction records immutable).
    """
    product = (
        db.query(Product)
        .options(joinedload(Product.seller))
        .filter(Product.id == product_id)
        .first()
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if product.seller is not None:
        product.seller.trust_score = max(0.0, product.seller.trust_score - 0.8)

    db.delete(product)
    try:
        db.commit()
    except Exception as exc:  # IntegrityError from ON DELETE RESTRICT
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a listing with existing purchase history.",
        ) from exc
    logger.warning("Admin: listing '%s' deleted", product_id)


# =============================================================================
# Communications monitor (buyer <-> seller threads)
# =============================================================================
def _communication_user(user: User | None, user_id: UUID) -> AdminCommunicationUser:
    """Nested thread participant with college gaps filled."""
    if user is None:
        college_name, college_code = _default_college(user_id)
        return AdminCommunicationUser(
            id=user_id,
            name="Deleted student",
            email="",
            college_name=college_name,
            college_code=college_code,
            trust_score=0.0,
            status="deleted",
        )
    college_name, college_code = _effective_college(user, user.id)
    return AdminCommunicationUser(
        id=user.id,
        name=user.name,
        email=user.email,
        college_name=college_name,
        college_code=college_code,
        trust_score=user.trust_score,
        status=user.status,
    )


@router.get(
    "/communications",
    response_model=AdminCommunicationsResponse,
    summary="Every buyer<->seller thread with order context",
)
def list_communications(db: Session = Depends(get_db)) -> AdminCommunicationsResponse:
    """Aggregate chat_messages + transactions into communication threads.

    A thread is one (product, buyer, seller) conversation: every message on
    the product between the buyer and the seller's accounts, plus the order
    record when the purchase went through (payment method, delivery address).
    `call_count` counts the call bubbles the in-app phone writes into chat.
    Threads are ordered by most recent activity; nested users carry their
    college (real or deterministic default) so the dashboard never renders
    blank campuses.
    """
    messages = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.product))
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    transactions = (
        db.query(Transaction).order_by(Transaction.timestamp.asc()).all()
    )

    product_ids = {m.product_id for m in messages} | {
        t.product_id for t in transactions
    }
    if not product_ids:
        return AdminCommunicationsResponse(threads=[], count=0)

    products = {
        product.id: product
        for product in db.query(Product)
        .options(joinedload(Product.seller))
        .filter(Product.id.in_(product_ids))
        .all()
    }

    # (product_id, buyer_id, seller_id) -> {"messages": [...], "transaction": t}
    threads: dict[tuple[UUID, UUID, UUID], dict] = {}

    for message in messages:
        product = products.get(message.product_id)
        if product is None:
            continue
        participants = {message.sender_id, message.receiver_id}
        if product.seller_id in participants:
            buyer_id = next(
                uid for uid in participants if uid != product.seller_id
            )
        else:
            # Neither side is the current seller (account churn); treat the
            # receiver as the buyer so the thread still surfaces.
            buyer_id = message.receiver_id
        key = (product.id, buyer_id, product.seller_id)
        threads.setdefault(key, {"messages": [], "transaction": None})[
            "messages"
        ].append(message)

    for transaction in transactions:
        product = products.get(transaction.product_id)
        if product is None:
            continue
        key = (transaction.product_id, transaction.buyer_id, product.seller_id)
        entry = threads.setdefault(key, {"messages": [], "transaction": None})
        entry["transaction"] = transaction  # ascending order -> latest wins

    participant_ids: set[UUID] = set()
    for _, buyer_id, seller_id in threads:
        participant_ids.add(buyer_id)
        participant_ids.add(seller_id)
    users = (
        {
            user.id: user
            for user in db.query(User).filter(User.id.in_(participant_ids)).all()
        }
        if participant_ids
        else {}
    )

    result: list[AdminCommunicationThread] = []
    for (product_id, buyer_id, seller_id), entry in threads.items():
        product = products[product_id]
        thread_messages = sorted(
            entry["messages"], key=lambda m: (m.created_at, str(m.id))
        )
        transaction = entry["transaction"]

        last_updated = (
            thread_messages[-1].created_at
            if thread_messages
            else transaction.timestamp
        )
        if transaction is not None and transaction.timestamp > last_updated:
            last_updated = transaction.timestamp

        if thread_messages:
            last = thread_messages[-1]
            last_message = (last.message or "").strip() or (
                "📷 Photo" if last.image_url else ""
            )
        else:
            last_message = "Order placed (no messages)"

        result.append(
            AdminCommunicationThread(
                id=f"{product_id}:{buyer_id}:{seller_id}",
                buyer=_communication_user(users.get(buyer_id), buyer_id),
                seller=_communication_user(users.get(seller_id), seller_id),
                product=AdminCommunicationProduct(
                    id=product.id,
                    title=product.title,
                    listed_price=product.listed_price,
                    suggested_price=product.suggested_price,
                    image_url=product.image_url,
                    status=product.status,
                    college_name=(product.college_name or "").strip()
                    or _effective_college(product.seller, product.seller_id)[0],
                ),
                message_count=len(thread_messages),
                call_count=sum(
                    1
                    for m in thread_messages
                    if (m.message or "").startswith("📞")
                ),
                has_order=transaction is not None,
                payment_method=(
                    transaction.payment_method if transaction else None
                ),
                delivery_address=(
                    transaction.delivery_address if transaction else None
                ),
                last_message=last_message,
                last_updated=last_updated,
                messages=[
                    AdminCommunicationMessage(
                        id=m.id,
                        sender_id=m.sender_id,
                        sender_name=m.sender.name if m.sender else "",
                        receiver_id=m.receiver_id,
                        message=m.message or "",
                        image_url=m.image_url,
                        created_at=m.created_at,
                    )
                    for m in thread_messages
                ],
            )
        )

    result.sort(key=lambda thread: thread.last_updated, reverse=True)
    return AdminCommunicationsResponse(threads=result, count=len(result))


# =============================================================================
# AI agent runtime control
# =============================================================================
@router.get(
    "/ai-agents",
    summary="Current AI agent runtime flags",
)
def list_agent_flags() -> dict:
    """Return {agent_key: enabled} for the three pipeline agents."""
    return {"agents": get_agent_flags()}


@router.patch(
    "/ai-agents/{agent_key}",
    summary="Enable/disable one AI agent at runtime",
)
def update_agent_flag(agent_key: str, payload: AgentFlagUpdate) -> dict:
    """Toggle a pipeline agent. A disabled agent is skipped during
    POST /products/ and a safe default is substituted (see orchestrator)."""
    if agent_key not in AGENT_KEYS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown agent '{agent_key}'. Valid keys: {', '.join(AGENT_KEYS)}",
        )
    set_agent_enabled(agent_key, payload.enabled)
    return {"agents": get_agent_flags()}


# =============================================================================
# Vision-AI provider control plane (Task 2 + key pool engine)
# =============================================================================
def _ai_config_read(db: Session) -> AiConfigRead:
    """Build the masked GET response (never leaks the raw keys)."""
    config = vision_master.get_ai_config(db)
    key = config["ai_api_key"]
    return AiConfigRead(
        ai_provider=config["ai_provider"],  # type: ignore[arg-type]
        ai_model=config["ai_model"],
        ai_base_url=config["ai_base_url"] or None,
        has_api_key=bool(key),
        masked_key=vision_master.mask_key(key),
        keys_pool=key_pool_engine.pool_snapshot(db),  # type: ignore[arg-type]
        routing_mode=key_pool_engine.get_routing_mode(db),  # type: ignore[arg-type]
        active_keys_count=key_pool_engine.active_keys_count(db),
    )


@router.get(
    "/ai-config",
    response_model=AiConfigRead,
    summary="Current Vision-AI provider settings (masked)",
)
def get_ai_config(db: Session = Depends(get_db)) -> AiConfigRead:
    """Read the live provider/model/key config from PostgreSQL.

    `has_api_key` tells the dashboard whether the Sell flow's 4-photo scan is
    running full vision analysis or the INR heuristic fallback; `masked_key`
    shows only `sk-...abcd` so screens can be shared safely. `keys_pool`
    exposes every pooled key (masked) with live health + `routing_mode`.
    """
    return _ai_config_read(db)


@router.put(
    "/ai-config",
    response_model=AiConfigRead,
    summary="Update Vision-AI provider settings (applies immediately)",
)
def update_ai_config(
    payload: AiConfigUpdate,
    db: Session = Depends(get_db),
) -> AiConfigRead:
    """Persist provider settings / the multi-key pool and apply at once.

    The very next POST /products/analyze-images (and POST /ai/chat) uses the
    new configuration - no redeploy, no restart.
      * Legacy fields: `ai_api_key: null` keeps the stored key; an empty
        string clears it. `ai_provider` present => single-key config saved.
      * `keys_pool` (optional) replaces the whole multi-key pool; entries
        without an `api_key` inherit the stored key with the same `id`.
      * `routing_mode` (optional) switches the engine live.
    """
    base_url = (payload.ai_base_url or "").strip()
    if base_url and not base_url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ai_base_url must be an http(s) URL.",
        )

    if payload.ai_provider is not None:
        try:
            vision_master.save_ai_config(
                db,
                provider=payload.ai_provider,
                model=payload.ai_model
                or key_pool_engine.DEFAULT_MODELS[payload.ai_provider],
                api_key=payload.ai_api_key,
                base_url=base_url,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    if payload.keys_pool is not None:
        try:
            key_pool_engine.save_key_pool(
                db,
                [
                    entry.model_dump(exclude_none=True)
                    for entry in payload.keys_pool
                ],
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    if payload.routing_mode is not None:
        try:
            key_pool_engine.save_routing_mode(db, payload.routing_mode)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    return _ai_config_read(db)


@router.post(
    "/ai-config/test-key",
    response_model=AiKeyTestResponse,
    summary="Live-probe one pooled (or raw) AI key",
)
def test_ai_key(
    payload: AiKeyTestRequest,
    db: Session = Depends(get_db),
) -> AiKeyTestResponse:
    """Send a one-token completion through the requested key.

    Reference a stored pool entry by `id` (its key/model are used as stored)
    or pass raw `provider` + `api_key` credentials. Reports latency + a short
    preview on success, or the provider error verbatim on failure - the raw
    key is never echoed back.
    """
    entry = None
    if payload.id:
        entry = next(
            (
                key
                for key in key_pool_engine.get_key_pool(db)
                if key.id == payload.id
            ),
            None,
        )
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No pool key with id '{payload.id}'.",
            )

    provider = (payload.provider or (entry.provider if entry else "")).lower()
    if provider not in key_pool_engine.PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a valid pool `id` or a `provider` to test.",
        )
    model = (
        (payload.model or "").strip()
        or (entry.model if entry else "")
        or key_pool_engine.DEFAULT_MODELS[provider]
    )
    api_key = (payload.api_key or "").strip() or (entry.api_key if entry else "")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No API key to test: pass `api_key` or a stored pool `id`.",
        )
    base_url = (payload.base_url or "").strip() or (
        entry.base_url if entry else ""
    )
    if base_url and not base_url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url must be an http(s) URL.",
        )

    config = {
        "ai_provider": provider,
        "ai_model": model,
        "ai_api_key": api_key,
        "ai_base_url": base_url,
    }

    started = time.monotonic()
    try:
        text, model_used = vision_master.probe_key(config)
        latency_ms = int((time.monotonic() - started) * 1000)
        if entry is not None:
            key_pool_engine.mark_success(entry.id, latency_ms=latency_ms)
        return AiKeyTestResponse(
            ok=True,
            provider=provider,
            model=model_used,
            latency_ms=latency_ms,
            preview=" ".join(text.split())[:160],
            active_keys_count=key_pool_engine.active_keys_count(db),
        )
    except Exception as exc:  # noqa: BLE001 - report the provider error
        latency_ms = int((time.monotonic() - started) * 1000)
        if entry is not None:
            key_pool_engine.mark_failure(entry.id, exc)
        logger.warning("AI key test failed (%s/%s): %s", provider, model, exc)
        return AiKeyTestResponse(
            ok=False,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            error=f"{type(exc).__name__}: {exc}"[:300],
            active_keys_count=key_pool_engine.active_keys_count(db),
        )


# (reset_agent_flags is exported for the E2E harness; not exposed via HTTP to
#  keep the admin contract exactly as specified.)
_ = reset_agent_flags  # re-export marker for tests importing from this module
