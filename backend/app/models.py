"""
models.py
=========
SQLAlchemy ORM schema definitions for CampusMart AI (Phase 1).

Tables
------
users          : Student accounts hydrated from Firebase Auth.
products       : Second-hand items listed by sellers on the marketplace.
transactions   : Purchase records linking a buyer to a product.
system_config  : Runtime settings (AI provider/model/key) owned by the admin.
chat_messages  : Buyer-seller messages scoped to a product thread.

Design notes
------------
* All primary keys are UUIDs generated in Python so IDs are unguessable
  (security) and safe to merge across services later.
* Tables use snake_case plural names via `__tablename__`.
* Relationships are declared bidirectionally so Phase 2 API code can navigate
  `user.products` / `product.seller` without hand-written JOINs.
* Timestamps are timezone-aware UTC (`DateTime(timezone=True)`) to eliminate
  client clock-skew and daylight-saving bugs.
* This module uses a relative import, so always run the backend as a package
  from `/backend` (e.g. `uvicorn app.main:app --reload`).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID  # native PG UUID type
from sqlalchemy.orm import relationship

from .database import Base


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Centralized helper keeps every table's default timestamp policy identical
    (single source of truth - easier to change in Phase 2 if needed).
    """
    return datetime.now(timezone.utc)


class User(Base):
    """A CampusMart account.

    Identity/auth comes from Firebase Auth; this table stores the profile plus
    platform-only fields (notably `trust_score`, which the Phase 3 scikit-learn
    model will update).
    """

    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,       # generated in Python on INSERT
        nullable=False,
    )

    # Stable identifier issued by Firebase Auth (password, google.com, etc.).
    # UNIQUE guarantee: exactly one DB profile per Firebase identity, which
    # makes "sign in -> find or create profile" idempotent.
    firebase_uid = Column(String(128), unique=True, nullable=False, index=True)

    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False)

    # --- Live-production auth (Phase 7) --------------------------------------
    # 'active'  -> normal marketplace access
    # 'blocked' -> moderation ban: cannot create listings or transactions
    #              (enforced with HTTP 403 in the routers).
    status = Column(
        String(16),
        nullable=False,
        default="active",
        server_default="'active'",
    )

    # bcrypt hash for direct campus email/password auth alongside Firebase.
    # NULL for Firebase-only accounts; set by POST /auth/register or the
    # seed script (seed_db.py gives demo accounts a known password).
    password_hash = Column(String(128), nullable=True)

    # Reputation heuristic (neutral start = 5.0). Range/scale is owned by the
    # trust model in Phase 3 - stored as Float per spec for simple aggregation.
    trust_score = Column(Float, nullable=False, default=5.0, server_default="5.0")

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,          # application-side UTC default
        server_default="now()",   # DB-side fallback if a raw INSERT omits it
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'blocked')",
            name="ck_users_status",
        ),
    )

    # --- Relationships -------------------------------------------------------
    # A student can list many products. ORM cascade keeps Python-side state in
    # sync with the DB-level ON DELETE CASCADE on products.seller_id.
    products = relationship(
        "Product",
        back_populates="seller",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # Purchases made by this user. NO ORM cascade here: transaction history is
    # append-only and protected at the DB level (FK ON DELETE RESTRICT).
    purchases = relationship(
        "Transaction",
        back_populates="buyer",
        lazy="select",
    )


class Product(Base):
    """A single second-hand item listed on the marketplace."""

    __tablename__ = "products"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # Owner of the listing. ON DELETE CASCADE => deleting a user removes their
    # listings (products without transactions).
    seller_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,               # hot path: "my listings" / seller profile queries
    )

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)

    # Free-text category label (e.g. 'textbooks', 'electronics', 'furniture').
    # Indexed because category browsing is a primary marketplace filter.
    category = Column(String(80), nullable=False, index=True)

    # Free-text condition label, e.g. 'new' | 'like_new' | 'good' | 'fair' | 'poor'.
    condition = Column(String(50), nullable=False)

    # Object-storage URL of the listing photo. Consumed by the YOLO pipeline
    # (Phase 3) to compute the fair-value suggestion.
    image_url = Column(String(500), nullable=False)

    # --- Production upgrade (multi-angle visual listing) ---------------------
    # JSON array of EVERY photo uploaded for this listing. `image_url` above
    # stays the front cover (backward compatible with old clients / the grid),
    # while this holds the full 4-angle set the vision AI inspects:
    #   ["...front.jpg", "...back.jpg", "...side.jpg", "...label.jpg", ...]
    # Stored as JSON (TEXT + json_parse on PostgreSQL) so the read path is a
    # plain Python list on every dialect (PostgreSQL in prod, SQLite in tests).
    image_urls = Column(JSON, nullable=True)

    # Comma-separated visual-search keywords produced by the vision AI
    # (brand, model, object type, synonyms, use-case terms), e.g.
    # "bose, soundlink, bluetooth speaker, portable audio, electronics".
    # Indexed by GET /products/?q= ... (searched with ILIKE, so no B-tree).
    ai_tags = Column(Text, nullable=True)

    # AI inspection summary across all 4 angles (wear, scratches, missing
    # parts, authenticity cues). Displayed on the product detail screen.
    ai_condition_notes = Column(Text, nullable=True)

    # AI-computed fair value (ultralytics YOLO + scikit-learn regressor).
    # NULLABLE on purpose: the vision pipeline fills this asynchronously after
    # the seller submits the listing, so it may not exist at INSERT time.
    suggested_price = Column(Float, nullable=True)

    # What the seller actually asks for - always known at creation time.
    listed_price = Column(Float, nullable=False)

    # Lifecycle flag:
    #   'active'  -> visible in search/browse
    #   'sold'    -> hidden from browse, retained for history
    #   'flagged' -> held for moderation review
    status = Column(
        String(20),
        nullable=False,
        default="active",
        server_default="'active'",   # single quotes => valid SQL literal DEFAULT 'active'
    )

    # Exact human-readable justification returned by the Trust & Fraud Agent
    # when it flagged the listing (Phase 7 admin moderation). NULL for clean
    # listings so the public feed never leaks internal scoring details.
    trust_reason = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )

    # DB-level guard mirroring the allowed values documented above. The ORM
    # defaults handle normal inserts; this CHECK blocks invalid statuses coming
    # from raw SQL, scripts, or future microservices.
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'sold', 'flagged')",
            name="ck_products_status",
        ),
    )

    # --- Relationships -------------------------------------------------------
    seller = relationship("User", back_populates="products")

    # Every purchase attempt against this product (Phase 2 ensures only one
    # can reach 'completed').
    transactions = relationship(
        "Transaction",
        back_populates="product",
        lazy="select",
    )

    # --- Phase 4 (additive) --------------------------------------------------
    # Read-only convenience used ONLY for API serialization: the Flutter feed
    # and detail screens display the seller's trust score next to each
    # listing. Not a Column - computed from the relationship at response time
    # (GET /products/ eager-loads `seller` via joinedload to avoid N+1).
    @property
    def seller_trust_score(self) -> "float | None":
        """Seller's current trust score, or None if the seller row is gone."""
        return self.seller.trust_score if self.seller else None

    @property
    def seller_name(self) -> "str | None":
        """Seller's display name for the mobile detail/profile screens.

        Mirrors `seller_trust_score`: read-only, derived from the relationship
        (GET /products/ eager-loads `seller` via joinedload, so this is free).
        """
        return self.seller.name if self.seller else None

    @property
    def photo_urls(self) -> "list[str]":
        """Every photo for this listing, front cover first.

        Falls back to the single legacy `image_url` column for rows created
        before the 4-angle upgrade, so old listings still render a gallery.
        """
        urls = [u for u in (self.image_urls or []) if u]
        if not urls and self.image_url:
            urls = [self.image_url]
        return urls


