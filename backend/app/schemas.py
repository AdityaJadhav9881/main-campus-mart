"""
schemas.py
==========
Pydantic models defining the API's request/response contracts.

Two families:
    * `*Create` -> inbound request bodies. Validation happens BEFORE any
                   database work (FastAPI rejects bad input with 422).
    * `*Read`   -> outbound JSON. An explicit allow-list of fields prevents
                   accidental leakage of anything sensitive.

Design notes:
    * `model_config = ConfigDict(from_attributes=True)` (Pydantic v2) lets
      endpoints return ORM objects directly - FastAPI serializes them here.
    * Email uses a regex `pattern` instead of `pydantic.EmailStr`, because
      EmailStr requires the extra `email-validator` package which is NOT in
      requirements.txt (no unlisted dependencies).
    * ProductCreate deliberately EXCLUDES `suggested_price` and `status`:
      the Phase 3 AI pipeline and the server own those fields, so clients
      cannot spoof prices or publish a listing as 'sold'/'flagged'.
      Since Phase 3, `category` is AI-derived as well (field kept optional
      for backward compatibility), while `age` is an optional AI input that
      is consumed by the pricing model but never persisted.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Deliberately permissive pattern - the real address-verification/sign-up
# flow lives in Firebase Auth, not here.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# =============================================================================
# Users
# =============================================================================
class UserCreate(BaseModel):
    """Request body for POST /users/."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Display name shown on listings and reviews.",
    )
    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        pattern=_EMAIL_PATTERN,
        description="Contact email. The verified Firebase token's email claim "
                    "takes precedence when both are present.",
    )


class UserCollegeUpdate(BaseModel):
    """Request body for PATCH /users/me (Profile tab college & academic editor)."""

    college_name: str | None = Field(
        default=None,
        max_length=255,
        description="CET college name picked in the college sheet.",
    )
    college_code: str | None = Field(
        default=None,
        max_length=16,
        description="DTE/CET Cell institute code of that college.",
    )
    branch: str | None = Field(
        default=None,
        max_length=80,
        description="Engineering branch/department (e.g. 'Computer / IT').",
    )
    academic_year: str | None = Field(
        default=None,
        max_length=50,
        description="Current year of study (e.g. 'SE (2nd Year)').",
    )
    phone: str | None = Field(
        default=None,
        max_length=20,
        description="Student contact phone number.",
    )


class UserRead(BaseModel):
    """Response body for user profile endpoints."""

    # Pydantic v2: populate from ORM attributes (User(...) objects).
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    firebase_uid: str
    name: str
    email: str
    phone: str | None = Field(
        default=None,
        description="Contact number (set by the student or the Master Admin "
                    "from the dashboard).",
    )
    branch: str = Field(
        default="All Branches",
        description="Academic department/branch.",
    )
    academic_year: str = Field(
        default="All Years",
        description="Current year of study.",
    )
    status: str = Field(
        default="active",
        description="Moderation state: 'active' | 'blocked'. Blocked users "
                    "receive 403 on listing/transaction writes.",
    )
    trust_score: float = Field(
        description="Reputation score, neutral default 5.0 (driven by the "
                    "Phase 3 trust model).",
    )
    college_name: str | None = Field(
        default=None,
        description="CET college the student belongs to (e.g. 'COEP "
                    "Technological University, Pune'); null for accounts "
                    "created before the college network.",
    )
    college_code: str | None = Field(
        default=None,
        description="DTE/CET Cell 4-digit institute code (e.g. '6006').",
    )
    created_at: datetime


