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

from pydantic import BaseModel, ConfigDict, Field

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
    status: str = Field(
        description="Lifecycle state: 'active' | 'sold' | 'flagged'.",
    )
    trust_reason: str | None = Field(
        default=None,
        description="Trust & Fraud Agent's justification when the listing "
                    "was flagged; null for clean listings.",
    )
    created_at: datetime


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
