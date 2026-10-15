"""
models.py
=========
SQLAlchemy ORM schema definitions for CampusMart AI (Phase 1).

Tables
------
users        : Student accounts hydrated from Firebase Auth.
products     : Second-hand items listed by sellers on the marketplace.
transactions : Purchase records linking a buyer to a product.

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
