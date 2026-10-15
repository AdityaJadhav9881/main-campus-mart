"""
routers/products.py
===================
Marketplace listing endpoints.

    POST /products/  (protected) - run the LangGraph AI pipeline, THEN insert
                                   the listing (Phase 3 integration).
    GET  /products/  (public)    - list every ACTIVE product as JSON.

Phase 3 update
--------------
Before any database write, POST /products/ passes the raw payload to
`ai_orchestrator.invoke()` (Listing Intelligence -> Price Prediction ->
Trust & Fraud Detection). The AI output owns three columns:

    category         <- extracted_category (client-supplied value ignored)
    suggested_price  <- price_agent fair-value estimate
    status           <- 'flagged' if trust_flag else 'active'

Flagged listings never appear in the public GET /products/ feed, which
filters on status='active'.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from ..ai.orchestrator import ai_orchestrator
from ..auth import extract_uid, verify_firebase_token
from ..database import get_db
from ..models import Product, User
from ..schemas import ProductCreate, ProductRead
from ..storage import StorageError, save_upload

logger = logging.getLogger(__name__)

# Prefix + path "/" below combine to the spec path "POST /products/".
router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "/upload-image/",
    status_code=status.HTTP_200_OK,
    summary="Upload a listing photo (Cloudinary)",
)
async def upload_listing_image(
    request: Request,
    file: UploadFile = File(...),
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> dict:
    """Store one listing photo and return its CDN URL.

    Phase 6 cloud pipeline:
        1. Auth required (same bearer token as listing creation).
        2. Image is validated (MIME allow-list, 5 MB cap).
        3. Uploaded to Cloudinary when CLOUDINARY_* env vars are set;
           otherwise written to /backend/uploads and served by this API.
        4. Returns {"image_url": "https://..."} which the Flutter client
           copies straight into the POST /products/ `image_url` field.
    """
    # Touch the verified identity so the dependency is exercised even if a
    # future refactor drops it from the signature (audit trail in logs).
    firebase_uid = extract_uid(token)

    # Phase 7: blocked students cannot feed the listing pipeline.
    uploader = (
        db.query(User).filter(User.firebase_uid == firebase_uid).first()
    )
    if uploader is not None and uploader.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been blocked. Contact campus support.",
        )

    try:
        image_url = save_upload(file, base_url=str(request.base_url))
    except StorageError as exc:
        logger.warning("Image upload rejected for %s: %s", firebase_uid, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    logger.info("Image uploaded by %s -> %s", firebase_uid, image_url)
    return {"image_url": image_url}


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create product listing",
)
def create_product(
    payload: ProductCreate,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> Product:
    """Create a listing for the authenticated seller, AI-analyzed first.

    Flow:
        1. Extract the verified Firebase UID from the token.
        2. Resolve the seller's profile row (required by the seller_id FK).
        3. Run the LangGraph AI orchestrator on the raw payload.
        4. Insert: category/suggested_price/status from the AI result.
    """
    firebase_uid = extract_uid(token)

    # The seller must already have a profile -> FK (seller_id -> users.id).
    seller = (
        db.query(User).filter(User.firebase_uid == firebase_uid).first()
    )
    if seller is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create your profile first (POST /users/) before listing products.",
        )

    # Phase 7: blocked students cannot create listings (moderation ban).
    if seller.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been blocked. Contact campus support.",
        )

    # -------------------------------------------------------------------------
    # Phase 3: LangGraph AI pipeline - runs BEFORE any DB write
    # -------------------------------------------------------------------------
    # Ordering matters: because nothing has been added to the session yet, an
    # AI failure leaves zero partial state behind.
    try:
        ai_result = ai_orchestrator.invoke(
            {
                "title": payload.title,
                "description": payload.description,
                "image_url": payload.image_url,
                "condition": payload.condition,
                # `age` is optional in the schema; agents must always receive
                # a value, so normalize missing input to a sentinel string.
                "age": payload.age or "unspecified",
            }
        )
    except Exception:  # noqa: BLE001 - converted to an actionable HTTP error
        # Fail CLOSED on purpose: Trust & Fraud detection is a safety gate, so
        # a pipeline error must REJECT the listing rather than publish it
        # un-analyzed.
        logger.exception("AI orchestrator failed; rejecting listing")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI analysis pipeline failed; listing was not created.",
        )

    # Observability: moderators can see why a listing was flagged later.
    logger.info(
        "AI result: category=%s suggested_price=%s trust_flag=%s reason=%s",
        ai_result.get("extracted_category"),
        ai_result.get("suggested_price"),
        ai_result.get("trust_flag"),
        ai_result.get("trust_reason"),
    )

    # Trust gate -> lifecycle status (GET /products/ only serves 'active').
    new_status = "flagged" if ai_result.get("trust_flag") else "active"

    product = Product(
        seller_id=seller.id,       # FK: authenticated seller's profile row
        title=payload.title,
        description=payload.description,
        # AI owns category since Phase 3 (any client value is ignored).
        category=ai_result["extracted_category"],
        condition=payload.condition,
        image_url=payload.image_url,
        # price_agent output - replaces the old NULL default.
        suggested_price=ai_result["suggested_price"],
        listed_price=payload.listed_price,
        status=new_status,
        # Phase 7: persist the trust agent's exact reason when flagged so the
        # admin dashboard can show moderators WHY the listing was held.
        trust_reason=ai_result.get("trust_reason") if new_status == "flagged" else None,
    )

    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get(
    "/",
    response_model=list[ProductRead],
    summary="List active products",
)
def list_active_products(db: Session = Depends(get_db)) -> list[Product]:
    """Return all products currently marked 'active', newest first.

    Public endpoint (no auth) so browsing works before login. By design this
    also hides 'flagged' (fraud-suspect) listings from buyers. Pagination can
    be layered on in Phase 4 once the catalog grows.
    """
    return (
        db.query(Product)
        # Phase 4: eager-load the seller so `product.seller_trust_score` (the
        # read-only property consumed by ProductRead) does not trigger an
        # N+1 query per listing on the feed.
        .options(joinedload(Product.seller))
        .filter(Product.status == "active")
        .order_by(Product.created_at.desc())
        .all()
    )