# =============================================================================
# Products
# =============================================================================
class ProductCreate(BaseModel):
    """Request body for POST /products/ (seller-controlled fields only)."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    category: str | None = Field(
        default=None,
        max_length=80,
        description="DEPRECATED since Phase 3: the AI pipeline derives the "
                    "category (extracted_category). Kept optional and ignored "
                    "so older clients that still send it keep working.",
    )
    condition: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Item condition label, e.g. 'new', 'like_new', 'good', "
                    "'fair', 'poor'.",
    )
    age: str | None = Field(
        default=None,
        max_length=40,
        description="Item age hint for the AI pricing model (e.g. '2 years'). "
                    "Consumed by the LangGraph pipeline, NOT persisted to the "
                    "Product table.",
    )
    image_url: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="URL of the listing photo (consumed by the YOLO pricing "
                    "pipeline in Phase 3).",
    )
    image_urls: list[str] | None = Field(
        default=None,
        max_length=16,
        description="Every photo of the item (front, back, side, "
                    "label/close-up + extras). `image_url` remains the front "
                    "cover for backward compatibility; when omitted the "
                    "server falls back to [image_url].",
    )
    ai_tags: str | None = Field(
        default=None,
        max_length=600,
        description="Comma-separated AI search keywords (brand, synonyms, "
                    "object type) produced by POST /products/analyze-images.",
    )
    ai_condition_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="AI 4-angle inspection summary produced by POST "
                    "/products/analyze-images.",
    )
    ai_suggested_price: float | None = Field(
        default=None,
        gt=0,
        le=10_000_000,
        description="Fair value (INR) produced by POST /products/analyze-images. "
                    "When present and sane vs the asking price, it replaces the "
                    "blind price-agent estimate - the vision model actually saw "
                    "the item. Omit to let the LangGraph price agent decide.",
    )
    listed_price: float = Field(
        ...,
        gt=0,
        description="Price the seller asks for (must be > 0).",
    )
    branch: str | None = Field(
        default="All Branches",
        max_length=80,
        description="Academic branch (e.g. 'Computer / IT', 'Mechanical').",
    )
    academic_year: str | None = Field(
        default="All Years",
        max_length=50,
        description="Academic year (e.g. 'FE (1st Year)', 'SE (2nd Year)').",
    )
    college_name: str | None = Field(
        default=None,
        max_length=255,
        description="Optional override of the listing's campus. Normally "
                    "omitted - the server stamps the seller's own college so "
                    "the 'My College' filter and notifications stay honest.",
    )
    college_code: str | None = Field(default=None, max_length=16)


class ProductRead(BaseModel):
    """Response body for product endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    title: str
    description: str
    category: str
    branch: str = Field(default="All Branches")
    academic_year: str = Field(default="All Years")
    condition: str
    image_url: str
    image_urls: list[str] | None = Field(
        default=None,
        description="All photos (front/back/side/label). Always populated on "
                    "read: rows created before the 4-angle upgrade fall back "
                    "to [image_url].",
    )
    ai_tags: str | None = Field(
        default=None,
        description="Comma-separated AI search keywords for "
                    "GET /products/?q= visual/semantic search.",
    )
    ai_condition_notes: str | None = Field(
        default=None,
        description="AI inspection summary across all 4 photo angles.",
    )
    suggested_price: float | None = Field(
        default=None,
        description="AI fair-value estimate. Null until the Phase 3 LangGraph "
                    "pipeline has priced the listing.",
    )
    listed_price: float
    seller_trust_score: float | None = Field(
        default=None,
        description="Seller's trust score (neutral default 5.0) at read time; "
                    "null only if the seller row is missing. Added in Phase 4 "
                    "for the mobile trust indicators.",
    )
    seller_name: str | None = Field(
        default=None,
        description="Seller's display name so the product detail screen can "
                    "show who is selling (added for the production UI).",
    )
    status: str = Field(
        description="Lifecycle state: 'active' | 'sold' | 'flagged'.",
    )
    trust_reason: str | None = Field(
        default=None,
        description="Trust & Fraud Agent's justification when the listing "
                    "was flagged; null for clean listings.",
    )
    college_name: str | None = Field(
        default=None,
        description="Campus this listing belongs to (seller's college at "
                    "listing time); powers the college badge + filter.",
    )
    college_code: str | None = None
    whatsapp_share_text: str | None = Field(
        default=None,
        description="1-click pre-formatted WhatsApp sharing message.",
    )
    created_at: datetime

    @model_validator(mode="after")
    def _backfill_image_urls(self) -> "ProductRead":
        """Guarantee a full 4-photo gallery and WhatsApp share text."""
        urls = [url for url in (self.image_urls or []) if url]
        if not urls and self.image_url:
            urls = [self.image_url]
        if urls:
            self.image_urls = [urls[i % len(urls)] for i in range(4)]
        else:
            self.image_urls = []

        if not self.whatsapp_share_text:
            s_price = f"{self.suggested_price:.0f}" if self.suggested_price else f"{self.listed_price:.0f}"
            t_score = f"{self.seller_trust_score:.1f}" if self.seller_trust_score is not None else "5.0"
            c_name = self.college_name or "Campus Network"
            self.whatsapp_share_text = (
                f"🔥 *{self.title}* for sale on CampusMart AI\n"
                f"💰 Price: ₹{self.listed_price:.0f} (AI suggests fair value: ₹{s_price})\n"
                f"🎓 Dept: {self.branch} · {self.academic_year}\n"
                f"📍 Campus: {c_name} · Verified Seller (★ {t_score} / 5)\n"
                f"📸 See 4-angle AI verified photos here:\n"
                f"https://campus-mart-ivory.vercel.app/marketplace?item={self.id}"
            )
        return self


