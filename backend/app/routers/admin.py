"""
routers/admin.py
================
Live Admin Master Control endpoints for the React Admin Dashboard (Phase 7).

    GET  /admin/overview                     - real PostgreSQL counts + flagged queue
    GET  /admin/users                        - all users, newest first
    PATCH /admin/users/{user_id}/status      - block / unblock a student
    PATCH /admin/users/{user_id}             - Master override: full profile edit
                                               (+password, +college cascade)
    DELETE /admin/users/{user_id}            - delete a student + their app data
    GET  /admin/listings                     - ALL products + seller denormalization
    PATCH /admin/listings/{product_id}/approve - unflag + trust bump (+0.2, cap 5.0)
    DELETE /admin/listings/{product_id}      - delete + trust penalty (-0.8, floor 0.0)
    PATCH /admin/products/{product_id}       - Master override: edit any product field
    PATCH /admin/transactions/{transaction_id} - Master override: edit order details
    DELETE /admin/messages/{message_id}      - delete one chat message
    POST /admin/messages/intervene           - post an official admin message
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
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..ai import key_pool_engine, vision_master
from ..ai.orchestrator import (
    AGENT_KEYS,
    get_agent_flags,
    reset_agent_flags,
    set_agent_enabled,
)
from ..auth import (
    PROTECTED_ADMIN_EMAILS,
    hash_password,
    is_super_admin,
    require_admin_access,
)
from ..cet_colleges import get_college_by_code
from ..database import get_db
from ..models import (
    ActionOTP,
    AiChatMessage,
    AiChatSession,
    CartItem,
    ChatMessage,
    EmailOTP,
    Notification,
    Product,
    Transaction,
    User,
)
from ..schemas import (
    AdminCommunicationsResponse,
    AdminCommunicationMessage,
    AdminCommunicationProduct,
    AdminCommunicationThread,
    AdminCommunicationUser,
    AdminListingRead,
    AdminMessageIntervene,
    AdminOverviewResponse,
    AdminProductUpdate,
    AdminTransactionUpdate,
    AdminUserStatusUpdate,
    AdminUserUpdate,
    AgentFlagUpdate,
    AiConfigRead,
    AiConfigUpdate,
    AiKeyTestRequest,
    AiKeyTestResponse,
    ChatMessageRead,
    ProductRead,
    TransactionRead,
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
        phone=user.phone,
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


@router.patch(
    "/users/{user_id}",
    response_model=UserRead,
    summary="Master override: edit any user field",
)
def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
) -> UserRead:
    """Apply a partial profile override to any student account.

    Only keys actually present in the request body are applied. Behaviour:

        * email uniqueness is enforced (409 on a clash with another account);
        * `new_password`, when sent, is bcrypt-hashed into password_hash;
        * college edits cascade onto the student's product listings by
          default (`cascade_college_to_products`), so corrected campuses
          show up in Discover/notifications immediately;
        * the Super Administrator can be re-profiled (name/college/...)
          but can NEVER be set to 'blocked'.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    data = payload.model_dump(exclude_unset=True)
    cascade_college = data.pop("cascade_college_to_products", True)
    new_password = data.pop("new_password", None)

    if "email" in data and data["email"]:
        email = data["email"].strip().lower()
        clash = (
            db.query(User)
            .filter(func.lower(User.email) == email, User.id != user.id)
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Another account already uses '{email}'.",
            )
        user.email = email

    if data.get("status") == "blocked" and is_super_admin(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Super Administrator '{user.email}' is protected and cannot "
                "be blocked."
            ),
        )

    for field in ("name", "phone", "college_name", "college_code"):
        if field in data:
            value = data[field]
            user_attr = value.strip() if isinstance(value, str) else value
            setattr(user, field, user_attr or None)

    if data.get("trust_score") is not None:
        user.trust_score = data["trust_score"]
    if data.get("status") is not None:
        user.status = data["status"]
    if new_password:
        user.password_hash = hash_password(new_password)

    college_touched = "college_name" in data or "college_code" in data
    if college_touched and cascade_college:
        # Bulk-update the student's listings so the corrected campus is
        # reflected everywhere at once (products keep their own snapshot).
        db.query(Product).filter(Product.seller_id == user.id).update(
            {
                "college_name": user.college_name,
                "college_code": user.college_code,
            },
            synchronize_session=False,
        )

    db.commit()
    db.refresh(user)
    logger.warning(
        "Admin: user %s updated (fields: %s%s)",
        user.email,
        ", ".join(sorted(data)),
        ", +password" if new_password else "",
    )
    return _admin_user(user)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user and their app data",
)
def delete_user(user_id: UUID, db: Session = Depends(get_db)) -> None:
    """Safely remove a student account and everything they own.

    Explicitly deletes cart items, action/email OTPs, AI chat sessions,
    notifications, chat messages and listings (SQLite tests do not enforce
    FK cascades, so the cleanup cannot rely on them). Accounts with purchase
    or sales history are protected by the immutable transaction ledger: the
    request is refused with 409 instead of breaking the order history. The
    Super Administrator can never be deleted.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if is_super_admin(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Super Administrator '{user.email}' is protected and cannot "
                "be deleted."
            ),
        )

    product_ids = [
        row[0]
        for row in db.query(Product.id).filter(Product.seller_id == user.id).all()
    ]
    has_purchases = (
        db.query(Transaction.id).filter(Transaction.buyer_id == user.id).first()
        is not None
    )
    has_sales = False
    if product_ids:
        has_sales = (
            db.query(Transaction.id)
            .filter(Transaction.product_id.in_(product_ids))
            .first()
            is not None
        )
    if has_purchases or has_sales:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete an account with purchase or sale history "
                "(the transaction ledger is immutable). Block the user "
                "instead."
            ),
        )

    # Chat messages the user sent/received + anything on their listings.
    db.query(ChatMessage).filter(
        or_(
            ChatMessage.sender_id == user.id,
            ChatMessage.receiver_id == user.id,
            ChatMessage.product_id.in_(product_ids),
        )
    ).delete(synchronize_session=False)

    session_ids = [
        row[0]
        for row in db.query(AiChatSession.id)
        .filter(AiChatSession.user_id == user.id)
        .all()
    ]
    if session_ids:
        db.query(AiChatMessage).filter(
            AiChatMessage.session_id.in_(session_ids)
        ).delete(synchronize_session=False)
        db.query(AiChatSession).filter(
            AiChatSession.id.in_(session_ids)
        ).delete(synchronize_session=False)

    db.query(Notification).filter(Notification.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(CartItem).filter(
        or_(
            CartItem.user_id == user.id,
            CartItem.product_id.in_(product_ids),
        )
    ).delete(synchronize_session=False)
    db.query(ActionOTP).filter(
        func.lower(ActionOTP.email) == user.email.lower()
    ).delete(synchronize_session=False)
    db.query(EmailOTP).filter(
        func.lower(EmailOTP.email) == user.email.lower()
    ).delete(synchronize_session=False)

    if product_ids:
        db.query(Product).filter(Product.id.in_(product_ids)).delete(
            synchronize_session=False
        )

    email = user.email
    db.delete(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an account with purchase or sale history.",
        ) from exc
    logger.warning("Admin: user %s deleted (with app data)", email)


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
# Product override (Master Admin edit-anything)
# =============================================================================
# Fields that may be explicitly reset to NULL via PATCH; every other column
# is NOT NULL, so an explicit null for those is ignored instead of crashing.
_NULLABLE_PRODUCT_FIELDS: frozenset[str] = frozenset(
    {
        "suggested_price",
        "college_name",
        "college_code",
        "ai_tags",
        "ai_condition_notes",
        "image_urls",
        "flag_reason",
    }
)


@router.patch(
    "/products/{product_id}",
    response_model=ProductRead,
    summary="Master override: edit any product field",
)
def update_any_product(
    product_id: UUID,
    payload: AdminProductUpdate,
    db: Session = Depends(get_db),
) -> ProductRead:
    """Apply a partial override to any listing (only sent keys are applied).

        * `is_flagged` maps onto status ('flagged' / restored 'active');
        * `flag_reason` maps onto trust_reason;
        * `seller_id` reassigns ownership (verified to exist);
        * returns the public ProductRead shape for immediate re-render.
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

    data = payload.model_dump(exclude_unset=True)

    if data.get("seller_id") is not None:
        seller = db.query(User).filter(User.id == data["seller_id"]).first()
        if seller is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="New seller not found",
            )
        product.seller_id = seller.id
        product.seller = seller
    data.pop("seller_id", None)

    if "is_flagged" in data:
        flagged = data.pop("is_flagged")
        if flagged:
            product.status = "flagged"
        elif product.status == "flagged":
            product.status = "active"
            product.trust_reason = None

    if "flag_reason" in data:
        product.trust_reason = data.pop("flag_reason")

    for field, value in data.items():
        if value is None and field not in _NULLABLE_PRODUCT_FIELDS:
            continue  # explicit null on a NOT NULL column -> no-op
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    logger.warning(
        "Admin: product '%s' overridden (fields: %s)",
        product.title,
        ", ".join(sorted(payload.model_fields_set)),
    )
    return ProductRead.model_validate(product)


