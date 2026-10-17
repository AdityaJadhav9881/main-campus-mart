"""
models.py
=========
SQLAlchemy ORM schema definitions for CampusMart AI (Phase 1).

Tables
------
users            : Student accounts hydrated from Firebase Auth.
products         : Second-hand items listed by sellers on the marketplace.
transactions     : Purchase records linking a buyer to a product.
system_config    : Runtime settings (AI provider/model/key) owned by the admin.
chat_messages    : Buyer-seller messages scoped to a product thread.
email_otps       : Pending signup verification codes.
action_otps      : Pending verify-before-action codes (sell / purchase).
ai_chat_sessions : Saved Ask-AI conversations (history drawer).
ai_chat_messages : Persisted turns inside an Ask-AI conversation.
notifications    : Bell-icon alerts (college listings, orders, messages...).
cart_items       : Products parked in a student's cart before checkout.
college_directory: AI/web-discovered colleges cached outside the CET catalog.

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
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
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

    # Contact number the Master Admin can set/correct from the dashboard
    # (also echoed on order cards so buyers and sellers can coordinate).
    # NULL for accounts that never provided one.
    phone = Column(String(20), nullable=True)

    # --- Maharashtra CET Cell college identity (college network) -------------
    # Free-text official college name + its 4-digit DTE/CET institute code
    # (e.g. "COEP Technological University" / "6006"). NULL for accounts that
    # predate the college network; students pick theirs on Sign Up and can
    # change it in Profile.
    college_name = Column(String(255), nullable=True)
    college_code = Column(String(16), nullable=True)

    # Academic classification (branch / department & current engineering year)
    branch = Column(
        String(80),
        nullable=False,
        default="All Branches",
        server_default="'All Branches'",
    )
    academic_year = Column(
        String(50),
        nullable=False,
        default="All Years",
        server_default="'All Years'",
    )

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

    # --- College network ------------------------------------------------------
    # The seller's college at listing time; powers the "My College" Discover
    # filter and the same-college push notifications. Indexed because
    # filtering by campus is a primary browse mode.
    college_name = Column(String(255), nullable=True, index=True)
    college_code = Column(String(16), nullable=True)

    # Free-text category label (e.g. 'textbooks', 'electronics', 'furniture').
    # Indexed because category browsing is a primary marketplace filter.
    category = Column(String(80), nullable=False, index=True)

    # Academic branch/department & year classification
    branch = Column(
        String(80),
        nullable=False,
        default="All Branches",
        server_default="'All Branches'",
        index=True,
    )
    academic_year = Column(
        String(50),
        nullable=False,
        default="All Years",
        server_default="'All Years'",
        index=True,
    )

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

    message = Column(Text, nullable=False, default="")

    # WhatsApp-style photo messages: Cloudinary URL of the attached photo
    # (nullable - most messages are text only). A message may be photo-only
    # (empty string body).
    image_url = Column(Text, nullable=True)

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

    # --- Structured checkout (order-handover upgrade) -------------------------
    # Coordinator/meetup details the buyer fills in the 4-step checkout sheet.
    # All nullable so pre-upgrade rows and quick legacy purchases stay valid.
    delivery_address = Column(String(400), nullable=True)
    hostel_or_landmark = Column(String(200), nullable=True)
    contact_phone = Column(String(20), nullable=True)

    # 'cash_on_meetup' | 'gpay_upi' (free string for forward compatibility).
    payment_method = Column(String(30), nullable=True)

    # UPI transaction reference / UTR when payment_method = 'gpay_upi'.
    upi_reference = Column(String(120), nullable=True)

    # Buyer's pickup/handover notes for the seller.
    order_notes = Column(Text, nullable=True)

    # Email action-OTP that authorised this purchase (6 digits).
    otp_code = Column(String(8), nullable=True)

    # Fulfilment state shown as the order card headline:
    #   'Requested / Processing' -> default at checkout
    #   'Completed' | 'Cancelled' -> updated during handover
    order_status = Column(
        String(40),
        nullable=False,
        default="Requested / Processing",
        server_default="'Requested / Processing'",
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

    # College network: the CET college picked in the Sign Up sheet travels
    # with the OTP row so verify-otp can stamp it onto the fresh User.
    college_name = Column(String(255), nullable=True)
    college_code = Column(String(16), nullable=True)

    expires_at = Column(DateTime(timezone=True), nullable=False)


class ActionOTP(Base):
    """One pending email verification code for a sensitive ACTION.

    Separate from EmailOTP (signup) because the unique-email constraint there
    would collide with a concurrent signup, and the payload differs:

        POST /auth/send-action-otp   -> create/replace a row per (email, action)
                                        with a 10-minute expiry.
        POST /auth/verify-action-otp -> mark verified + mint `action_token`;
                                        the client then passes the token/otp to
                                        POST /products/ or /purchase.

    Actions: 'sell' (publish a listing) | 'purchase' (place an order).
    """

    __tablename__ = "action_otps"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    email = Column(String(255), nullable=False, index=True)
    otp_code = Column(String(6), nullable=False)

    # 'sell' | 'purchase' (free string for future actions like 'delete').
    action_type = Column(String(30), nullable=False)

    # Human context shown in the email + verification sheet ("Bose QC35 II").
    item_title = Column(String(200), nullable=True)

    # Opaque proof handed to the client after a successful verify; routers
    # accept it in place of the raw code.
    action_token = Column(String(64), nullable=True)

    verified = Column(Boolean, nullable=False, default=False)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )


class AiChatSession(Base):
    """A saved Ask-AI conversation shown in the Gemini-style history drawer.

    One row per conversation; messages cascade with it so "delete chat"
    wipes the transcript atomically. `title` is auto-derived from the first
    user prompt (first ~4 meaningful words).
    """

    __tablename__ = "ai_chat_sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String(200), nullable=False, default="New chat")

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default="now()",
    )

    messages = relationship(
        "AiChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AiChatMessage.created_at",
        lazy="selectin",
    )


class AiChatMessage(Base):
    """One persisted turn (user or assistant) inside an AiChatSession."""

    __tablename__ = "ai_chat_messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 'user' | 'assistant'
    role = Column(String(12), nullable=False)

    content = Column(Text, nullable=False, default="")

    # Photo attached to this turn (inspection requests), Cloudinary URL.
    image_url = Column(Text, nullable=True)

    # JSON array of catalog product UUIDs the assistant recommended, so the
    # history replay can re-render recommendation cards.
    matched_products_json = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )

    session = relationship("AiChatSession", back_populates="messages")


class Notification(Base):
    """In-app notification for the bell icon + native push mirror.

    Types: 'college_listing' | 'order_placed' | 'item_sold' | 'chat_message'
           | 'call' | 'system'.
    `reference_id` carries the deep-link target as a string: a product UUID
    (college_listing), a chat counterpart/user UUID (chat_message, call), or
    a transaction UUID (order_placed / item_sold).
    """

    __tablename__ = "notifications"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String(200), nullable=False)
    body = Column(String(500), nullable=False)

    # 'college_listing' | 'order_placed' | 'item_sold' | 'chat_message'
    # | 'call' | 'system'
    type = Column(String(30), nullable=False, default="system", index=True)

    reference_id = Column(String(64), nullable=True)

    is_read = Column(Boolean, nullable=False, default=False, index=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )


class CartItem(Base):
    """One product parked in a student's cart before checkout.

    Unique (user_id, product_id): adding the same listing twice is a no-op.
    """

    __tablename__ = "cart_items"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )

    product = relationship("Product", lazy="joined")

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),
    )


class CollegeDirectory(Base):
    """A college discovered outside the bundled CET catalog, cached forever.

    `GET /colleges` serves the bundled catalog first, then these rows, then
    (only on a full miss) runs AI / web discovery - `CollegeDirectory` is
    where the result lands so the same query is paid for exactly once.
    `source` records how the entry was found ('ai' = Gemini Search grounding,
    'wikipedia', 'osm' = Nominatim, 'admin' = manual seed).

    Intentionally NOT a foreign-key target: users/products keep denormalized
    college_name / college_code strings so pickers stay decoupled from this
    cache (a deleted directory row must never break an account).
    """

    __tablename__ = "college_directory"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # DTE / CET Cell institute code when known, otherwise "" (the picker
    # shows a "Verified Campus" badge for code-less entries).
    code = Column(String(16), nullable=False, default="", index=True)

    name = Column(String(255), nullable=False, index=True)
    short_name = Column(String(120), nullable=False, default="")
    city = Column(String(120), nullable=False, default="", index=True)
    state = Column(String(120), nullable=False, default="Maharashtra")

    # JSON list - same shape as cet_colleges.CetCollege.aliases.
    aliases = Column(JSON, nullable=False, default=list)

    source = Column(String(24), nullable=False, default="ai")
    verified = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )


class WantedRequest(Base):
    """A 'Want to Buy' (WTB) request posted by a student on campus.

    Other students at the same college (or branch) can see this, match it with
    what they have, and message the requester directly.
    """

    __tablename__ = "wanted_requests"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    requester_name = Column(String(120), nullable=False)
    requester_email = Column(String(255), nullable=False)
    college_name = Column(String(255), nullable=False, index=True)
    college_code = Column(String(16), nullable=True)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    max_budget = Column(Float, nullable=False)
    category = Column(String(80), nullable=False, default="Academic Material")
    branch = Column(String(80), nullable=False, default="All Branches")
    academic_year = Column(String(50), nullable=False, default="All Years")
    urgency = Column(String(40), nullable=False, default="Flexible")  # 'Urgent (24–48h)' | 'This Week' | 'Flexible'
    status = Column(String(20), nullable=False, default="open", server_default="'open'")  # 'open' | 'fulfilled' | 'closed'
    ai_keywords = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )

    requester = relationship("User", lazy="joined")


class CallSession(Base):
    """P2P Audio/Video call session between two students.

    Tracks ringing state, caller/receiver signaling, duration, and completion.
    """

    __tablename__ = "call_sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    caller_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    caller_name = Column(String(120), nullable=False)

    receiver_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receiver_name = Column(String(120), nullable=False)

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )

    call_type = Column(String(20), nullable=False, default="voice")  # 'voice' | 'video'
    status = Column(
        String(20),
        nullable=False,
        default="ringing",
        server_default="'ringing'",
    )  # 'ringing' | 'connected' | 'declined' | 'ended' | 'missed'

    sdp_offer = Column(Text, nullable=True)
    sdp_answer = Column(Text, nullable=True)
    audio_chunks_json = Column(Text, nullable=True)

    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default="now()",
    )
    connected_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    caller = relationship("User", foreign_keys=[caller_id], lazy="joined")
    receiver = relationship("User", foreign_keys=[receiver_id], lazy="joined")
    product = relationship("Product", lazy="joined")