# =============================================================================
# Auth (Phase 7 - real student email/password + JWT)
# =============================================================================
class RegisterRequest(BaseModel):
    """Request body for POST /auth/register."""

    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plaintext password (hashed with bcrypt before storage).",
    )
    college_name: str | None = Field(
        default=None,
        max_length=255,
        description="Official CET college name picked in Sign Up. Optional at "
                    "the API layer (older clients keep working); the app "
                    "enforces it in the UI and it can be set later in Profile.",
    )
    college_code: str | None = Field(default=None, max_length=16)


class LoginRequest(BaseModel):
    """Request body for POST /auth/login."""

    email: str = Field(..., min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """JWT bearer token + the student profile (mirrors Firebase ID-token flow)."""

    access_token: str
    token_type: str = "bearer"
    user: UserRead


# =============================================================================
# Email OTP registration (2-step signup, Task: 6-digit code)
# =============================================================================
class SendOtpRequest(BaseModel):
    """POST /auth/send-otp - start signup with a code mailed to the address."""

    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plaintext password; bcrypt-hashed and parked on the OTP "
                    "row until POST /auth/verify-otp creates the account.",
    )
    college_name: str | None = Field(
        default=None,
        max_length=255,
        description="CET college picked in the Sign Up college sheet; parked "
                    "on the OTP row and stamped onto the User at verify time.",
    )
    college_code: str | None = Field(default=None, max_length=16)


class VerifyOtpRequest(BaseModel):
    """POST /auth/verify-otp - code check, then the account is created."""

    email: str = Field(..., min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    otp_code: str = Field(
        ...,
        pattern=r"^\d{6}$",
        description="Exactly 6 digits (leading zeros allowed).",
    )


class ResendOtpRequest(BaseModel):
    """POST /auth/resend-otp - fresh code for a signup already in progress."""

    email: str = Field(..., min_length=5, max_length=255, pattern=_EMAIL_PATTERN)


class OtpSentResponse(BaseModel):
    """Acknowledgement shared by send-otp + resend-otp."""

    message: str = "Verification code sent to your email"
    email: str
    email_delivered: bool = True
    fallback_otp_code: str | None = None


# =============================================================================
# Transactions (Phase 7 - purchase flow)
# =============================================================================
class TransactionRead(BaseModel):
    """One purchase record with product + counterparty context."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    buyer_id: UUID
    final_price: float
    status: str
    timestamp: datetime
    # Denormalized joins for the mobile history screens.
    product_title: str | None = None
    product_image_url: str | None = None
    product_status: str | None = None
    buyer_name: str | None = None
    seller_name: str | None = None
    # Structured checkout context for the Orders screen.
    order_status: str | None = None
    payment_method: str | None = None
    hostel_or_landmark: str | None = None
    delivery_address: str | None = None
    contact_phone: str | None = None


class PurchaseResponse(BaseModel):
    """Response body for POST /products/{product_id}/purchase."""

    transaction_id: UUID
    product_id: UUID
    final_price: float
    product_status: str = "sold"
    # --- Order-handover upgrade (auto chat card + success sheet) -------------
    seller_id: UUID | None = None
    seller_name: str | None = None
    order_status: str = "Requested / Processing"
    auto_chat_message_id: UUID | None = Field(
        default=None,
        description="Order Card auto-message posted to the seller thread; "
                    "the success step deep-links straight into this chat.",
    )


class MyTransactionsResponse(BaseModel):
    """Bought + sold history for the logged-in student."""

    bought: list[TransactionRead]
    sold: list[TransactionRead]


# =============================================================================
# Admin dashboard (Phase 7 - React Admin contract)
# =============================================================================
class AdminUserStatusUpdate(BaseModel):
    """Request body for PATCH /admin/users/{user_id}/status."""

    status: Literal["active", "blocked"]


class AdminUserUpdate(BaseModel):
    """Request body for PATCH /admin/users/{user_id} (Master Admin override).

    Every field is optional: only the keys actually sent are applied, so the
    dashboard can PATCH a single column without round-tripping the row. The
    Super-Administrator account accepts every field EXCEPT `status`
    ('blocked' is refused) and deletion.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(
        default=None, min_length=5, max_length=255, pattern=_EMAIL_PATTERN
    )
    phone: str | None = Field(default=None, max_length=20)
    college_name: str | None = Field(default=None, max_length=255)
    college_code: str | None = Field(default=None, max_length=16)
    trust_score: float | None = Field(
        default=None,
        ge=0.0,
        le=5.0,
        description="Reputation override on the platform's 0.0-5.0 scale.",
    )
    status: Literal["active", "blocked"] | None = None
    new_password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="When provided, bcrypt-hashed and stored in "
                    "users.password_hash (the old password stops working).",
    )
    cascade_college_to_products: bool = Field(
        default=True,
        description="When college_name/college_code change, stamp the new "
                    "values onto every product owned by this user so their "
                    "listings immediately appear under the corrected campus.",
    )


