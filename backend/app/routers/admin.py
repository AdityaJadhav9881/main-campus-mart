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
    GET  /admin/ai-agents                    - runtime agent flags
    PATCH /admin/ai-agents/{agent_key}       - toggle an agent on/off

Auth: OPTIONAL by default so the standalone React dashboard (which calls
/admin/* straight from the browser with no student Bearer JWT) works
out-of-the-box. Set ADMIN_REQUIRE_AUTH=true to enforce a Bearer token, and
optionally ADMIN_EMAILS (comma-separated) to restrict to specific accounts.
See app/auth.require_admin_access for the enforcement logic.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..ai.orchestrator import (
    AGENT_KEYS,
    get_agent_flags,
    reset_agent_flags,
    set_agent_enabled,
)
from ..auth import require_admin_access
from ..database import get_db
from ..models import Product, User
from ..schemas import (
    AdminListingRead,
    AdminOverviewResponse,
    AdminUserStatusUpdate,
    AgentFlagUpdate,
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


def _admin_listing(product: Product) -> AdminListingRead:
    """Serialize a Product with its seller denormalized for the dashboard."""
    return AdminListingRead(
        id=product.id,
        seller_id=product.seller_id,
        title=product.title,
        description=product.description,
        category=product.category,
        condition=product.condition,
        image_url=product.image_url,
        suggested_price=product.suggested_price,
        listed_price=product.listed_price,
        status=product.status,
        trust_reason=product.trust_reason,
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
def list_users(db: Session = Depends(get_db)) -> list[User]:
    """Every student account, newest first (includes blocked + status)."""
    return db.query(User).order_by(User.created_at.desc()).all()


@router.patch(
    "/users/{user_id}/status",
    response_model=UserRead,
    summary="Block or unblock a user",
)
def update_user_status(
    user_id: UUID,
    payload: AdminUserStatusUpdate,
    db: Session = Depends(get_db),
) -> User:
    """Set user.status to 'blocked' or 'active'.

    Blocked users immediately receive 403 on listing creation, image upload,
    and purchases (enforced in the products/transactions routers).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.status = payload.status
    db.commit()
    db.refresh(user)
    logger.warning("Admin: user %s status -> %s", user.email, user.status)
    return user


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


# (reset_agent_flags is exported for the E2E harness; not exposed via HTTP to
#  keep the admin contract exactly as specified.)
_ = reset_agent_flags  # re-export marker for tests importing from this module
