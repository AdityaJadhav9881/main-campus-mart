"""
wanted.py
=========
"Want to Buy" (WTB) Campus Request Board router with AI Reverse-Matching.

Students post what they need (e.g. "Looking for mini drafter under ₹300").
Features:
  1. GET /wanted/ - list open requests with up to 3 live matching products.
  2. POST /wanted/ - post a request, auto-generate AI keywords, reverse-match live items,
     and broadcast notification to students at the same college.
  3. POST /wanted/ai-draft - auto-expand raw text ("need drafter under 300 urgent") into
     a structured request.
  4. POST /wanted/{id}/fulfill & DELETE /wanted/{id} - complete or remove request.
"""

import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..ai import key_pool_engine
from ..auth import get_or_create_current_user, verify_firebase_token
from ..database import get_db
from ..models import Notification, Product, User, WantedRequest
from ..schemas import (
    ProductRead,
    WantedAiDraftRequest,
    WantedAiDraftResponse,
    WantedRequestCreate,
    WantedRequestRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wanted", tags=["Want to Buy (WTB) Board"])


def _current_user(
    token: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db),
) -> User:
    return get_or_create_current_user(db, token)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _find_matches_for_wanted(db: Session, req: WantedRequest, limit: int = 3) -> list[ProductRead]:
    """Find live active products that match this wanted request."""
    # Build search tokens from title + ai_keywords
    tokens = set()
    raw = f"{req.title} {req.category} {req.ai_keywords or ''}".lower()
    for word in re.findall(r"\b[a-z0-9]{3,}\b", raw):
        tokens.add(word)

    query = (
        db.query(Product)
        .filter(
            Product.status == "active",
            Product.seller_id != req.user_id,
        )
    )

    if req.college_name:
        query = query.filter(
            or_(
                Product.college_name == req.college_name,
                Product.college_name.is_(None),
            )
        )

    # Budget filter: product price within or close to max_budget (up to +15%)
    query = query.filter(Product.listed_price <= (req.max_budget * 1.15))

    candidates = query.order_by(Product.created_at.desc()).limit(20).all()
    matched = []
    for p in candidates:
        p_text = f"{p.title} {p.description} {p.category} {p.ai_tags or ''}".lower()
        score = sum(1 for t in tokens if t in p_text)
        if score > 0 or p.category.lower() == req.category.lower():
            matched.append((score, p))

    matched.sort(key=lambda x: x[0], reverse=True)
    return [ProductRead.model_validate(p) for _, p in matched[:limit]]


def _to_read(db: Session, req: WantedRequest) -> WantedRequestRead:
    matches = _find_matches_for_wanted(db, req, limit=3)
    return WantedRequestRead(
        id=req.id,
        user_id=req.user_id,
        requester_name=req.requester_name,
        requester_email=req.requester_email,
        college_name=req.college_name,
        college_code=req.college_code,
        title=req.title,
        description=req.description,
        max_budget=req.max_budget,
        category=req.category,
        branch=req.branch,
        academic_year=req.academic_year,
        urgency=req.urgency,
        status=req.status,
        ai_keywords=req.ai_keywords,
        created_at=req.created_at,
        matching_products=matches,
    )


@router.get(
    "/",
    response_model=list[WantedRequestRead],
    summary="List active Wanted requests with live product matches",
)
def list_wanted_requests(
    college_name: str | None = Query(default=None),
    branch: str | None = Query(default=None),
    academic_year: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[WantedRequestRead]:
    """Returns open wanted requests matching filters with live matching products."""
    query = db.query(WantedRequest).filter(WantedRequest.status == "open")

    if college_name and college_name.strip():
        query = query.filter(WantedRequest.college_name == college_name.strip())

    if branch and branch.strip() and branch.strip() != "All Branches":
        query = query.filter(
            or_(
                WantedRequest.branch == branch.strip(),
                WantedRequest.branch == "All Branches",
            )
        )

    if academic_year and academic_year.strip() and academic_year.strip() != "All Years":
        query = query.filter(
            or_(
                WantedRequest.academic_year == academic_year.strip(),
                WantedRequest.academic_year == "All Years",
            )
        )

    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(WantedRequest.title).like(term),
                func.lower(WantedRequest.description).like(term),
                func.lower(WantedRequest.ai_keywords).like(term),
            )
        )

    requests = query.order_by(WantedRequest.created_at.desc()).limit(limit).all()
    return [_to_read(db, r) for r in requests]


@router.post(
    "/",
    response_model=WantedRequestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Post a new Wanted request",
)
def create_wanted_request(
    payload: WantedRequestCreate,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> WantedRequestRead:
    """Post an item wanted request with instant AI keyword expansion and campus alert."""
    if current_user.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is blocked from posting requests.",
        )

    college = payload.college_name or current_user.college_name or "Campus Network"
    code = payload.college_code or current_user.college_code

    # Extract keywords
    words = set(re.findall(r"\b[a-z0-9]{3,}\b", f"{payload.title} {payload.description}".lower()))
    keywords = ", ".join(sorted(words))

    req = WantedRequest(
        user_id=current_user.id,
        requester_name=current_user.name,
        requester_email=current_user.email,
        college_name=college,
        college_code=code,
        title=payload.title.strip(),
        description=payload.description.strip(),
        max_budget=payload.max_budget,
        category=payload.category,
        branch=payload.branch,
        academic_year=payload.academic_year,
        urgency=payload.urgency,
        status="open",
        ai_keywords=keywords,
        created_at=_utcnow(),
    )
    db.add(req)

    # Campus broadcast notification: notify students in same college
    same_college_students = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            User.college_name == college,
            User.status == "active",
        )
        .limit(30)
        .all()
    )

    for student in same_college_students:
        db.add(
            Notification(
                user_id=student.id,
                title=f"🙋 Wanted at {college}: {req.title} (Budget ₹{req.max_budget:.0f})",
                body=f"{current_user.name} needs this ({req.urgency}). Tap if you have one to sell!",
                type="wanted_request",
                reference_id=str(req.id),
            )
        )

    db.commit()
    db.refresh(req)
    logger.info("Wanted request created by %s: '%s'", current_user.email, req.title)
    return _to_read(db, req)