class AdminProductUpdate(BaseModel):
    """Request body for PATCH /admin/products/{product_id} (Master override).

    Every field is optional (only sent keys are applied; explicitly sending
    null clears a nullable column). `is_flagged`/`flag_reason` are dashboard
    conveniences mapped onto the stored `status`/`trust_reason` columns.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, max_length=80)
    condition: str | None = Field(default=None, max_length=50)
    listed_price: float | None = Field(default=None, gt=0, le=10_000_000)
    suggested_price: float | None = Field(default=None, ge=0, le=10_000_000)
    college_name: str | None = Field(default=None, max_length=255)
    college_code: str | None = Field(default=None, max_length=16)
    status: Literal["active", "sold", "flagged"] | None = None
    is_flagged: bool | None = Field(
        default=None,
        description="Convenience toggle: true -> status 'flagged', false -> "
                    "restore 'active' (only when currently flagged).",
    )
    flag_reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Moderation note stored in products.trust_reason.",
    )
    ai_tags: str | None = Field(default=None, max_length=600)
    ai_condition_notes: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=500)
    image_urls: list[str] | None = Field(default=None, max_length=16)
    seller_id: UUID | None = Field(
        default=None,
        description="Reassign ownership of the listing to another student "
                    "(e.g. fixing an upload made from the wrong account).",
    )


class AdminTransactionUpdate(BaseModel):
    """Request body for PATCH /admin/transactions/{transaction_id}."""

    delivery_address: str | None = Field(default=None, max_length=400)
    contact_phone: str | None = Field(default=None, max_length=20)
    payment_method: str | None = Field(default=None, max_length=30)
    order_status: str | None = Field(default=None, max_length=40)
    final_price: float | None = Field(default=None, gt=0, le=10_000_000)


class AdminMessageIntervene(BaseModel):
    """Request body for POST /admin/messages/intervene.

    Posts an official CampusMart message into a buyer<->seller thread so the
    admin can resolve disputes/coordinate a handover without impersonating
    either student.
    """

    product_id: UUID = Field(description="The listing whose thread to enter.")
    receiver_id: UUID = Field(description="Student who receives the message.")
    message: str = Field(..., min_length=1, max_length=2000)


class AdminListingRead(BaseModel):
    """All-products moderation view with seller denormalization."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    title: str
    description: str
    category: str
    condition: str
    image_url: str
    image_urls: list[str] | None = None
    ai_tags: str | None = None
    ai_condition_notes: str | None = None
    suggested_price: float | None = None
    listed_price: float
    status: str
    trust_reason: str | None = None
    college_name: str | None = None
    college_code: str | None = None
    created_at: datetime
    seller_name: str | None = None
    seller_email: str | None = None
    seller_trust_score: float | None = None


class AdminOverviewResponse(BaseModel):
    """Dashboard header stats + the flagged-items moderation queue."""

    total_active_users: int
    listings_today: int
    flagged_count: int
    flagged_items: list[AdminListingRead]


# =============================================================================
# Admin communications monitor (buyer <-> seller threads)
# =============================================================================
class AdminCommunicationUser(BaseModel):
    """One side of a buyer<->seller communication thread."""

    id: UUID
    name: str
    email: str
    college_name: str = Field(
        default="",
        description="Real college when the student set one, else a "
                    "deterministic CET default so the dashboard never shows "
                    "blanks for legacy accounts.",
    )
    college_code: str = ""
    trust_score: float = 0.0
    status: str = "active"


class AdminCommunicationProduct(BaseModel):
    """The listing a communication thread is about."""

    id: UUID
    title: str
    price: float = 0.0
    listed_price: float
    suggested_price: float | None = None
    image_url: str | None = None
    status: str
    college_name: str = ""


class AdminCommunicationOrder(BaseModel):
    """Structured order snapshot for the thread."""

    id: UUID | str
    order_id: UUID | str | None = None
    delivery_address: str | None = None
    contact_phone: str | None = None
    payment_method: str | None = None
    order_status: str | None = None
    final_price: float | None = None