class SystemConfig(Base):
    """Runtime configuration persisted in PostgreSQL (Master Admin controlled).

    One row per setting. The AI provider settings written by
    `PUT /admin/ai-config` live here so a Render redeploy (which wipes the
    filesystem but keeps Neon) still boots with the same provider/model/key:

        ai_provider  : 'gemini' | 'openai' | 'groq' | 'openrouter'
        ai_model     : e.g. 'gemini-2.5-flash'
        ai_api_key   : the key the Master Admin pasted in the dashboard
        ai_base_url  : optional custom endpoint override
    """

    __tablename__ = "system_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default="now()",
    )


class ChatMessage(Base):
    """One buyer-seller message on a specific product's thread.

    Threads are identified by the (product_id, sender/receiver) pair: the same
    two students talking about two different products are two separate
    conversations, which is exactly what the Messages tab groups by.
    """

    __tablename__ = "chat_messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sender_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    receiver_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    message = Column(Text, nullable=False)

    # Set the first time the receiver opens the thread -> drives the unread
    # badge on the Messages tab (NULL = unread).
    read_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )

    # --- Relationships -------------------------------------------------------
    # back_populates is intentionally omitted on the sender/receiver side:
    # User has no `sent_messages` accessor, so simple FK relationships keep
    # the ORM from needing ambiguous-foreign-key resolution on User.
    product = relationship("Product", lazy="joined")
    sender = relationship("User", foreign_keys=[sender_id], lazy="joined")
    receiver = relationship("User", foreign_keys=[receiver_id], lazy="joined")


class Transaction(Base):
    """An immutable purchase record: which buyer bought which product, for how
    much, and when.

    Append-only by design: rows are created at checkout and their status is
    updated, never deleted (FKs use ON DELETE RESTRICT to enforce this).
    """

    __tablename__ = "transactions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    buyer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),  # preserve history
        nullable=False,
        index=True,               # hot path: "my orders" queries
    )

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),  # preserve history
        nullable=False,
        index=True,               # hot path: order history for a listing
    )

    # Price actually paid (may differ from listed_price after negotiation).
    final_price = Column(Float, nullable=False)

    # Suggested vocabulary for Phase 2 (kept as String per spec):
    #   'pending' | 'completed' | 'cancelled' | 'disputed'
    status = Column(
        String(30),
        nullable=False,
        default="pending",
        server_default="'pending'",  # quoted => valid SQL literal
    )

    # Named `timestamp` per spec (SQL keyword, but SQLAlchemy quotes it safely).
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )

    # --- Relationships -------------------------------------------------------
    buyer = relationship("User", back_populates="purchases")
    product = relationship("Product", back_populates="transactions")


class EmailOTP(Base):
    """Pending 6-digit email verification code for the OTP signup flow.

    Row lifecycle (Task: registration OTP):
        POST /auth/send-otp   -> upserts ONE row per email (10-min expiry)
                                 holding the hashed password + display name so
                                 verify-otp can create the User atomically.
        POST /auth/verify-otp -> validates the code, creates the active User,
                                 then DELETES this row.
        POST /auth/resend-otp -> replaces otp_code + expiry on the same row.

    Stale rows simply expire (expires_at); no cleanup job is needed because
    send-otp overwrites per email.
    """

    __tablename__ = "email_otps"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # UNIQUE + index: one pending signup per email address.
    email = Column(String(255), unique=True, nullable=False, index=True)

    # 6-digit code as String so leading zeros ("012345") survive intact.
    otp_code = Column(String(6), nullable=False)

    # Snapshot of the signup form, consumed when the User row is created.
    name = Column(String(120), nullable=False)
    password_hash = Column(String(128), nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False)