@router.post(
    "/ai-draft",
    response_model=WantedAiDraftResponse,
    summary="AI Quick-Fill: expand short raw sentence into structured request",
)
def draft_wanted_with_ai(
    payload: WantedAiDraftRequest,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> WantedAiDraftResponse:
    """Uses LLM or rule engine to parse 'need drafter under 300 urgent for monday'."""
    text = payload.raw_text.strip()

    # Rule-based deterministic extraction
    budget_match = re.search(r"(?:under|budget|max|rs\.?|inr|₹)\s*(\d+)", text, re.I)
    budget = float(budget_match.group(1)) if budget_match else 500.0

    urgency = "Flexible"
    if re.search(r"\b(urgent|asap|today|tomorrow|monday)\b", text, re.I):
        urgency = "Urgent (24–48h)"
    elif re.search(r"\b(this week|soon)\b", text, re.I):
        urgency = "This Week"

    branch = "First Year (Common)"
    if re.search(r"\b(computer|it|coding|laptop|python|c\+\+|java)\b", text, re.I):
        branch = "Computer / IT"
    elif re.search(r"\b(mechanical|workshop|cad|thermo)\b", text, re.I):
        branch = "Mechanical"
    elif re.search(r"\b(electrical|entc|circuit|arduino|multimeter)\b", text, re.I):
        branch = "Electrical / ENTC"
    elif re.search(r"\b(civil|survey|concrete)\b", text, re.I):
        branch = "Civil"
    elif re.search(r"\b(pharmacy|pharma|biology|chemistry)\b", text, re.I):
        branch = "Pharmacy"

    category = "Academic Material"
    if re.search(r"\b(drafter|calculator|scale|sheet|apron|roller)\b", text, re.I):
        category = "Lab Gear & Instruments"
    elif re.search(r"\b(speaker|headphone|phone|laptop|charger|mouse|keyboard)\b", text, re.I):
        category = "Electronics"

    title_words = [w for w in text.split() if not re.match(r"^(need|want|looking|for|under|\d+|urgent|rs|inr)$", w, re.I)]
    title = f"Looking for {' '.join(title_words).capitalize() or text}"[:100]

    # Try fast LLM completion if key pool is active
    try:
        prompt = (
            f"You are CampusMart AI. Given this student request: '{text}', generate structured JSON: "
            '{"title": "Clean item title", "description": "Helpful 1-2 sentence description", '
            f'"max_budget": {budget}, "category": "{category}", "branch": "{branch}", '
            f'"academic_year": "FE (1st Year)", "urgency": "{urgency}", "ai_keywords": ["keyword1", "keyword2"]}}'
        )
        llm_out = key_pool_engine.execute_completion(db, prompt, role="listing")
        data = json.loads(re.search(r"\{.*\}", llm_out, re.DOTALL).group(0))
        return WantedAiDraftResponse(
            title=data.get("title", title),
            description=data.get("description", f"Looking to purchase {text} for campus coursework."),
            max_budget=float(data.get("max_budget", budget)),
            category=data.get("category", category),
            branch=data.get("branch", branch),
            academic_year=data.get("academic_year", "FE (1st Year)"),
            urgency=data.get("urgency", urgency),
            ai_keywords=data.get("ai_keywords", [category, branch]),
        )
    except Exception:
        # Instant reliable fallback
        return WantedAiDraftResponse(
            title=title,
            description=f"Need {text} urgently for campus coursework and submissions.",
            max_budget=budget,
            category=category,
            branch=branch,
            academic_year="FE (1st Year)" if branch == "First Year (Common)" else "All Years",
            urgency=urgency,
            ai_keywords=[category, branch, urgency],
        )


@router.post(
    "/{wanted_id}/fulfill",
    response_model=WantedRequestRead,
    summary="Mark a Wanted request as fulfilled",
)
def fulfill_wanted_request(
    wanted_id: UUID,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> WantedRequestRead:
    """Requester marks their post fulfilled."""
    req = db.query(WantedRequest).filter(WantedRequest.id == wanted_id).first()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only creator can fulfill.")

    req.status = "fulfilled"
    db.commit()
    db.refresh(req)
    return _to_read(db, req)


@router.delete(
    "/{wanted_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a Wanted request",
)
def delete_wanted_request(
    wanted_id: UUID,
    current_user: User = Depends(_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Removes a student's own wanted request."""
    req = db.query(WantedRequest).filter(WantedRequest.id == wanted_id).first()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if req.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only creator can delete.")

    db.delete(req)
    db.commit()