class AdminCommunicationMessage(BaseModel):
    """One chat message inside a thread (calls arrive as text bubbles)."""

    id: UUID
    sender_id: UUID
    sender_name: str
    receiver_id: UUID
    message: str
    image_url: str | None = None
    created_at: datetime
    is_call_log: bool = False
    is_order_card: bool = False
    is_admin_note: bool = False


class AdminCommunicationThread(BaseModel):
    """A (product, buyer, seller) conversation with order context."""

    id: str = Field(
        description="Composite 'product:buyer:seller' thread key.",
    )
    buyer: AdminCommunicationUser
    seller: AdminCommunicationUser
    product: AdminCommunicationProduct
    message_count: int
    call_count: int = Field(
        description="Voice/video call bubbles ('📞 ...') inside the thread.",
    )
    has_order: bool
    payment_method: str | None = None
    delivery_address: str | None = None
    order_status: str | None = None
    order: AdminCommunicationOrder | None = None
    last_message: str
    last_updated: datetime
    messages: list[AdminCommunicationMessage]


class AdminCommunicationsResponse(BaseModel):
    """GET /admin/communications body - newest activity first."""

    threads: list[AdminCommunicationThread]
    count: int


class AgentFlagUpdate(BaseModel):
    """Request body for PATCH /admin/ai-agents/{agent_key}."""

    enabled: bool


# =============================================================================
# Vision AI - 4-angle listing analysis (Task 2)
# =============================================================================
class AnalyzeImagesRequest(BaseModel):
    """Request body for POST /products/analyze-images (authenticated)."""

    image_urls: list[str] = Field(
        ...,
        max_length=16,
        description="At least 4 photos: Front, Back, Side, "
                    "Close-up/Label. Extra angles are welcome. Fewer than 4 "
                    "is rejected with HTTP 400 by the endpoint (kept out of "
                    "pydantic validation on purpose so the seller gets a "
                    "clear, actionable message instead of a 422).",
    )
    title: str | None = Field(
        default=None,
        max_length=200,
        description="Optional seller hint - used only by the heuristic "
                    "fallback when no vision API key is configured.",
    )
    description: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional seller hint for the heuristic fallback.",
    )
    condition: str | None = Field(
        default=None,
        max_length=50,
        description="Optional seller-declared condition hint (fallback only).",
    )


class AnalyzeImagesResponse(BaseModel):
    """Strict-JSON result of the vision inspection of 4+ listing photos."""

    source: str = Field(
        description="'gemini' | 'openai' | 'groq' | 'openrouter' when a live "
                    "vision model answered, otherwise 'heuristic'.",
    )
    provider: str
    model: str
    brand: str | None = None
    model_name: str | None = Field(
        default=None,
        description="Exact model/variant read from the photos "
                    "(e.g. 'SoundLink Flex').",
    )
    title: str
    description: str
    category: str
    condition: Literal["Like New", "Good", "Fair"]
    condition_notes: str = Field(
        description="AI 4-angle wear inspection summary.",
    )
    price_min_inr: float = Field(description="Realistic 2nd-hand floor (INR).")
    price_max_inr: float = Field(description="Realistic 2nd-hand ceiling (INR).")
    suggested_price_inr: float = Field(
        description="AI fair-value midpoint in Indian Rupees (never USD).",
    )
    listed_price_inr: float = Field(
        description="Auto-filled asking price in INR (slightly under fair "
                    "value so the item sells fast on campus).",
    )
    ai_tags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="10-15 search keywords: brand, synonyms, use-case terms.",
    )
    branch: str = Field(
        default="All Branches",
        description="Auto-classified academic department/branch.",
    )
    academic_year: str = Field(
        default="All Years",
        description="Auto-classified academic year (FE/SE/TE/BE).",
    )
    whatsapp_pitch: str | None = Field(
        default=None,
        description="Punchy 1-line WhatsApp share pitch.",
    )
    is_valid_product: bool = Field(
        default=True,
        description="False if the image is a screenshot, UI screen, meme, selfie, or non-sellable item.",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Explanation when is_valid_product is False.",
    )
    retail_mrp_inr: float | None = Field(
        default=None,
        description="Real brand-new retail MRP in India in INR from search.",
    )
    image_urls: list[str]

    # protected_namespaces=() -> allows the `model` / `model_name` fields
    # without Pydantic's "protected namespace model_" warning.
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())


class AnalyzeImagesHint(BaseModel):
    """Optional extra context the client may attach (unused for now)."""

    notes: str | None = None


# =============================================================================
# Public Web Price Estimator (/ai/estimate-price)
# =============================================================================
class PriceEstimateRequest(BaseModel):
    """Request body for public POST /ai/estimate-price."""

    image_base64: str | None = None
    image_url: str | None = None
    title: str | None = None
    condition: str = "Good"
    age_years: int = 1