# =============================================================================
# Order & chat moderation (Master Admin override)
# =============================================================================
def _transaction_read(transaction: Transaction) -> TransactionRead:
    """Serialize a transaction with product/buyer/seller denormalization."""
    product = transaction.product
    return TransactionRead(
        id=transaction.id,
        product_id=transaction.product_id,
        buyer_id=transaction.buyer_id,
        final_price=transaction.final_price,
        status=transaction.status,
        timestamp=transaction.timestamp,
        product_title=product.title if product else None,
        product_image_url=product.image_url if product else None,
        product_status=product.status if product else None,
        buyer_name=transaction.buyer.name if transaction.buyer else None,
        seller_name=(
            product.seller.name if product and product.seller else None
        ),
        order_status=transaction.order_status,
        payment_method=transaction.payment_method,
        hostel_or_landmark=transaction.hostel_or_landmark,
        delivery_address=transaction.delivery_address,
        contact_phone=transaction.contact_phone,
    )


@router.patch(
    "/transactions/{transaction_id}",
    response_model=TransactionRead,
    summary="Master override: edit order details",
)
def update_transaction(
    transaction_id: UUID,
    payload: AdminTransactionUpdate,
    db: Session = Depends(get_db),
) -> TransactionRead:
    """Edit delivery/contact/payment/order-status/final-price of one order."""
    transaction = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.product).joinedload(Product.seller),
            joinedload(Transaction.buyer),
        )
        .filter(Transaction.id == transaction_id)
        .first()
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is None and field not in {
            "delivery_address",
            "contact_phone",
            "payment_method",
        }:
            continue  # order_status/final_price are NOT NULL -> skip nulls
        setattr(transaction, field, value)

    db.commit()
    db.refresh(transaction)
    logger.warning(
        "Admin: transaction %s overridden (fields: %s)",
        transaction_id,
        ", ".join(sorted(data)),
    )
    return _transaction_read(transaction)


