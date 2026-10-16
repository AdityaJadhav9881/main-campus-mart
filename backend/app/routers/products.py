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
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..ai import vision_master
from ..ai.orchestrator import ai_orchestrator
from ..auth import (
    account_terminated,
    extract_uid,
    get_or_create_current_user,
    verify_firebase_token,
)
from ..database import get_db
from ..email_service import send_listing_published_email
from ..models import Product, User
from ..schemas import (
    AnalyzeImagesRequest,
    AnalyzeImagesResponse,
    ProductCreate,
    ProductRead,
)
from ..storage import StorageError, save_upload

logger = logging.getLogger(__name__)

# Prefix + path "/" below combine to the spec path "POST /products/".
router = APIRouter(prefix="/products", tags=["products"])


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards in user input (paired with escape="\\").

    SQLAlchemy 2.1's ColumnOperators.ilike() has no `autoescape` flag, so the
    `?q=` / `?category=` search escapes percent, underscore and backslash
    itself - a student searching for "100%" gets literal matches, not a
    wildcard scan.
    """
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


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
        2. Image is validated (MIME allow-list, 5 MB cap). Uploads that arrive
           as `application/octet-stream` / with no content type - the normal
           case for Android's image_picker - are identified from their magic
           bytes (or filename extension) instead of being rejected with 400.
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
        raise account_terminated()

    try:
        image_url, content_type = save_upload(
            file, base_url=str(request.base_url)
        )
    except StorageError as exc:
        logger.warning("Image upload rejected for %s: %s", firebase_uid, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # content_type is the RESOLVED type (sniffed when the client sent
    # application/octet-stream), so moderators can see what really landed.
    logger.info(
        "Image uploaded by %s -> %s (%s, declared %s)",
        firebase_uid,
        image_url,
        content_type,
        file.content_type or "none",
    )
    return {"image_url": image_url}


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create product listing",
)
def create_product(
    payload: ProductCreate,
    background: BackgroundTasks,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> Product:
    """Create a listing for the authenticated seller, AI-analyzed first.

    Flow:
        1. Extract the verified Firebase UID from the token.
        2. Resolve the seller's profile row (required by the seller_id FK).
        3. Run the LangGraph AI orchestrator on the raw payload.
        4. Insert: category/suggested_price/status from the AI result.
        5. Queue the branded "your listing is live" email (Brevo) as a
           background task - non-blocking, a mail hiccup cannot fail the
           listing.
    """
    # The seller must already have a profile -> auto-provision if needed.
    seller = get_or_create_current_user(db, token)

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

    # Fair value: the vision AI's INR estimate (POST /products/analyze-images
    # output the seller's Sell form was auto-filled with) wins when present -
    # it actually SAW the item. The blind price agent stays as the fallback
    # for clients that skip the 4-photo scan. A client-supplied figure outside
    # a sane band around the asking price (deal-badge manipulation) is ignored.
    suggested_price = ai_result.get("suggested_price")
    if payload.ai_suggested_price is not None:
        low, high = payload.listed_price * 0.2, payload.listed_price * 5.0
        if low <= payload.ai_suggested_price <= high:
            suggested_price = payload.ai_suggested_price
        else:
            logger.warning(
                "ai_suggested_price %.2f outside [%.2f, %.2f] for listed %.2f; "
                "keeping price-agent value",
                payload.ai_suggested_price, low, high, payload.listed_price,
            )

    # Full photo set: `image_url` remains the front cover (grid/legacy), while
    # `image_urls` carries the whole 4-angle gallery the vision AI inspected.
    image_urls = [url for url in (payload.image_urls or []) if url]
    if payload.image_url and payload.image_url not in image_urls:
        image_urls.insert(0, payload.image_url)

    product = Product(
        seller_id=seller.id,       # FK: authenticated seller's profile row
        title=payload.title,
        description=payload.description,
        # AI owns category since Phase 3 (any client value is ignored).
        category=ai_result["extracted_category"],
        condition=payload.condition,
        image_url=payload.image_url,
        image_urls=image_urls,
        ai_tags=payload.ai_tags,
        ai_condition_notes=payload.ai_condition_notes,
        # price_agent (or vision AI) output - replaces the old NULL default.
        suggested_price=suggested_price,
        listed_price=payload.listed_price,
        status=new_status,
        # Phase 7: persist the trust agent's exact reason when flagged so the
        # admin dashboard can show moderators WHY the listing was held.
        trust_reason=ai_result.get("trust_reason") if new_status == "flagged" else None,
    )

    # Snapshot the seller BEFORE commit (commit expires ORM attributes; the
    # background email runs detached after the session closes).
    seller_email, seller_name = seller.email, seller.name

    db.add(product)
    db.commit()
    db.refresh(product)

    # Task: "Product Listed" confirmation - queued so the HTTP response never
    # waits on Brevo, and email_service swallows any network failure.
    background.add_task(
        send_listing_published_email, seller_email, seller_name, product
    )
    return product


@router.post(
    "/analyze-images",
    response_model=AnalyzeImagesResponse,
    status_code=status.HTTP_200_OK,
    summary="Vision-AI inspection of 4+ listing photos",
)
def analyze_listing_images(
    payload: AnalyzeImagesRequest,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> dict:
    """Inspect the seller's 4-angle photo set with the configured Vision LLM.

    Contract (Task 2):
        * Authenticated (blocked accounts are rejected by the bearer layer).
        * AT LEAST 4 photos are required - Front, Back, Side,
          Close-up/Label - and fewer is a clear 400 (not a silent partial).
        * The configured provider (SystemConfig: gemini/openai/groq/openrouter)
          answers with STRICT JSON: exact product/brand/model, 4-angle wear ->
          condition, title/description/category, INR price band + suggested and
          listed prices, and 10-15 ai_tags.
        * No API key configured yet -> intelligent INR (₹) heuristic fallback
          (source='heuristic'), so the Sell flow never dead-ends.
    """
    # `verify_firebase_token` already blocks terminated accounts; touching the
    # identity here keeps the audit trail explicit for this expensive endpoint.
    extract_uid(token)

    image_urls = [str(url).strip() for url in payload.image_urls if str(url).strip()]
    if len(image_urls) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Please upload at least 4 photos - Front, Back, Side and a "
                f"Close-up/Label shot (received {len(image_urls)} of 4)."
            ),
        )

    result = vision_master.analyze_listing_images(
        db,
        image_urls,
        title=payload.title,
        description=payload.description,
        condition=payload.condition,
    )
    logger.info(
        "analyze-images -> source=%s category=%s condition=%s price=₹%.0f tags=%d",
        result.get("source"),
        result.get("category"),
        result.get("condition"),
        float(result.get("suggested_price_inr") or 0),
        len(result.get("ai_tags") or []),
    )
    return result


@router.get(
    "/",
    response_model=list[ProductRead],
    summary="List active products",
)
def list_active_products(
    q: str | None = Query(
        default=None,
        max_length=200,
        description="Free-text search across title, description, category, "
                    "ai_tags and ai_condition_notes (visual/semantic match).",
    ),
    category: str | None = Query(
        default=None,
        max_length=80,
        description="Exact category filter, case-insensitive "
                    "(e.g. 'Electronics').",
    ),
    db: Session = Depends(get_db),
) -> list[Product]:
    """Return products currently marked 'active', newest first.

    Public endpoint (no auth) so browsing works before login. By design this
    also hides 'flagged' (fraud-suspect) listings from buyers.

    Search (Task 3): `?q=` matches ANY of title / description / category /
    ai_tags / ai_condition_notes with case-insensitive substring semantics, so
    "bluetooth audio", "bose" or "music box" all surface a speaker the vision
    AI analysed. `?category=` applies the marketplace chip filter server-side.
    """
    query = db.query(Product)
    # Phase 4: eager-load the seller so `product.seller_trust_score` (the
    # read-only property consumed by ProductRead) does not trigger an
    # N+1 query per listing on the feed.
    query = query.options(joinedload(Product.seller)).filter(Product.status == "active")

    if category and category.strip():
        # Exact (case-insensitive) chip filter - LIKE wildcards typed by a
        # user are escaped so "%"/"_" stay literal characters.
        query = query.filter(
            Product.category.ilike(_escape_like(category.strip()), escape="\\")
        )

    term = (q or "").strip()
    if term:
        pattern = f"%{_escape_like(term)}%"
        query = query.filter(
            or_(
                Product.title.ilike(pattern, escape="\\"),
                Product.description.ilike(pattern, escape="\\"),
                Product.category.ilike(pattern, escape="\\"),
                Product.ai_tags.ilike(pattern, escape="\\"),
                Product.ai_condition_notes.ilike(pattern, escape="\\"),
            )
        )

    return query.order_by(Product.created_at.desc()).all()


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete your own listing",
)
def delete_own_listing(
    product_id: UUID,
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> None:
    """Remove a listing the authenticated student owns.

    Guards (mirrors the create/upload policy):
        * 404 - listing does not exist.
        * 403 - blocked account.
        * 403 - someone else's listing (admins use DELETE /admin/listings/{id}).
        * 400 - already sold (purchase history is append-only and the FK is
          ON DELETE RESTRICT, so the row must be kept).

    Seller trust is intentionally NOT penalised here: a student cleaning up
    their own posts is normal marketplace behaviour (the -0.8 penalty stays
    reserved for admin moderation deletes).
    """
    user = get_or_create_current_user(db, token)

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
    if product.seller_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own listings.",
        )
    if product.status == "sold":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sold listings are kept as purchase history and cannot be deleted.",
        )

    db.delete(product)
    try:
        db.commit()
    except IntegrityError as exc:  # FK RESTRICT from an existing transaction
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a listing with existing purchase history.",
        ) from exc

    logger.info("Listing '%s' deleted by owner %s", product_id, user.email)
