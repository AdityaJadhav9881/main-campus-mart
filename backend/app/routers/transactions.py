"""
routers/transactions.py
=======================
Purchase flow + student purchase history (Phase 7).

    POST /products/{product_id}/purchase  (protected) - buy/reserve an active
        listing: creates a Transaction row, marks the product 'sold', and
        increments the seller's trust score (+0.1, capped at 5.0).
    GET  /transactions/my                 (protected) - the logged-in
        student's bought and sold history with product + counterparty detail.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..auth import (
    account_terminated,
    extract_uid,
    get_or_create_current_user,
    verify_firebase_token,
)
from ..database import get_db
from ..email_service import send_product_sold_emails
from ..models import Product, Transaction, User
from ..schemas import MyTransactionsResponse, PurchaseResponse, TransactionRead

logger = logging.getLogger(__name__)

# NOTE: no router prefix — paths are declared in full so the purchase route
# nests under /products/ (contract) while history lives under /transactions/.
router = APIRouter(tags=["transactions"])

# Seller trust-score reward for a completed sale (capped at 5.0).
SELL_TRUST_BONUS = 0.1


def _load_user(db: Session, token: dict) -> User:
    return get_or_create_current_user(db, token)


@router.post(
    "/products/{product_id}/purchase",
    response_model=PurchaseResponse,
    summary="Purchase an active listing",
)
def purchase_product(
    product_id: UUID,
    background: BackgroundTasks,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> PurchaseResponse:
    """Buy/reserve one active listing.

    Flow (single transaction so the sold-claim and trust update are atomic):
        1. 404 if the product does not exist.
        2. 403 if the buyer's account is blocked.
        3. 400 if the listing is not 'active' (already sold/flagged) or if the
           buyer is the seller (cannot buy your own item).
        4. Insert a completed Transaction at the listed price.
        5. product.status = 'sold'; seller.trust_score += 0.1 (cap 5.0).
        6. Queue BOTH Brevo sale emails (seller "Sold!" + buyer "Order
           Confirmed") as a background task - non-blocking by design.
    """
    buyer = _load_user(db, token)

    if buyer.status == "blocked":
        raise account_terminated()

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

    if product.seller_id == buyer.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot purchase your own listing.",
        )

    if product.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This listing is no longer available (status: {product.status}).",
        )

    transaction = Transaction(
        buyer_id=buyer.id,
        product_id=product.id,
        final_price=product.listed_price,
        status="completed",
    )
    product.status = "sold"
    if product.seller is not None:
        product.seller.trust_score = min(5.0, product.seller.trust_score + SELL_TRUST_BONUS)

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    # Detach-safe: the sale emails run as a BackgroundTask AFTER this
    # request's session closes, and commit() expired every ORM object above.
    # Reloading each row while the session is still open keeps its scalar
    # attributes readable once the rows are detached.
    db.refresh(product)
    seller = product.seller          # lazy re-load while the session is open
    if seller is not None:
        db.refresh(seller)
    db.refresh(buyer)

    logger.info(
        "Purchase: %s bought '%s' for ₹%.2f (seller trust -> %s)",
        buyer.email,
        product.title,
        transaction.final_price,
        seller.trust_score if seller is not None else "n/a",
    )

    # Task: "Product Sold" emails - queued so checkout never waits on Brevo
    # (email_service never raises; offline tests clear BREVO_API_KEY).
    if seller is not None:
        background.add_task(
            send_product_sold_emails,
            seller,
            buyer,
            product,
            transaction.final_price,
        )

    return PurchaseResponse(
        transaction_id=transaction.id,
        product_id=product.id,
        final_price=transaction.final_price,
        product_status="sold",
    )


@router.get(
    "/transactions/my",
    response_model=MyTransactionsResponse,
    summary="My bought and sold history",
)
def my_transactions(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> MyTransactionsResponse:
    """Return the logged-in student's purchase + sale history, newest first."""
    user = _load_user(db, token)

    bought_rows = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.product).joinedload(Product.seller),
            joinedload(Transaction.buyer),
        )
        .filter(Transaction.buyer_id == user.id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )
    sold_rows = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.product).joinedload(Product.seller),
            joinedload(Transaction.buyer),
        )
        .join(Product, Transaction.product_id == Product.id)
        .filter(Product.seller_id == user.id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )

    def _serialize(tx: Transaction) -> TransactionRead:
        product = tx.product
        return TransactionRead(
            id=tx.id,
            product_id=tx.product_id,
            buyer_id=tx.buyer_id,
            final_price=tx.final_price,
            status=tx.status,
            timestamp=tx.timestamp,
            product_title=product.title if product else None,
            product_image_url=product.image_url if product else None,
            product_status=product.status if product else None,
            buyer_name=tx.buyer.name if tx.buyer else None,
            seller_name=product.seller.name if product and product.seller else None,
        )

    return MyTransactionsResponse(
        bought=[_serialize(tx) for tx in bought_rows],
        sold=[_serialize(tx) for tx in sold_rows],
    )
