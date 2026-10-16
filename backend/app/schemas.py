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
from typing import Literal
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


class UserRead(BaseModel):
    """Response body for user profile endpoints."""

    # Pydantic v2: populate from ORM attributes (User(...) objects).
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    firebase_uid: str
    name: str
    email: str
    status: str = Field(
        default="active",
        description="Moderation state: 'active' | 'blocked'. Blocked users "
                    "receive 403 on listing/transaction writes.",
    )
    trust_score: float = Field(
        description="Reputation score, neutral default 5.0 (driven by the "
                    "Phase 3 trust model).",
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


class ProductRead(BaseModel):
    """Response body for product endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    title: str
    description: str
    category: str
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
    created_at: datetime

    @model_validator(mode="after")
    def _backfill_image_urls(self) -> "ProductRead":
        """Guarantee a non-null gallery for pre-upgrade rows.

        Listings created before the 4-angle feature have `image_urls = NULL`;
        mirroring the front cover here means the Flutter carousel never has to
        branch on null.
        """
        if not self.image_urls:
            self.image_urls = [self.image_url] if self.image_url else []
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


class PurchaseResponse(BaseModel):
    """Response body for POST /products/{product_id}/purchase."""

    transaction_id: UUID
    product_id: UUID
    final_price: float
    product_status: str = "sold"


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
        min_length=5,
        max_length=20,
        description="10-15 search keywords: brand, synonyms, use-case terms.",
    )
    image_urls: list[str]

    # protected_namespaces=() -> allows the `model` / `model_name` fields
    # without Pydantic's "protected namespace model_" warning.
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())


class AnalyzeImagesHint(BaseModel):
    """Optional extra context the client may attach (unused for now)."""

    notes: str | None = None


# =============================================================================
# Master Admin - AI provider control plane (Task 2)
# =============================================================================
class AiConfigRead(BaseModel):
    """GET /admin/ai-config - never leaks the raw key."""

    ai_provider: Literal["gemini", "openai", "groq", "openrouter"]
    ai_model: str
    ai_base_url: str | None = None
    has_api_key: bool
    masked_key: str | None = Field(
        default=None,
        description="'sk-...abcd' style mask; null when no key is stored.",
    )


class AiConfigUpdate(BaseModel):
    """PUT /admin/ai-config - applies immediately (no redeploy needed)."""

    ai_provider: Literal["gemini", "openai", "groq", "openrouter"]
    ai_model: str = Field(..., min_length=1, max_length=120)
    ai_api_key: str | None = Field(
        default=None,
        max_length=400,
        description="New API key. Omit to keep the stored one; send an empty "
                    "string to clear it.",
    )
    ai_base_url: str | None = Field(
        default=None,
        max_length=400,
        description="Optional custom endpoint URL.",
    )


# =============================================================================
# Buyer-seller chat + CampusMart AI assistant (Task 5)
# =============================================================================
class ChatMessageCreate(BaseModel):
    """Request body for POST /chats/messages."""

    product_id: UUID
    receiver_id: UUID
    message: str = Field(..., min_length=1, max_length=4000)


class ChatMessageRead(BaseModel):
    """One message as returned by the chat endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    sender_id: UUID
    receiver_id: UUID
    message: str
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

    message: str = Field(..., min_length=1, max_length=4000)
    history: list[AiChatMessage] = Field(
        default_factory=list,
        max_length=40,
        description="Prior turns (oldest first) so the assistant keeps "
                    "context across the conversation.",
    )


class AiChatResponse(BaseModel):
    """Reply from the CampusMart AI assistant."""

    reply: str
    source: str = Field(
        "'llm' when the configured provider answered, 'catalog' when the "
        "rule-based local assistant answered.",
    )
    recommended_product_ids: list[UUID] = Field(default_factory=list)