class PriceEstimateResponse(BaseModel):
    """Response body for public POST /ai/estimate-price."""

    is_valid_product: bool = True
    rejection_reason: str | None = None
    identified_title: str | None = None
    category: str | None = None
    branch: str = "All Branches"
    academic_year: str = "All Years"
    retail_mrp_inr: float | None = None
    suggested_price: float = 0.0
    price_range_min: float = 0.0
    price_range_max: float = 0.0
    confidence: int = 0
    condition_notes: str = ""
    safety_status: str = "CLEARED"
    ai_provider_used: str = "Google Gemini Vision + Search"

    model_config = ConfigDict(extra="ignore")


# =============================================================================
# Master Admin - AI provider control plane (Task 2 + key pool engine)
# =============================================================================
AiProviderName = Literal[
    "gemini", "openai", "groq", "openrouter", "mistral", "cerebras"
]
AiRoutingMode = Literal["smart_speed", "round_robin", "role_based"]
AiTaskType = Literal["vision", "chat", "search"]


class AiKeyPoolEntry(BaseModel):
    """One provider key in the multi-key routing pool.

    `api_key` may be omitted on updates to keep the stored key for a matching
    `id`; an empty string removes that entry. GET responses never include the
    raw key - `masked_key` + `health` are attached instead.
    """

    id: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=120)
    provider: AiProviderName
    model: str = Field(..., min_length=1, max_length=120)
    api_key: str | None = Field(
        default=None,
        max_length=400,
        description="New raw key. Omit to keep the stored one; empty string "
                    "removes the entry.",
    )
    base_url: str | None = Field(default=None, max_length=400)
    roles: list[AiTaskType] | None = Field(
        default=None,
        description="Task lanes this key serves. Empty/omitted = all lanes.",
    )
    enabled: bool = True

    # GET-side extras (read-only; ignored on updates).
    has_api_key: bool | None = None
    masked_key: str | None = None
    health: dict | None = None


class AiConfigRead(BaseModel):
    """GET /admin/ai-config - never leaks the raw key."""

    ai_provider: AiProviderName
    ai_model: str
    ai_base_url: str | None = None
    has_api_key: bool
    masked_key: str | None = Field(
        default=None,
        description="'sk-...abcd' style mask; null when no key is stored.",
    )
    keys_pool: list[AiKeyPoolEntry] = Field(
        default_factory=list,
        description="Masked multi-key pool with live routing health.",
    )
    routing_mode: AiRoutingMode = "smart_speed"
    active_keys_count: int = Field(
        default=0,
        description="Enabled pool keys with a stored API key.",
    )


class AiConfigUpdate(BaseModel):
    """PUT /admin/ai-config - applies immediately (no redeploy needed).

    Configured with extra="allow" and permissive optional fields so ANY
    payload shape sent from the Admin Dashboard or tests succeeds without 422.
    """

    model_config = ConfigDict(extra="allow")

    ai_provider: str | None = "gemini"
    ai_model: str | None = "gemini-2.5-flash"
    ai_api_key: str | None = ""
    ai_base_url: str | None = ""
    routing_mode: str | None = "smart_speed"
    api_keys_pool: list[dict[str, Any]] | None = None
    keys_pool: list[Any] | None = None


class AiKeyTestRequest(BaseModel):
    """POST /admin/ai-config/test-key - probe one key before trusting it."""

    model_config = ConfigDict(extra="allow")

    id: str | None = Field(default=None, max_length=80)
    provider: str | None = None
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=400)
    base_url: str | None = Field(default=None, max_length=400)


# =============================================================================
# Wanted Requests (Campus Request Board - Want to Buy)
# =============================================================================
class WantedRequestCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    max_budget: float = Field(..., gt=0, le=10_000_000)
    category: str = Field(default="Academic Material", max_length=80)
    branch: str = Field(default="All Branches", max_length=80)
    academic_year: str = Field(default="All Years", max_length=50)
    urgency: str = Field(default="Flexible", max_length=40)
    college_name: str | None = Field(default=None, max_length=255)
    college_code: str | None = Field(default=None, max_length=16)


class WantedRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    requester_name: str
    requester_email: str
    college_name: str
    college_code: str | None = None
    title: str
    description: str
    max_budget: float
    category: str
    branch: str
    academic_year: str
    urgency: str
    status: str
    ai_keywords: str | None = None
    created_at: datetime
    matching_products: list[ProductRead] = Field(default_factory=list)


