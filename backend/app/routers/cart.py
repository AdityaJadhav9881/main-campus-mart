"""
routers/cart.py
===============
Shopping cart for the marketplace (Amazon-style cart tab).

    GET    /cart/                 - my cart with full product cards + total
    POST   /cart/{product_id}     - park a listing in the cart (idempotent)
    DELETE /cart/{product_id}     - remove a listing from the cart
    DELETE /cart/                 - empty the whole cart

The cart is a pre-checkout staging area: buying through
POST /products/{id}/purchase clears the item automatically.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..auth import get_or_create_current_user, verify_firebase_token
from ..database import get_db
from ..models import CartItem, Product
from ..schemas import CartItemRead, CartResponse, ProductRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cart", tags=["cart"])


def _cart_response(db: Session, user_id: UUID) -> CartResponse:
    """Build the cart payload with full product cards for the UI."""
    rows = (
        db.query(CartItem)
        .options(joinedload(CartItem.product).joinedload(Product.seller))
        .filter(CartItem.user_id == user_id)
        .order_by(CartItem.created_at.desc())
        .all()
    )
    items = [
        CartItemRead(
            id=row.id,
            added_at=row.created_at,
            product=ProductRead.model_validate(row.product),
        )
        for row in rows
        if row.product is not None
    ]
    total = sum(item.product.listed_price for item in items)
    return CartResponse(items=items, count=len(items), total_price=round(total, 2))


@router.get(
    "",
    response_model=CartResponse,
    summary="My cart (products + total)",
)
@router.get(
    "/",
    response_model=CartResponse,
    include_in_schema=False,
)
def get_cart(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> CartResponse:
    """Cart contents with ₹ total for the cart screen."""
    me = get_or_create_current_user(db, token)
    return _cart_response(db, me.id)


@router.post(
    "/{product_id}",
    response_model=CartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a listing to my cart",
)
def add_to_cart(
    product_id: UUID,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> CartResponse:
    """Idempotent add: re-adding the same listing returns the cart unchanged."""
    me = get_or_create_current_user(db, token)

    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found (it may have been removed).",
        )
    if product.seller_id == me.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot add your own listing to the cart.",
        )
    if product.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This listing is no longer available (status: {product.status}).",
        )

    existing = (
        db.query(CartItem)
        .filter(CartItem.user_id == me.id, CartItem.product_id == product.id)
        .first()
    )
    if existing is None:
        db.add(CartItem(user_id=me.id, product_id=product.id))
        try:
            db.commit()
        except IntegrityError:
            # Concurrent double-tap on "Add to Cart" - already added, fine.
            db.rollback()
        else:
            logger.info("Cart: %s added '%s'", me.email, product.title)

    return _cart_response(db, me.id)


@router.delete(
    "/{product_id}",
    response_model=CartResponse,
    summary="Remove one listing from my cart",
)
def remove_from_cart(
    product_id: UUID,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> CartResponse:
    """Idempotent remove (deleting a non-present item is a no-op)."""
    me = get_or_create_current_user(db, token)
    db.query(CartItem).filter(
        CartItem.user_id == me.id,
        CartItem.product_id == product_id,
    ).delete(synchronize_session=False)
    db.commit()
    return _cart_response(db, me.id)


@router.delete(
    "",
    response_model=CartResponse,
    summary="Empty my cart",
)
@router.delete(
    "/",
    response_model=CartResponse,
    include_in_schema=False,
)
def clear_cart(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> CartResponse:
    """Remove every item (used after checkout or by a "Clear cart" action)."""
    me = get_or_create_current_user(db, token)
    db.query(CartItem).filter(CartItem.user_id == me.id).delete(
        synchronize_session=False
    )
    db.commit()
    return _cart_response(db, me.id)