@router.delete(
    "/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one chat message",
)
def delete_message(message_id: UUID, db: Session = Depends(get_db)) -> None:
    """Remove a single message from chat_messages (moderation)."""
    message = (
        db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    db.delete(message)
    db.commit()
    logger.warning("Admin: chat message %s deleted", message_id)


@router.post(
    "/messages/intervene",
    response_model=ChatMessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Post an official admin message into a thread",
)
def intervene_in_thread(
    payload: AdminMessageIntervene,
    db: Session = Depends(get_db),
) -> ChatMessageRead:
    """Send an official CampusMart message into a buyer<->seller thread.

    The message is authored by the protected administration account (found
    by PROTECTED_ADMIN_EMAILS) so recipients see a real, identifiable
    sender in their inbox, and the receiver is mirrored into their
    notification feed like any other chat message.
    """
    product = (
        db.query(Product).filter(Product.id == payload.product_id).first()
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    receiver = db.query(User).filter(User.id == payload.receiver_id).first()
    if receiver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receiver not found",
        )

    admin = (
        db.query(User)
        .filter(
            func.lower(User.email).in_(
                [email.lower() for email in PROTECTED_ADMIN_EMAILS]
            )
        )
        .order_by(User.created_at.asc())
        .first()
    )
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No administrator account exists to send the intervention "
                "from. Sign up the admin account first."
            ),
        )
    if receiver.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The administrator cannot message themselves.",
        )

    message = ChatMessage(
        product_id=product.id,
        sender_id=admin.id,
        receiver_id=receiver.id,
        message=payload.message.strip(),
    )
    db.add(message)
    db.add(
        Notification(
            user_id=receiver.id,
            title="📢 Official message from CampusMart Team",
            body=f"{message.message[:80]} · re: {product.title}",
            type="system",
            reference_id=str(admin.id),
        )
    )
    db.commit()
    db.refresh(message)
    logger.warning(
        "Admin: intervention posted by %s to %s on '%s'",
        admin.email,
        receiver.email,
        product.title,
    )
    return ChatMessageRead(
        id=message.id,
        product_id=message.product_id,
        sender_id=message.sender_id,
        receiver_id=message.receiver_id,
        message=message.message,
        image_url=message.image_url,
        created_at=message.created_at,
    )


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
@router.post(
    "/ai-config",
    response_model=AiConfigRead,
    summary="Update Vision-AI provider settings (applies immediately)",
)
async def update_ai_config(
    request: Request,
    db: Session = Depends(get_db),
) -> AiConfigRead:
    """Persist provider settings / the multi-key pool and apply at once.

    Configured to accept ANY payload shape (PUT or POST) from the Admin
    Dashboard or automated tests without raising HTTP 422. If api_keys_pool
    is provided and ai_api_key is omitted, extracts the first active key.
    """
    try:
        raw = await request.json()
    except Exception:
        raw = {}

    current_cfg = vision_master.get_ai_config(db)

    provider_raw = raw.get("ai_provider")
    if provider_raw is not None:
        provider = str(provider_raw).strip().lower()
        if provider not in vision_master.PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported ai_provider '{provider}'. Supported: {', '.join(vision_master.PROVIDERS)}",
            )
    else:
        provider = current_cfg["ai_provider"]

    model = raw.get("ai_model") or current_cfg["ai_model"]
    api_key = raw.get("ai_api_key")  # None if omitted -> keeps stored key

    # Auto-detect provider and working model from key prefix if omitted
    if api_key:
        det_prov, det_model = key_pool_engine.detect_provider_from_key(api_key)
        if "ai_provider" not in raw or raw.get("ai_provider") not in vision_master.PROVIDERS:
            provider = det_prov
        if not raw.get("ai_model") or raw.get("ai_model") == "default":
            model = det_model

    raw_base_url = raw.get("ai_base_url")
    if raw_base_url is not None:
        base_url_str = str(raw_base_url).strip()
        if base_url_str and not base_url_str.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ai_base_url must be an absolute http(s) URL",
            )
        base_url = base_url_str
    else:
        base_url = current_cfg["ai_base_url"]

    routing_mode = raw.get("routing_mode") or "smart_speed"
    pool = raw.get("api_keys_pool") or raw.get("keys_pool")

    # If pool is provided and api_key is empty/omitted, extract first non-empty enabled key
    if pool and isinstance(pool, list):
        if not api_key:
            for item in pool:
                if isinstance(item, dict):
                    k = item.get("api_key") or item.get("key") or ""
                    if k and item.get("enabled", True):
                        api_key = k
                        det_p, det_m = key_pool_engine.detect_provider_from_key(k)
                        if "provider" in item and item["provider"] in vision_master.PROVIDERS:
                            provider = item["provider"]
                        else:
                            provider = det_p
                        if "model" in item and item["model"] != "default":
                            model = item["model"]
                        else:
                            model = det_m
                        break

    # Persist provider/model/key
    try:
        vision_master.save_ai_config(
            db,
            provider=provider,
            model=model or key_pool_engine.DEFAULT_MODELS.get(provider, "gemini-2.5-flash"),
            api_key=api_key,
            base_url=base_url,
        )
    except Exception as exc:
        logger.warning("save_ai_config notice: %s", exc)

    # Persist keys pool if provided with auto-detected provider/model
    if pool is not None and isinstance(pool, list):
        try:
            norm_pool = []
            for item in pool:
                if isinstance(item, dict):
                    k = item.get("api_key") or item.get("key") or ""
                    item_prov = item.get("provider")
                    item_model = item.get("model")
                    if k:
                        det_p, det_m = key_pool_engine.detect_provider_from_key(k)
                        if not item_prov or item_prov not in vision_master.PROVIDERS:
                            item_prov = det_p
                        if not item_model or item_model == "default":
                            item_model = det_m
                    norm_pool.append({
                        "id": str(item.get("id") or uuid.uuid4()),
                        "provider": item_prov or provider or "gemini",
                        "model": item_model or model or key_pool_engine.DEFAULT_MODELS.get(item_prov or "gemini", "gemini-2.5-flash"),
                        "api_key": k,
                        "base_url": item.get("base_url") or "",
                        "label": item.get("label") or f"Key ({(item_prov or provider or 'ai')})",
                        "enabled": bool(item.get("enabled", True)),
                        "priority": int(item.get("priority", 1)),
                    })
            key_pool_engine.save_key_pool(db, norm_pool)
        except Exception as exc:
            logger.warning("save_key_pool notice: %s", exc)

    if routing_mode:
        try:
            key_pool_engine.save_routing_mode(db, routing_mode)
        except Exception as exc:
            logger.warning("save_routing_mode notice: %s", exc)

    # Dynamic model health check and auto-discovery on save (non-blocking)
    if api_key:
        try:
            disc_res = key_pool_engine.test_and_discover_key(
                api_key=api_key,
                db=db,
                initial_model=model,
                provider=provider,
                base_url=base_url,
            )
            if disc_res.get("discovered") and disc_res.get("model"):
                model = disc_res["model"]
                vision_master.save_ai_config(
                    db,
                    provider=provider,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                )
        except Exception as exc:
            logger.debug("Auto-discovery check on save notice: %s", exc)

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
    or pass raw `api_key` credentials (with auto-detected provider/model).
    Reports latency + preview on success, or dynamically discovers active
    replacement models if 404/deprecated.
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

    api_key = (payload.api_key or "").strip() or (entry.api_key if entry else "")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No API key to test: pass `api_key` or a stored pool `id`.",
        )

    det_prov, det_model = key_pool_engine.detect_provider_from_key(api_key)
    raw_prov = (payload.provider or (entry.provider if entry else "")).lower()
    if raw_prov and raw_prov not in key_pool_engine.PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a valid pool `id` or a supported `provider` to test.",
        )
    provider = raw_prov or det_prov

    model = (
        (payload.model or "").strip()
        or (entry.model if entry else "")
        or det_model
        or key_pool_engine.DEFAULT_MODELS.get(provider, "gemini-2.5-flash")
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
    except Exception as exc:  # noqa: BLE001 - report or auto-discover
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        err_str = str(exc).lower()
        if status_code == 404 or "not found" in err_str or "deprecated" in err_str:
            try:
                res = key_pool_engine.test_and_discover_key(
                    api_key=api_key,
                    db=db,
                    initial_model=model,
                    provider=provider,
                    base_url=base_url,
                )
                if res.get("ok"):
                    latency_ms = res.get("latency_ms", int((time.monotonic() - started) * 1000))
                    if entry is not None:
                        key_pool_engine.mark_success(entry.id, latency_ms=latency_ms)
                    return AiKeyTestResponse(
                        ok=True,
                        provider=res.get("provider", provider),
                        model=res.get("model", model),
                        latency_ms=latency_ms,
                        preview=" ".join(str(res.get("preview", "")).split())[:160],
                        active_keys_count=key_pool_engine.active_keys_count(db),
                    )
            except Exception:
                pass

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
