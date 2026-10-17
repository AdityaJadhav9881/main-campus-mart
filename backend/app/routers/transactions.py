"""
routers/transactions.py
=======================
Purchase flow + student purchase history (Phase 7) with the structured
checkout upgrade (delivery details, payment method, auto order card).

    POST /products/{product_id}/purchase  (protected) - buy/reserve an active
        listing: creates a Transaction row (optionally carrying the checkout
        sheet's delivery/payment/OTP data), marks the product 'sold',
        increments the seller's trust score (+0.1, capped at 5.0), posts the
        📦 order card into the buyer-seller chat, notifies both parties, and
        clears the item from the buyer's cart.
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
from ..models import CartItem, ChatMessage, Notification, Product, Transaction, User
from ..schemas import (
    CheckoutRequest,
    MyTransactionsResponse,
    PurchaseResponse,
    TransactionRead,
)

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
    payload: CheckoutRequest | None = None,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> PurchaseResponse:
    """Buy/reserve one active listing (optionally with checkout details).

    Flow (single transaction so the sold-claim and trust update are atomic):
        1. 404 if the product does not exist.
        2. 403 if the buyer's account is blocked.
        3. 400 if the listing is not 'active' (already sold/flagged) or if the
           buyer is the seller (cannot buy your own item).
        4. Insert a Transaction at the listed price carrying the optional
           checkout sheet fields (address, phone, payment method, UPI ref,
           action-OTP) and order_status 'Requested / Processing'.
        5. product.status = 'sold'; seller.trust_score += 0.1 (cap 5.0).
        6. Post the 📦 order card into the buyer-seller chat thread.
        7. Notify seller ("Order Received") + buyer ("Order Confirmed").
        8. Remove the item from the buyer's cart, if present.
        9. Queue BOTH Brevo sale emails (non-blocking background task).
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

    payload = payload or CheckoutRequest()

    transaction = Transaction(
        buyer_id=buyer.id,
        product_id=product.id,
        final_price=product.listed_price,
        status="completed",
        delivery_address=(payload.delivery_address or "").strip() or None,
        hostel_or_landmark=(payload.hostel_or_landmark or "").strip() or None,
        contact_phone=(payload.contact_phone or "").strip() or None,
        payment_method=payload.payment_method,
        upi_reference=(payload.upi_reference or "").strip() or None,
        order_notes=(payload.notes or "").strip() or None,
        otp_code=(payload.otp_code or "").strip() or None,
        order_status="Requested / Processing",
    )
    product.status = "sold"
    if product.seller is not None:
        product.seller.trust_score = min(5.0, product.seller.trust_score + SELL_TRUST_BONUS)

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    # --- Auto order card in the buyer -> seller chat --------------------------
    payment_line = {
        "cash_on_meetup": "💵 Cash on Meetup",
        "gpay_upi": "💳 GPay UPI",
    }.get(transaction.payment_method or "", "To be decided")
    if transaction.payment_method == "gpay_upi" and transaction.upi_reference:
        payment_line += f" (ref: {transaction.upi_reference})"
    meet_line = (
        transaction.hostel_or_landmark
        or transaction.delivery_address
        or "To be decided in chat"
    )
    card_lines = [
        "📦 NEW ORDER PLACED",
        f"Item: {product.title}",
        f"Price: ₹{transaction.final_price:,.0f}",
        f"Buyer: {buyer.name}",
        f"Payment: {payment_line}",
        f"Meet: {meet_line}",
    ]
    if transaction.contact_phone:
        card_lines.append(f"Contact: {transaction.contact_phone}")
    if transaction.otp_code:
        card_lines.append("OTP Verified: ✅")
    if transaction.order_notes:
        card_lines.append(f"Notes: {transaction.order_notes}")
    card_lines.append("Let's coordinate the handover!")
    order_card = ChatMessage(
        product_id=product.id,
        sender_id=buyer.id,
        receiver_id=product.seller_id,
        message="\n".join(card_lines),
        image_url=None,
    )
    db.add(order_card)

    # --- Bell notifications for both sides -------------------------------------
    db.add(
        Notification(
            user_id=product.seller_id,
            title=f"🎉 Order Received for '{product.title}'!",
            body=(
                f"{buyer.name} placed an order for "
                f"₹{transaction.final_price:,.0f} · {payment_line}"
            )[:500],
            type="order_placed",
            reference_id=str(transaction.id),
            is_read=False,
        )
    )
    db.add(
        Notification(
            user_id=buyer.id,
            title=f"✅ Order Confirmed: '{product.title}'",
            body=(
                f"Your order (₹{transaction.final_price:,.0f}) was sent to "
                f"{(product.seller.name if product.seller else 'the seller')}. "
                "Message them to arrange your campus pickup."
            )[:500],
            type="order_placed",
            reference_id=str(transaction.id),
            is_read=False,
        )
    )

    # --- Clear the item from the buyer's cart (if it was parked there) --------
    db.query(CartItem).filter(
        CartItem.user_id == buyer.id,
        CartItem.product_id == product.id,
    ).delete(synchronize_session=False)

    db.commit()
    db.refresh(order_card)
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
        seller_id=product.seller_id,
        seller_name=seller.name if seller is not None else None,
        order_status=transaction.order_status,
        auto_chat_message_id=order_card.id,
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
            order_status=tx.order_status,
            payment_method=tx.payment_method,
            hostel_or_landmark=tx.hostel_or_landmark,
            delivery_address=tx.delivery_address,
            contact_phone=tx.contact_phone,
        )

    return MyTransactionsResponse(
        bought=[_serialize(tx) for tx in bought_rows],
        sold=[_serialize(tx) for tx in sold_rows],
    )