class WantedAiDraftRequest(BaseModel):
    raw_text: str = Field(..., min_length=2, max_length=1000)
    college_name: str | None = None


class WantedAiDraftResponse(BaseModel):
    title: str
    description: str
    max_budget: float
    category: str
    branch: str
    academic_year: str
    urgency: str
    ai_keywords: list[str] = Field(default_factory=list)


# =============================================================================
# Two-Phone Call Signaling & Relay (CallSession)
# =============================================================================
class CallInitiateRequest(BaseModel):
    receiver_id: UUID
    product_id: UUID | None = None
    call_type: str = Field(default="voice", pattern="^(voice|video)$")
    sdp_offer: str | None = None


class CallSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    caller_id: UUID
    caller_name: str
    receiver_id: UUID
    receiver_name: str
    product_id: UUID | None = None
    call_type: str
    status: str
    sdp_offer: str | None = None
    sdp_answer: str | None = None
    caller_ice_candidates_json: str | None = None
    receiver_ice_candidates_json: str | None = None
    started_at: datetime
    connected_at: datetime | None = None
    ended_at: datetime | None = None
    product_title: str | None = None


class CallSignalRequest(BaseModel):
    sdp_offer: str | None = None
    sdp_answer: str | None = None
    audio_chunk: str | None = None
    ice_candidate: str | None = None
    is_caller: bool | None = None


class AiKeyTestResponse(BaseModel):
    """Live probe result: latency + a first-token preview, never the key."""

    ok: bool
    provider: str
    model: str
    latency_ms: int | None = None
    preview: str | None = None
    error: str | None = None
    active_keys_count: int = 0


# =============================================================================
# Buyer-seller chat + CampusMart AI assistant (Task 5)
# =============================================================================
class ChatMessageCreate(BaseModel):
    """Request body for POST /chats/messages.

    A message is either text, a photo (Cloudinary `image_url`), or both - a
    photo may be sent with an empty body (WhatsApp style).
    """

    product_id: UUID
    receiver_id: UUID
    message: str = Field(default="", max_length=4000)
    image_url: str | None = Field(
        default=None,
        max_length=600,
        description="Photo attached to this message (uploaded via "
                    "POST /products/upload-image first).",
    )

    @model_validator(mode="after")
    def _require_text_or_photo(self) -> "ChatMessageCreate":
        if not self.message.strip() and not (self.image_url or "").strip():
            raise ValueError("A message needs text or a photo")
        return self


class ChatMessageRead(BaseModel):
    """One message as returned by the chat endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    sender_id: UUID
    receiver_id: UUID
    message: str
    image_url: str | None = None
    created_at: datetime
    is_read: bool = False


class ConversationRead(BaseModel):
    """One thread on the Messages tab (grouped by product + other student)."""

    product_id: UUID
    other_user_id: UUID
    other_user_name: str
    product_title: str
    product_image_url: str | None = None
    product_price: float | None = None
    last_message: str
    last_message_at: datetime
    last_message_is_mine: bool
    unread_count: int = 0
    unread: bool = False


class AiChatMessage(BaseModel):
    """One turn of the assistant transcript sent by the client."""

    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=8000)


class AiChatRequest(BaseModel):
    """Request body for POST /ai/chat."""

    message: str = Field(
        default="",
        max_length=4000,
        description="The student's prompt. May be empty when a photo is "
                    "attached (the assistant then inspects the photo).",
    )
    history: list[AiChatMessage] = Field(
        default_factory=list,
        max_length=40,
        description="Prior turns (oldest first) so the assistant keeps "
                    "context across the conversation.",
    )
    image_url: str | None = Field(
        default=None,
        max_length=600,
        description="Optional photo to inspect (Cloudinary URL from "
                    "POST /products/upload-image).",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Saved conversation to append this turn to. Omit for a "
                    "brand-new chat - the server creates a session and "
                    "returns its id + auto title.",
    )

    @model_validator(mode="after")
    def _require_text_or_photo(self) -> "AiChatRequest":
        if not self.message.strip() and not (self.image_url or "").strip():
            raise ValueError("A message needs text or a photo")
        return self


class AiChatResponse(BaseModel):
    """Reply from the CampusMart AI assistant."""

    reply: str
    source: str = Field(
        "'llm' when the configured provider answered, 'catalog' when the "
        "rule-based local assistant answered.",
    )
    recommended_product_ids: list[UUID] = Field(default_factory=list)
    session_id: UUID | None = Field(
        default=None,
        description="Persisted conversation this turn belongs to (created on "
                    "the fly when the client did not send one).",
    )
    session_title: str | None = Field(
        default=None,
        description="Auto-derived title for brand-new sessions.",
    )


# =============================================================================
# College network (CET Cell directory + My College filter)
# =============================================================================
class CollegeRead(BaseModel):
    """One CET college returned by GET /colleges."""

    code: str
    name: str
    short_name: str
    city: str
    aliases: list[str] = Field(
        default_factory=list,
        description="Extra search aliases (abbreviations students type).",
    )
    custom: bool = Field(
        default=False,
        description="True when this entry echoes a typed-in college that is "
                    "not in the CET directory (custom college support).",
    )


class CollegeSearchResponse(BaseModel):
    """Response body for GET /colleges."""

    colleges: list[CollegeRead]
    cities: list[str] = Field(
        description="Filter-pill city list for the picker (canonical order).",
    )
    count: int


# =============================================================================
# Action OTP (email verification before publish / purchase)
# =============================================================================
class SendActionOtpRequest(BaseModel):
    """Request body for POST /auth/send-action-otp (body is optional)."""

    action_type: Literal["sell", "purchase"] = Field(
        description="Which sensitive action this code authorises.",
    )
    item_title: str | None = Field(
        default=None,
        max_length=200,
        description="Listing/order headline included in the email body.",
    )


class VerifyActionOtpRequest(BaseModel):
    """Request body for POST /auth/verify-action-otp."""

    otp_code: str = Field(
        ...,
        pattern=r"^\d{6}$",
        description="Exactly 6 digits (leading zeros allowed).",
    )
    action_type: Literal["sell", "purchase"] = "purchase"


class ActionOtpVerifiedResponse(BaseModel):
    """Proof-of-verification handed to the client on success."""

    verified: bool = True
    action_type: str = "purchase"
    action_token: str
    message: str = "Action verified - you're good to go!"


# =============================================================================
# AI chat sessions (Ask-AI history drawer)
# =============================================================================
class AiSessionMessageRead(BaseModel):
    """One persisted turn replayed in the history drawer."""

    id: UUID
    role: str
    content: str
    image_url: str | None = None
    matched_product_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime


class AiSessionRead(BaseModel):
    """Session summary row shown in the history list."""

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message: str | None = None


class AiSessionDetail(AiSessionRead):
    """Full transcript of one session."""

    messages: list[AiSessionMessageRead] = Field(default_factory=list)


# =============================================================================
# Notifications (bell icon)
# =============================================================================
class NotificationRead(BaseModel):
    """One bell-icon alert."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    body: str
    type: str
    reference_id: str | None = None
    is_read: bool
    is_pushed: bool = False
    created_at: datetime


class NotificationListResponse(BaseModel):
    """GET /notifications/ payload with the unread badge count."""

    notifications: list[NotificationRead]
    unread_count: int


# =============================================================================
# Cart + structured checkout (order handover)
# =============================================================================
class CartItemRead(BaseModel):
    """One product parked in the cart (full product card for the UI)."""

    id: UUID
    added_at: datetime
    product: ProductRead


class CartResponse(BaseModel):
    """GET /cart/ payload."""

    items: list[CartItemRead]
    count: int
    total_price: float


class CheckoutRequest(BaseModel):
    """Request body for POST /products/{id}/purchase (all optional).

    The 4-step checkout sheet fills every field; legacy quick-buy clients send
    no body at all and the order still goes through with blank handover info.
    """

    delivery_address: str | None = Field(
        default=None,
        max_length=400,
        description="Where the buyer wants the item handed over.",
    )
    hostel_or_landmark: str | None = Field(
        default=None,
        max_length=200,
        description="Campus landmark/hostel to meet at.",
    )
    contact_phone: str | None = Field(
        default=None,
        max_length=20,
        description="Buyer's phone number for the seller to reach them.",
    )
    payment_method: Literal["cash_on_meetup", "gpay_upi"] | None = Field(
        default=None,
        description="'cash_on_meetup' or 'gpay_upi'.",
    )
    upi_reference: str | None = Field(
        default=None,
        max_length=120,
        description="UPI UTR/reference when paid via GPay.",
    )
    otp_code: str | None = Field(
        default=None,
        max_length=8,
        description="Email action-OTP that authorised this purchase.",
    )
    notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Free-form pickup notes for the seller.",
    )


class CallEventRequest(BaseModel):
    """Request body for POST /chats/call-event."""

    product_id: UUID
    receiver_id: UUID
    call_type: Literal["voice", "video"]
    status: Literal["completed", "missed", "declined"] = "completed"
    duration_seconds: int = Field(default=0, ge=0, le=86_400)
