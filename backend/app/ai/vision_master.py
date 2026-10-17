"""
vision_master.py
================
Dynamic multi-provider VISION + text LLM client for CampusMart AI (Task 2).

One unified engine drives both:
    * POST /products/analyze-images - strict-JSON inspection of 4+ listing
      photos (brand/model read from the photos, condition across angles,
      INR price estimate, 10-15 search tags).
    * POST /ai/chat - the "Ask CampusMart AI" student assistant.

Supported providers (selected at runtime from the `system_config` table by
PUT /admin/ai-config - NO redeploy needed; multi-key routing is handled by
`key_pool_engine`):

    gemini      Google  generativelanguage.googleapis.com  (inline base64 parts)
    openai      OpenAI  api.openai.com/v1                  (data-URI image_url)
    groq        Groq    api.groq.com/openai/v1             (OpenAI-compatible)
    openrouter  OpenRouter openrouter.ai/api/v1            (OpenAI-compatible)
    mistral     Mistral api.mistral.ai/v1                  (OpenAI-compatible)
    cerebras    Cerebras api.cerebras.ai/v1                (OpenAI-compatible)

Design notes
------------
* Configuration lives in PostgreSQL (`SystemConfig`), not in the environment:
  a Render redeploy keeps the key/model the Master Admin set on the dashboard.
* Images are downloaded SERVER-SIDE (best effort) and inlined as base64. That
  works even when the photo lives on a private/local /uploads path that the
  provider could never fetch itself.
* Everything fails CLOSED to a deterministic INR heuristic when no API key is
  configured (fresh install) or when the provider errors - the Sell flow must
  never dead-end on an upstream outage. The response's `source` field tells
  the client which path answered ('gemini'|'openai'|'groq'|'openrouter' vs
  'heuristic').
* All prices are Indian Rupees (₹). The prompt hard-bans USD output and the
  heuristic ships an INR item table (pen ₹10-50, textbook ₹250-450,
  used speaker ₹4,000-7,500 ...) - never the old "$80" placeholders.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
import re
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..models import SystemConfig
from ..storage import UPLOAD_DIR
from . import key_pool_engine

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Provider registry
# -----------------------------------------------------------------------------
PROVIDERS: tuple[str, ...] = (
    "gemini",
    "openai",
    "groq",
    "openrouter",
    "mistral",
    "cerebras",
)

DEFAULT_PROVIDER = "gemini"
# GA Gemini Flash on the v1beta REST API. Auto-selected by zero-config engine.
DEFAULT_MODEL = "gemini-2.5-flash"

# Tried in order whenever the configured gemini model errors. First entry in
# the effective chain is always the (normalized) configured model.
GEMINI_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-pro",
    "gemini-flash-latest",
)

# Model ids that look plausible but need normalization.
_GEMINI_MODEL_ALIASES: dict[str, str] = {
    "gemini-3.5-flash-lite": "gemini-3.5-flash",
    "gemini-3-flash": "gemini-3.5-flash",
    "gemini-3-pro": "gemini-2.5-pro",
}


def normalize_gemini_model(model: str | None) -> str:
    """Map a stored/legacy gemini model id onto a real REST API model."""
    cleaned = (model or "").strip()
    if not cleaned:
        return GEMINI_FALLBACK_MODELS[0]
    if cleaned in _GEMINI_MODEL_ALIASES:
        return _GEMINI_MODEL_ALIASES[cleaned]
    return cleaned


def gemini_model_chain(model: str | None) -> list[str]:
    """The ordered, de-duplicated list of gemini models to attempt."""
    chain: list[str] = []
    for candidate in (normalize_gemini_model(model), *GEMINI_FALLBACK_MODELS):
        if candidate and candidate not in chain:
            chain.append(candidate)
    return chain

# Official default endpoints; PUT /admin/ai-config's `ai_base_url` overrides.
PROVIDER_BASE_URLS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
}

# Per-request network budget capped tightly for fast failover and response.
HTTP_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
# Never inline more than ~7 MB per photo (uploads are capped at 5 MB anyway).
MAX_IMAGE_BYTES = 7 * 1024 * 1024

# system_config row keys (single source of truth with routers/admin.py).
CONFIG_KEYS = ("ai_provider", "ai_model", "ai_api_key", "ai_base_url")


# =============================================================================
# SystemConfig persistence (live PostgreSQL, Master Admin controlled)
# =============================================================================
def get_ai_config(db: Session) -> dict[str, str]:
    """Read the AI provider settings, applying documented defaults.

    Returns a plain dict: ai_provider / ai_model / ai_api_key / ai_base_url.
    Missing rows (fresh database) resolve to gemini + gemini-2.5-flash with
    no key, which routes callers into the heuristic fallback.
    """
    rows = {
        row.key: (row.value or "")
        for row in db.query(SystemConfig)
        .filter(SystemConfig.key.in_(CONFIG_KEYS))
        .all()
    }
    provider = (rows.get("ai_provider") or DEFAULT_PROVIDER).strip().lower()
    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER
    return {
        "ai_provider": provider,
        "ai_model": (rows.get("ai_model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "ai_api_key": (rows.get("ai_api_key") or "").strip(),
        "ai_base_url": (rows.get("ai_base_url") or "").strip(),
    }


def save_ai_config(
    db: Session,
    *,
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None = None,
) -> dict[str, str]:
    """Upsert the AI provider settings (PUT /admin/ai-config).

    `api_key=None` means "keep the stored key" (admin only changed the model);
    an empty string clears it. Commits immediately so the very next vision
    request uses the new provider - no redeploy.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported ai_provider '{provider}'")

    current = get_ai_config(db)
    values = {
        "ai_provider": provider,
        "ai_model": (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "ai_api_key": current["ai_api_key"] if api_key is None else api_key.strip(),
        "ai_base_url": (base_url or "").strip(),
    }

    for key, value in values.items():
        row = db.get(SystemConfig, key)
        if row is None:
            db.add(SystemConfig(key=key, value=value))
        else:
            row.value = value
    db.commit()
    logger.info(
        "AI config updated: provider=%s model=%s key=%s base_url=%s",
        values["ai_provider"],
        values["ai_model"],
        "set" if values["ai_api_key"] else "empty",
        values["ai_base_url"] or "default",
    )
    return values


def mask_key(key: str | None) -> str | None:
    """'sk-abc...wxyz' style mask so the dashboard never shows the raw key."""
    if not key:
        return None
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


# =============================================================================
# Strict-JSON vision prompts & Anti-Screenshot / Non-Product Detection
# =============================================================================
_CATEGORY_LIST = (
    "'Electronics', 'Academic Material', 'Lab Gear & Instruments', "
    "'Stationery', 'Hostel & Lifestyle'"
)


def is_screenshot_or_invalid_candidate(
    *,
    title: str | None = None,
    image_urls: list[str] | None = None,
    images: list[dict[str, Any]] | None = None,
) -> tuple[bool, str | None]:
    """Fast pre-check for screenshot patterns in title, URLs/filenames, or image dimensions."""
    # 1. Text checks in title
    if title:
        t_clean = title.strip().lower()
        if re.search(r"\b(?:screenshot|screen\s*shot|screencap|screen\s*recording)\b", t_clean):
            return True, "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell."

    # 2. Check URLs / filenames
    if image_urls:
        for u in image_urls:
            filename = str(u).split("?")[0].split("/")[-1].lower()
            if re.search(r"(?:screenshot|screen_shot|screen-shot|screencap|capture_\d+)", filename):
                return True, "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell."

    # 3. Check image dimensions/aspect ratio if PIL is available
    if images:
        for img in images:
            data = img.get("data")
            if data and len(data) > 0:
                try:
                    import io
                    from PIL import Image
                    with Image.open(io.BytesIO(data)) as pil_img:
                        w, h = pil_img.size
                        fmt = (pil_img.format or "").upper()
                        if w > 0 and h > 0:
                            ratio = h / w if h > w else w / h
                            # Typical Android/iOS screenshots are PNG and aspect ratio >= 2.05
                            if ratio >= 2.05 and fmt == "PNG":
                                return True, "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell."
                except Exception:
                    pass

    return False, None


ANALYSIS_PROMPT = f"""You are the listing-intelligence engine of Campus Mart Ai, an Indian \
college second-hand marketplace. You receive 4+ photos of one item taken from different \
angles: Front, Back, Side, and a Close-up/Label shot. Study EVERY photo before answering.

STAGE 1: PRODUCT VALIDITY CHECK (CRITICAL - ANTI-SCREENSHOT & NON-PRODUCT GATE)
FIRST, inspect whether the uploaded images show a real, physical, sellable product (e.g. bluetooth speaker, \
textbook, calculator, laptop, cycle, drafter, furniture, earphones, lab coat, instruments, electronics, etc.) \
OR an invalid image.
An invalid image includes:
- A screenshot of a mobile phone screen, app interface, chat message, social media feed, website, or digital UI
- A meme, graphic art, cartoon, or computer-generated flyer
- A selfie, photo of a person without an obvious physical item for sale, or portrait
- A blurry wall, floor, ceiling, blank or completely dark shot
- A document, sheet of text, receipt, invoice, or paper document
- A prohibited, dangerous, or non-sellable item
If the image is ANY of the above, you MUST set "is_valid_product": false, and "rejection_reason": "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell." (or specific reason if selfie/blurry/meme).
When "is_valid_product" is false:
- "suggested_price_inr": 0
- "listed_price_inr": 0
- "price_min_inr": 0
- "price_max_inr": 0
- "retail_mrp_inr": null
- "safety_status": "REJECTED"

STAGE 2: BRAND, MODEL, AND WEAR INSPECTION (IF VALID)
Carefully examine all 4 photos and perform deep catalog and brand matching. Read brand names, \
model numbers, serial numbers, labels, engravings, and ports (e.g. recognizing "Bose SoundLink Flex", \
"Casio fx-991EX ClassWiz", "Sony WH-1000XM4", "Logitech MX Master", "Apple MacBook Air M1", \
"HC Verma Concepts of Physics", "SanDisk Ultra 64GB", "Arduino Uno R3", etc.). \
Judge physical wear, scratches, scuffs, dents, and functionality indicators from all angles, and \
calculate accurate realistic resale market prices in Indian Rupees (₹).

Return ONLY one JSON object (no markdown, no commentary, no code fences) with exactly these keys:
{{
  "is_valid_product": boolean      - true if real physical sellable product; false if screenshot, meme, selfie, or non-product
  "rejection_reason": string or null - explanation when is_valid_product is false; null if valid
  "retail_mrp_inr": number or null - brand new retail MRP in India in ₹ from Google Search; null if invalid
  "brand": string or null          - exact brand visible (e.g. "Bose", "Casio", "Apple", "Classmate")
  "model_name": string or null     - exact model/variant (e.g. "SoundLink Flex", "fx-991CW", "AirPods Pro")
  "title": string                  - compelling, accurate marketplace title with brand & model, <= 120 chars
  "description": string            - 2-4 professional, honest sentences: exact specs, condition, included accessories
  "category": string               - exactly one of {_CATEGORY_LIST}
  "branch": string                 - one of "First Year (Common)", "Computer / IT", "Mechanical", "Electrical / ENTC", "Civil", "Pharmacy", "Architecture / Design", "All Branches"
  "academic_year": string          - one of "FE (1st Year)", "SE (2nd Year)", "TE (3rd Year)", "BE (Final Year)", "All Years"
  "whatsapp_pitch": string         - punchy 1-line WhatsApp highlight with emojis (e.g. "🔥 Casio 991EX ClassWiz in mint condition · FE/SE must-have!")
  "condition": string              - exactly one of "Like New", "Good", "Fair"
  "condition_notes": string        - detailed 4-angle inspection summary: front/back/side/label wear,
                                     scratches, dents, button/port condition, accessories/box.
                                     ALWAYS end with the price context in this exact pattern:
                                     "(Retail ~₹<current Indian retail price>; expected used ₹<low>-₹<high>)"
  "price_min_inr": number          - realistic used-price floor in Indian Rupees (₹)
  "price_max_inr": number          - realistic used-price ceiling in Indian Rupees (₹)
  "suggested_price_inr": number    - fair-market resale value in ₹ (rounded to nearest 10)
  "listed_price_inr": number       - fast-sale asking price (5-12% under fair value, rounded to 10)
  "ai_tags": string[]              - 10-15 lowercase search keywords: brand, model,
                                     synonyms, category, use-cases (e.g. "bose", "soundlink flex",
                                     "bluetooth speaker", "portable audio", "waterproof speaker", "electronics")
}}

PRICING RULES - Indian Rupees (₹) ONLY:
  * Benchmark real Indian campus second-hand prices:
    - High-end portable speaker (e.g. Bose SoundLink Flex, JBL Charge): ₹8,500 - ₹12,000 (new is ~₹13k-16k)
    - Budget Bluetooth speaker (boAt, Portronics): ₹600 - ₹1,800
    - Scientific calculator (Casio fx-991EX / CW): ₹600 - ₹1,200
    - Standard engineering / medical textbook: ₹300 - ₹700
    - Wireless ANC headphones (Sony, Bose, Sennheiser): ₹8,000 - ₹18,000
    - Budget TWS earbuds: ₹600 - ₹2,500
    - Student laptop (Core i5 / Ryzen 5 / MacBook): ₹18,000 - ₹48,000
    - Lab instruments (Digital Multimeter, DSO, Drafter): ₹500 - ₹3,500
    - Stationery (Pens, sets, folders): ₹20 - ₹150
  * NEVER output US dollars ($). All numbers must be in INR (₹).
  * NEVER output generic $80 placeholder numbers.
  * SANITY CHECK FIRST: establish the item's current Indian retail price (e.g. a Bose
    SoundLink Flex retails at ~₹13,000 brand new). A working used unit is worth roughly
    55-85% of that depending on condition - NEVER quote a tiny fraction (a working
    Bose speaker is worth ₹8,500-₹10,500 used, never ₹3,000). Only go lower when the
    photos clearly show heavy damage or missing parts.
  * Condition scaling: Like New ~= 85-90% of used fair market, Good ~= 70-75%, Fair ~= 50-60%.

QUALITY RULES:
  * Extract exact brand and model when text or logos are visible in any photo angle.
  * ai_tags must include brand, model, synonyms, and practical college search queries.
  * Return strict valid JSON only."""


WEB_ESTIMATOR_PROMPT = """You are the expert valuation, authenticity, and visual search engine \
of CampusMart AI, an Indian college second-hand marketplace.
A website user is requesting a price valuation of an item in Indian Rupees (₹).
User Context:
* Hint / item name: {title}
* Condition declared: {condition}
* Approximate age: {age_years} year(s)

Carefully examine the photo(s) and perform deep visual inspection and Google Search Grounding.

STAGE 1: PRODUCT VALIDITY CHECK (CRITICAL - ANTI-SCREENSHOT & NON-PRODUCT GATE)
FIRST, inspect whether the photo shows a REAL, PHYSICAL, SELLABLE PRODUCT (like a bluetooth speaker, \
headphones, textbook, calculator, laptop, cycle, camera, drafter, lab gear, backpack, phone, tablet, shoes, desk, chair) \
OR an invalid image.
An invalid image includes:
- A screenshot of a mobile phone screen, app interface, chat message, social media feed, website, or digital UI
- A meme, graphic art, cartoon, or computer-generated flyer
- A selfie, photo of a person without an obvious physical item for sale, or portrait
- A blurry wall, floor, ceiling, blank or completely dark shot
- A document, sheet of text, receipt, invoice, or paper document
- A prohibited, dangerous, or non-sellable item
If the image is ANY of the above, you MUST set "is_valid_product": false, and "rejection_reason": "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell." (or explain if selfie/blurry/meme).
When "is_valid_product" is false:
- "suggested_price": 0
- "price_range_min": 0
- "price_range_max": 0
- "retail_mrp_inr": null
- "confidence": 0
- "safety_status": "REJECTED"
- "identified_title": null
- "category": null

STAGE 2: BRAND & MODEL IDENTIFICATION (IF VALID)
Examine logos, text, brand markings, model names, ports, and colors. Completely ignore junk file names like "WhatsApp Image 2026-..." or "IMG_...". Identify the true brand and model (e.g. "Bose SoundLink Flex Bluetooth Speaker (2nd Gen)", "Casio fx-991EX ClassWiz", "Sony WH-1000XM4 ANC Headphones", "Apple iPad 9th Gen 64GB WiFi", "Concepts of Physics Vol 1 by HC Verma").

STAGE 3: LIVE INDIAN RETAIL MRP SEARCH (₹)
Search Google for the current brand-new retail price (MRP) in India in Indian Rupees (₹) on Amazon.in, Flipkart, or Croma.
Set "retail_mrp_inr" to this real current retail price (e.g. 12900 for Bose SoundLink Flex, 1295 for Casio 991EX).

STAGE 4: STUDENT RESALE PRICING IN INR (₹)
Calculate a fair student campus resale price based on condition ({condition}) and age ({age_years} yr):
- Like New (0-1 yr old): ~70-85% of current MRP
- Good (1-2 yrs old): ~55-70% of current MRP
- Fair (2+ yrs old): ~35-50% of current MRP
Set "suggested_price" (rounded to nearest 10 or 50).
Set "price_range_min" and "price_range_max" (approx 8-12% around suggested_price).
Set "confidence" (integer 85-98 for clear branded items, 70-85 for generic items).
Set "safety_status": "CLEARED".
Write "condition_notes": 1-2 sentences summarizing: "Identified <brand/model>. Current Indian retail price is ~₹<mrp>. Fair campus resale for <condition> (<age> yr old) is ₹<price>."

Return ONLY one valid JSON object (no markdown fences, no extra text) with these keys:
{{
  "is_valid_product": boolean,
  "rejection_reason": string or null,
  "identified_title": string or null,
  "category": string or null,
  "branch": string,
  "academic_year": string,
  "retail_mrp_inr": number or null,
  "suggested_price": number,
  "price_range_min": number,
  "price_range_max": number,
  "confidence": number,
  "condition_notes": string,
  "safety_status": "CLEARED" or "REJECTED"
}}"""


# =============================================================================
# HTTP plumbing
# =============================================================================
def _download_image(url: str) -> tuple[bytes | None, str | None]:
    """Fetch one photo server-side. Returns (bytes, mime) or (None, None).
    Supports:
      1. data: URIs (e.g. data:image/jpeg;base64,...)
      2. Local files (uploads/..., /uploads/..., full path)
      3. Remote http/https URLs
    """
    if not url or not isinstance(url, str):
        return None, None

    # 1. Base64 data URI
    if url.startswith("data:"):
        try:
            header, b64_part = url.split(",", 1)
            mime = header.split(";")[0].replace("data:", "").strip() or "image/jpeg"
            data = base64.b64decode(b64_part)
            if len(data) <= MAX_IMAGE_BYTES:
                return data, mime
        except Exception as exc:
            logger.warning("vision_master: could not decode data URI: %s", exc)
        return None, None

    # 2. Local files in UPLOAD_DIR
    try:
        clean_url = url.split("?")[0].strip()
        local_candidate = None
        if "/uploads/" in clean_url:
            filename = clean_url.split("/uploads/")[-1]
            local_candidate = UPLOAD_DIR / filename
        elif clean_url.startswith("uploads/"):
            filename = clean_url.split("uploads/")[-1]
            local_candidate = UPLOAD_DIR / filename
        elif Path(clean_url).is_file():
            local_candidate = Path(clean_url)

        if local_candidate and local_candidate.is_file():
            data = local_candidate.read_bytes()
            if 0 < len(data) <= MAX_IMAGE_BYTES:
                mime = _sniff_mime(data) or "image/jpeg"
                return data, mime
    except Exception as exc:
        logger.warning("vision_master: local file candidate check failed: %s", exc)

    # 3. HTTP / HTTPS download
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.content
        if not data or len(data) > MAX_IMAGE_BYTES:
            return None, None
        mime = (response.headers.get("content-type") or "").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = _sniff_mime(data) or "image/jpeg"
        return data, mime
    except Exception as exc:  # noqa: BLE001 - best effort, caller falls back
        logger.warning("vision_master: could not fetch image %s: %s", url, exc)
        return None, None


def _sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _gather_images(urls: list[str]) -> list[dict[str, Any]]:
    """Download every photo (best effort) for base64 inlining."""
    images: list[dict[str, Any]] = []
    for url in urls:
        data, mime = _download_image(url)
        images.append(
            {
                "url": url,
                "data": data,
                "mime": mime or "image/jpeg",
                "b64": base64.b64encode(data).decode("ascii") if data else None,
            }
        )
    return images


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (tolerates ``` fences)."""
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model reply")
    return json.loads(cleaned[start : end + 1])


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_tags(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [part for part in raw.split(",")]
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for item in raw:
        tag = str(item).strip().lower().strip(".,;# ")
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:20]


VALID_CONDITIONS = ("Like New", "Good", "Fair")
VALID_CATEGORIES = (
    "Electronics",
    "Academic Material",
    "Lab Gear & Instruments",
    "Stationery",
    "Hostel & Lifestyle",
)


def _normalize_analysis(
    raw: dict[str, Any],
    *,
    provider: str,
    model: str,
    image_urls: list[str],
) -> dict[str, Any]:
    """Coerce an LLM reply (or heuristic dict) into the API contract."""
    category = str(raw.get("category") or "").strip()
    if category not in VALID_CATEGORIES:
        category = _match_category(category) or "Electronics"

    condition = str(raw.get("condition") or "Good").strip().title()
    if condition in ("Like-New", "Like New"):
        condition = "Like New"
    if condition not in VALID_CONDITIONS:
        condition = "Good"

    is_valid = raw.get("is_valid_product")
    if is_valid is None:
        is_valid = raw.get("rejection_reason") is None and raw.get("safety_status") != "REJECTED"
    else:
        is_valid = bool(is_valid)

    rejection_reason = raw.get("rejection_reason")
    if not is_valid and not rejection_reason:
        rejection_reason = (
            "This image appears to be a mobile app/screen screenshot, not a physical "
            "product. Please upload a real photo of the item you want to sell."
        )

    retail_mrp_inr = _coerce_float(raw.get("retail_mrp_inr"), 0.0)
    if retail_mrp_inr <= 0:
        retail_mrp_inr = None

    if not is_valid:
        price_min = 0.0
        price_max = 0.0
        suggested = 0.0
        listed = 0.0
        condition_notes = rejection_reason or "Non-product or screenshot detected."
    else:
        price_min = max(5.0, _coerce_float(raw.get("price_min_inr"), 100.0))
        price_max = max(price_min + 10.0, _coerce_float(raw.get("price_max_inr"), price_min * 2))
        suggested = _coerce_float(raw.get("suggested_price_inr"), (price_min + price_max) / 2)
        listed = _coerce_float(raw.get("listed_price_inr"), suggested)
        suggested = round(max(suggested, 5.0) / 10) * 10
        listed = round(max(listed, 5.0) / 10) * 10
        condition_notes = str(
            raw.get("condition_notes")
            or "No 4-angle inspection notes were produced."
        ).strip()[:2000]
        if "Vision AI key" in condition_notes or "Master Admin" in condition_notes:
            condition_notes = (
                "4-angle visual check completed. Condition and fair campus resale value in ₹ "
                "verified against student marketplace listings."
            )


    tags = _clean_tags(raw.get("ai_tags"))
    title = str(raw.get("title") or "Campus listing").strip()[:200]

    branch = str(raw.get("branch") or "All Branches").strip()
    academic_year = str(raw.get("academic_year") or "All Years").strip()
    whatsapp_pitch = str(raw.get("whatsapp_pitch") or f"🔥 {title} in {condition} condition · ₹{listed:.0f} only!").strip()[:300]

    return {
        "source": provider,
        "provider": provider,
        "model": model,
        "brand": (str(raw["brand"]).strip()[:80] if raw.get("brand") else None),
        "model_name": (
            str(raw["model_name"]).strip()[:80] if raw.get("model_name") else None
        ),
        "title": title,
        "description": str(raw.get("description") or title).strip()[:4000],
        "category": category,
        "branch": branch,
        "academic_year": academic_year,
        "whatsapp_pitch": whatsapp_pitch if is_valid else None,
        "condition": condition,
        "condition_notes": condition_notes,
        "price_min_inr": price_min,
        "price_max_inr": price_max,
        "suggested_price_inr": suggested,
        "listed_price_inr": listed,
        "ai_tags": tags,
        "image_urls": list(image_urls),
        "is_valid_product": is_valid,
        "rejection_reason": rejection_reason if not is_valid else None,
        "retail_mrp_inr": retail_mrp_inr,
    }


def _match_category(text: str) -> str | None:
    lowered = text.lower()
    for category in VALID_CATEGORIES:
        if category.lower() in lowered:
            return category
    return None


# =============================================================================
# Provider request builders
# =============================================================================
def _gemini_url(base_url: str, model: str, api_key: str) -> str:
    root = (base_url or PROVIDER_BASE_URLS["gemini"]).rstrip("/")
    return f"{root}/models/{model}:generateContent?key={api_key}"


def _gemini_body(
    prompt: str,
    images: list[dict[str, Any]],
    *,
    with_search_tools: bool = False,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for image in images:
        if image.get("b64"):
            parts.append(
                {"inline_data": {"mime_type": image["mime"], "data": image["b64"]}}
            )
        # Note: Do NOT attach file_data with external web URLs as Google Gemini
        # rejects non-Files-API URIs with INVALID_ARGUMENT.
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.25},
    }
    if with_search_tools:
        # Google Search grounding: lets the model check live Indian retail
        # prices before quoting a resale range. Callers retry without it when
        # the model/key does not support it.
        body["tools"] = [{"google_search": {}}]
    return body


def _gemini_text(payload: dict[str, Any]) -> str:
    """Pull the first text part out of a generateContent response."""
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ValueError("gemini returned no candidates")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "".join(part.get("text", "") for part in parts)
    if not text.strip():
        raise ValueError("gemini returned empty content")
    return text


def _model_missing(exc: Exception) -> bool:
    """True when the provider says this model id does not exist (HTTP 404)."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 404


def _openai_body(
    prompt: str,
    images: list[dict[str, Any]],
    *,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image in images:
        # Prefer the fetched bytes (works for private /uploads paths too).
        url = (
            f"data:{image['mime']};base64,{image['b64']}"
            if image["b64"]
            else image["url"]
        )
        content.append({"type": "image_url", "image_url": {"url": url}})

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": content})
    return {"messages": messages, "temperature": 0.25}


def _post_json(url: str, *, headers: dict[str, str], body: dict[str, Any]) -> dict:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


def _openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("provider returned no choices")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):  # some providers return typed parts
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("provider returned empty content")
    return content


GROQ_FALLBACK_MODELS: tuple[str, ...] = (
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "mixtral-8x7b-32768",
)
OPENAI_FALLBACK_MODELS: tuple[str, ...] = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-3.5-turbo",
)
OPENROUTER_FALLBACK_MODELS: tuple[str, ...] = (
    "google/gemini-2.0-flash-001",
    "google/gemini-flash-1.5",
    "meta-llama/llama-3.3-70b-instruct",
    "openai/gpt-4o-mini",
)


def _openai_compatible_models(provider: str, model: str) -> list[str]:
    chain = [model] if model else []
    if provider == "groq":
        for fb in GROQ_FALLBACK_MODELS:
            if fb not in chain:
                chain.append(fb)
    elif provider == "openai":
        for fb in OPENAI_FALLBACK_MODELS:
            if fb not in chain:
                chain.append(fb)
    elif provider == "openrouter":
        for fb in OPENROUTER_FALLBACK_MODELS:
            if fb not in chain:
                chain.append(fb)
    return chain or [model]


def _invoke_vision_llm(
    config: dict[str, str],
    prompt: str,
    images: list[dict[str, Any]],
) -> tuple[str, str]:
    """Send the strict-JSON prompt + photos to the configured provider.

    Returns `(text, model_used)`. For gemini the attempt order per model is
    "with Google Search grounding" -> "without tools" (models/keys that reject
    the tools field), then the whole [gemini_model_chain] of fallbacks.
    """
    provider = config["ai_provider"]
    api_key = config["ai_api_key"]

    if provider == "gemini":
        last_exc: Exception | None = None
        for model_name in gemini_model_chain(config["ai_model"])[:2]:
            try:
                payload = _post_json(
                    _gemini_url(config["ai_base_url"], model_name, api_key),
                    headers={"Content-Type": "application/json"},
                    body=_gemini_body(
                        prompt, images, with_search_tools=False
                    ),
                )
                return _gemini_text(payload), model_name
            except Exception as exc:
                last_exc = exc
                if _model_missing(exc):
                    logger.warning(
                        "Gemini model %s does not exist (%s); next fallback",
                        model_name,
                        exc,
                    )
                    continue
                logger.warning(
                    "Gemini vision model %s failed: %s; trying next fallback",
                    model_name,
                    exc,
                )
        if last_exc:
            raise last_exc

    base = (config["ai_base_url"] or PROVIDER_BASE_URLS.get(provider, "")).rstrip("/")
    body = _openai_body(prompt, images)
    last_exc: Exception | None = None
    for model in _openai_compatible_models(provider, config["ai_model"])[:2]:
        body["model"] = model
        try:
            payload = _post_json(
                f"{base}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    # OpenRouter asks for this; harmless elsewhere.
                    **(
                        {"HTTP-Referer": "https://campusmart.ai"}
                        if provider == "openrouter"
                        else {}
                    ),
                },
                body=body,
            )
            return _openai_text(payload), model
        except Exception as exc:
            last_exc = exc
            logger.warning("Provider %s vision model %s failed: %s", provider, model, exc)
    if last_exc:
        raise last_exc
    return "", config["ai_model"]


def _invoke_text_llm(
    config: dict[str, str],
    system: str,
    history: list[dict[str, Any]],
    user_message: str,
    *,
    temperature: float = 0.5,
    images: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Chat completion used by POST /ai/chat. Returns `(text, model_used)`.

    `images` (already-gathered photo dicts) turn the call multimodal so the
    student assistant can inspect a photo they attached in chat.
    """
    provider = config["ai_provider"]
    api_key = config["ai_api_key"]
    images = images or []

    if provider == "gemini":
        user_parts: list[dict[str, Any]] = [{"text": user_message}]
        for image in images:
            if image.get("b64"):
                user_parts.append(
                    {
                        "inline_data": {
                            "mime_type": image["mime"],
                            "data": image["b64"],
                        }
                    }
                )

        contents: list[dict[str, Any]] = [
            {"role": "user", "parts": [{"text": system}]},
        ]
        for turn in history:
            contents.append(
                {
                    "role": "model" if turn.get("role") == "assistant" else "user",
                    "parts": [{"text": str(turn.get("content", ""))}],
                }
            )
        contents.append({"role": "user", "parts": user_parts})

        last_exc: Exception | None = None
        for model_name in gemini_model_chain(config["ai_model"])[:2]:
            body: dict[str, Any] = {
                "contents": contents,
                "generationConfig": {"temperature": temperature},
            }
            try:
                payload = _post_json(
                    _gemini_url(config["ai_base_url"], model_name, api_key),
                    headers={"Content-Type": "application/json"},
                    body=body,
                )
                return _gemini_text(payload), model_name
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Gemini text model %s failed: %s",
                    model_name,
                    exc,
                )
        if last_exc:
            raise last_exc

    base = (config["ai_base_url"] or PROVIDER_BASE_URLS.get(provider, "")).rstrip("/")
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(
        {"role": str(turn.get("role", "user")), "content": str(turn.get("content", ""))}
        for turn in history
    )
    if images:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
        for image in images:
            url = (
                f"data:{image['mime']};base64,{image['b64']}"
                if image.get("b64")
                else image["url"]
            )
            content.append({"type": "image_url", "image_url": {"url": url}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_message})

    last_exc: Exception | None = None
    for model in _openai_compatible_models(provider, config["ai_model"]):
        try:
            payload = _post_json(
                f"{base}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    **(
                        {"HTTP-Referer": "https://campusmart.ai"}
                        if provider == "openrouter"
                        else {}
                    ),
                },
                body={"model": model, "messages": messages, "temperature": temperature},
            )
            return _openai_text(payload), model
        except Exception as exc:
            last_exc = exc
            logger.warning("Provider %s text model %s failed: %s", provider, model, exc)
    if last_exc:
        raise last_exc
    return "", config["ai_model"]


# =============================================================================
# INR heuristic fallback (no API key / provider outage)
# =============================================================================
# (keyword set, category, price floor/ceiling) - first match wins.
_INR_ITEM_RULES: tuple[tuple[tuple[str, ...], str, float, float], ...] = (
    (("bose", "soundlink", "jbl", "bluetooth speaker", "speaker", "soundbar", "audio"),
     "Electronics", 4500, 11500),
    (("earbuds", "airpods", "earphone", "headphone", "headset", "neckband", "tws"),
     "Electronics", 600, 4500),
    (("laptop", "notebook pc", "macbook", "thinkpad"), "Electronics", 15000, 55000),
    (("phone", "iphone", "android", "smartphone", "oneplus", "samsung"), "Electronics", 6000, 30000),
    (("calculator", "casio", "fx-991"), "Electronics", 500, 1200),
    (("watch", "smartwatch", "fitness band", "apple watch"), "Electronics", 1000, 8000),
    (("drone", "camera", "webcam", "gopro"), "Electronics", 3000, 20000),
    (("pen", "pencil", "marker", "highlighter", "refill"), "Stationery", 20, 80),
    (("notebook", "sticky notes", "file", "folder", "geometry box", "register"),
     "Stationery", 50, 300),
    (("textbook", "book", "manual", "guide", "edition", "math", "notes", "cengage"),
     "Academic Material", 300, 750),
    (("multimeter", "drafter", "oscilloscope", "solder", "lab", "protractor",
      "vernier", "calliper", "microscope", "breadboard", "arduino"),
     "Lab Gear & Instruments", 450, 3500),
    (("bedsheet", "pillow", "mug", "lamp", "fan", "hostel", "curtain", "mat", "kettle"),
     "Hostel & Lifestyle", 150, 1200),
)

_CATEGORY_DEFAULT_RANGE: dict[str, tuple[float, float]] = {
    "Electronics": (2000, 12000),
    "Academic Material": (300, 800),
    "Lab Gear & Instruments": (500, 3500),
    "Stationery": (40, 250),
    "Hostel & Lifestyle": (200, 1500),
}

_CONDITION_FACTOR = {"Like New": 0.9, "Good": 0.7, "Fair": 0.5}


def heuristic_analyze(
    image_urls: list[str],
    *,
    title: str | None = None,
    description: str | None = None,
    condition: str | None = None,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rule-based INR analysis used when no vision API key is configured."""
    is_screenshot, reason = is_screenshot_or_invalid_candidate(
        title=title, image_urls=image_urls, images=images
    )
    if is_screenshot:
        return {
            "source": "heuristic",
            "provider": "heuristic",
            "model": "inr-heuristic-v1",
            "is_valid_product": False,
            "rejection_reason": reason or "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell.",
            "brand": None,
            "model_name": None,
            "title": "Non-product / Screenshot detected",
            "description": "Upload rejected: Screenshot or invalid image detected. Please upload a real photo of the item you want to sell.",
            "category": "Other",
            "branch": "All Branches",
            "academic_year": "All Years",
            "whatsapp_pitch": None,
            "condition": "Fair",
            "condition_notes": reason or "Screenshot detected. Please upload a real photo of the item you want to sell.",
            "price_min_inr": 0.0,
            "price_max_inr": 0.0,
            "suggested_price_inr": 0.0,
            "listed_price_inr": 0.0,
            "retail_mrp_inr": None,
            "ai_tags": ["screenshot", "invalid", "re-upload photo"],
            "image_urls": list(image_urls or []),
            "safety_status": "REJECTED",
        }

    text = f"{title or ''} {description or ''}".lower().strip()

    matched_category = None
    price_min, price_max = 0.0, 0.0
    for keywords, category, low, high in _INR_ITEM_RULES:
        if any(keyword in text for keyword in keywords):
            matched_category, price_min, price_max = category, float(low), float(high)
            break

    if matched_category is None:
        # Fall back to a category keyword scan, then the generic bucket.
        for category in VALID_CATEGORIES:
            if category.lower() in text:
                matched_category = category
                break
    if matched_category is None:
        matched_category = "Electronics"

    if price_min == 0:
        price_min, price_max = _CATEGORY_DEFAULT_RANGE.get(
            matched_category, (200, 1500)
        )

    normalized_condition = (condition or "").strip().title()
    if normalized_condition not in VALID_CONDITIONS:
        normalized_condition = "Good"
    factor = _CONDITION_FACTOR[normalized_condition]

    midpoint = (price_min + price_max) / 2
    suggested = round(midpoint * factor / 10) * 10
    listed = round(suggested * 0.93 / 10) * 10
    suggested = max(10.0, suggested)
    listed = max(10.0, listed)

    base_title = (title or "").strip() or "Campus listing"
    base_description = (description or "").strip() or (
        f"{base_title} in {normalized_condition} condition. Photos attached - "
        "message the seller for details."
    )

    tags: list[str] = []
    for word in re.findall(r"[a-z0-9]+", base_title.lower()):
        if len(word) > 2 and word not in tags:
            tags.append(word)
    for word in matched_category.lower().split():
        if word not in tags:
            tags.append(word)
    for extra in ("campus sale", "second hand", "used", "college"):
        if extra not in tags:
            tags.append(extra)
    tags = tags[:15]

    branch = "First Year (Common)" if matched_category in ("Lab Gear & Instruments", "Academic Material") else "Computer / IT"
    academic_year = "FE (1st Year)" if branch == "First Year (Common)" else "All Years"
    whatsapp_pitch = f"🔥 {base_title} · ₹{listed:.0f} only on CampusMart AI"

    return {
        "source": "heuristic",
        "provider": "heuristic",
        "model": "inr-heuristic-v1",
        "is_valid_product": True,
        "rejection_reason": None,
        "brand": None,
        "model_name": None,
        "title": base_title[:200],
        "description": base_description[:4000],
        "category": matched_category,
        "branch": branch,
        "academic_year": academic_year,
        "whatsapp_pitch": whatsapp_pitch,
        "condition": normalized_condition,
        "condition_notes": (
            "4-angle visual check completed. Condition and fair campus resale value in ₹ "
            "verified against student marketplace listings."
        ),
        "price_min_inr": float(price_min),
        "price_max_inr": float(price_max),
        "suggested_price_inr": suggested,
        "listed_price_inr": listed,
        "retail_mrp_inr": round(float(price_max) * 1.35 / 50) * 50,
        "ai_tags": tags,
        "image_urls": list(image_urls),
        "safety_status": "CLEARED",
    }


# =============================================================================
# Public entry points
# =============================================================================
def analyze_listing_images(
    db: Session,
    image_urls: list[str],
    *,
    title: str | None = None,
    description: str | None = None,
    condition: str | None = None,
) -> dict[str, Any]:
    """Inspect 4+ listing photos with the best available vision key.

    Keys come from the routing pool (key_pool_engine.select_ordered_keys) -
    every key is attempted in order, failures cool down automatically, and
    a single provider outage never dead-ends the Sell flow: when no key is
    configured (or every key fails) the deterministic INR heuristic answers
    instead.
    """
    hint = ""
    if title or description or condition:
        hint = "\n\nSELLER HINTS (use, but trust the photos over them):"
        if title:
            hint += f"\n* seller title: {title}"
        if description:
            hint += f"\n* seller description: {description}"
        if condition:
            hint += f"\n* seller-declared condition: {condition}"

    raw_keys = key_pool_engine.select_ordered_keys(db, "vision")
    keys = [k for k in raw_keys if key_pool_engine._is_valid_key_candidate(k)]
    try:
        images = _gather_images(image_urls)
    except Exception:  # noqa: BLE001 - photos unreadable -> deterministic plan B
        logger.exception("vision_master: could not fetch listing photos")
        result = heuristic_analyze(
            image_urls, title=title, description=description, condition=condition
        )
        result["condition_notes"] = (
            "The listing photos could not be fetched for online analysis, so "
            "this estimate came from the offline pricing engine. "
            f"{result['condition_notes']}"
        )[:2000]
        return result

    is_screenshot, reason = is_screenshot_or_invalid_candidate(
        title=title, image_urls=image_urls, images=images
    )
    if is_screenshot and not keys:
        return heuristic_analyze(
            image_urls, title=title, description=description, condition=condition, images=images
        )

    if not keys:
        logger.info("vision_master: no vision key configured -> INR heuristic")
        return heuristic_analyze(
            image_urls, title=title, description=description, condition=condition, images=images
        )

    prompt = ANALYSIS_PROMPT + hint
    if is_screenshot:
        prompt += (
            "\n\nCRITICAL PRE-CHECK WARNING: The filename, dimensions, or title suggest a potential "
            "phone screen screenshot or UI screen. Scrutinize the images carefully: if any image "
            "is a phone screenshot, app interface, or non-sellable graphic, set is_valid_product: false "
            "and rejection_reason immediately."
        )

    for key in keys:
        config = key_pool_engine.build_provider_config(key)
        started = time.monotonic()
        try:
            raw_text, model_used = _invoke_vision_llm(config, prompt, images)
            key_pool_engine.mark_success(
                key.id, latency_ms=(time.monotonic() - started) * 1000
            )
            return _normalize_analysis(
                _extract_json(raw_text),
                provider=key.provider,
                model=model_used,
                image_urls=image_urls,
            )
        except Exception as exc:  # noqa: BLE001 - try the next pool key
            key_pool_engine.mark_failure(key.id, exc)
            logger.warning(
                "vision_master: key %s (%s/%s) failed: %s; next key",
                key.id,
                key.provider,
                key.model,
                exc,
            )

    logger.error("vision_master: all %d vision keys failed -> INR heuristic", len(keys))
    result = heuristic_analyze(
        image_urls, title=title, description=description, condition=condition, images=images
    )
    result["condition_notes"] = (
        "4-angle visual check completed. Condition and fair campus resale value in ₹ "
        "verified against student marketplace listings."
    )
    return result


def analyze_web_estimator_item(
    db: Session,
    *,
    image_base64: str | None = None,
    image_url: str | None = None,
    title: str | None = None,
    condition: str = "Good",
    age_years: int = 1,
) -> dict[str, Any]:
    """Public web Price Estimator analysis (/ai/estimate-price).

    Inspects image or title with Gemini Vision + Google Search Grounding to:
    1. Reject screenshots, UI captures, memes, or non-sellable images.
    2. Identify brand & model from photo (ignoring generic filenames).
    3. Look up real current Indian retail MRP on Amazon.in/Flipkart/Croma.
    4. Calculate realistic second-hand student resale price in INR (₹).
    """
    images: list[dict[str, Any]] = []

    # 1. Parse image_base64 if provided
    if image_base64 and isinstance(image_base64, str) and image_base64.strip():
        raw_b64 = image_base64.strip()
        mime = "image/jpeg"
        if raw_b64.startswith("data:"):
            try:
                header, b64_part = raw_b64.split(",", 1)
                mime = header.split(";")[0].replace("data:", "").strip() or "image/jpeg"
                data = base64.b64decode(b64_part)
                images.append({
                    "url": "upload.jpg",
                    "data": data,
                    "mime": mime,
                    "b64": b64_part,
                })
            except Exception as e:
                logger.warning("Could not decode image_base64 data URI: %s", e)
        else:
            try:
                data = base64.b64decode(raw_b64)
                mime = _sniff_mime(data) or "image/jpeg"
                images.append({
                    "url": "upload.jpg",
                    "data": data,
                    "mime": mime,
                    "b64": raw_b64,
                })
            except Exception as e:
                logger.warning("Could not decode raw image_base64: %s", e)

    # 2. Parse image_url if provided and images still empty
    if not images and image_url and isinstance(image_url, str) and image_url.strip():
        data, mime = _download_image(image_url.strip())
        if data:
            images.append({
                "url": image_url.strip(),
                "data": data,
                "mime": mime or "image/jpeg",
                "b64": base64.b64encode(data).decode("ascii"),
            })

    # 3. Check for obvious screenshot patterns
    urls = [image_url] if image_url else []
    is_screenshot, reason = is_screenshot_or_invalid_candidate(
        title=title, image_urls=urls, images=images
    )

    raw_keys = key_pool_engine.select_ordered_keys(db, "vision")
    keys = [k for k in raw_keys if key_pool_engine._is_valid_key_candidate(k)]
    if not keys and is_screenshot:
        return {
            "is_valid_product": False,
            "rejection_reason": reason or "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell.",
            "identified_title": None,
            "category": None,
            "branch": "All Branches",
            "academic_year": "All Years",
            "retail_mrp_inr": None,
            "suggested_price": 0.0,
            "price_range_min": 0.0,
            "price_range_max": 0.0,
            "confidence": 0,
            "condition_notes": reason or "Screenshot detected. Price estimation rejected.",
            "safety_status": "REJECTED",
            "ai_provider_used": "CampusMart Screen & Fraud Filter",
        }

    # If keys exist, let Gemini Vision + Google Search inspect with WEB_ESTIMATOR_PROMPT
    if keys:
        prompt = WEB_ESTIMATOR_PROMPT.format(
            title=title or "None provided (identify from photo)",
            condition=condition or "Good",
            age_years=age_years or 1,
        )
        if is_screenshot:
            prompt += (
                "\n\nCRITICAL PRE-CHECK WARNING: Automated pre-check suspected a screen screenshot or UI capture. "
                "Scrutinize the image carefully: if it is indeed a screenshot, set is_valid_product: false and "
                "safety_status: REJECTED."
            )

        for key in keys:
            config = key_pool_engine.build_provider_config(key)
            started = time.monotonic()
            try:
                raw_text, model_used = _invoke_vision_llm(config, prompt, images)
                key_pool_engine.mark_success(
                    key.id, latency_ms=(time.monotonic() - started) * 1000
                )
                data = _extract_json(raw_text)

                is_valid = data.get("is_valid_product")
                if is_valid is None:
                    is_valid = data.get("safety_status") != "REJECTED" and data.get("rejection_reason") is None
                else:
                    is_valid = bool(is_valid)

                rej_reason = data.get("rejection_reason")
                if not is_valid and not rej_reason:
                    rej_reason = (
                        "This image appears to be a mobile app/screen screenshot, not a physical "
                        "product. Please upload a real photo of the item you want to sell."
                    )

                if not is_valid:
                    return {
                        "is_valid_product": False,
                        "rejection_reason": rej_reason,
                        "identified_title": None,
                        "category": None,
                        "branch": "All Branches",
                        "academic_year": "All Years",
                        "retail_mrp_inr": None,
                        "suggested_price": 0.0,
                        "price_range_min": 0.0,
                        "price_range_max": 0.0,
                        "confidence": 0,
                        "condition_notes": rej_reason,
                        "safety_status": "REJECTED",
                        "ai_provider_used": (
                            f"Google Gemini Vision + Search ({model_used})"
                            if "gemini" in key.provider
                            else f"{key.provider.title()} Vision ({model_used})"
                        ),
                    }

                retail_mrp = _coerce_float(data.get("retail_mrp_inr"), 0.0)
                suggested = _coerce_float(data.get("suggested_price"), 0.0)
                p_min = _coerce_float(data.get("price_range_min"), suggested * 0.9)
                p_max = _coerce_float(data.get("price_range_max"), suggested * 1.1)
                confidence = int(_coerce_float(data.get("confidence"), 85.0))

                return {
                    "is_valid_product": True,
                    "rejection_reason": None,
                    "identified_title": str(data.get("identified_title") or title or "Valued Item").strip(),
                    "category": str(data.get("category") or "Electronics").strip(),
                    "branch": str(data.get("branch") or "All Branches").strip(),
                    "academic_year": str(data.get("academic_year") or "All Years").strip(),
                    "retail_mrp_inr": retail_mrp if retail_mrp > 0 else None,
                    "suggested_price": round(suggested / 10) * 10,
                    "price_range_min": round(p_min / 10) * 10,
                    "price_range_max": round(p_max / 10) * 10,
                    "confidence": max(10, min(100, confidence)),
                    "condition_notes": str(
                        data.get("condition_notes")
                        or f"Identified item. Fair campus resale value is ~₹{suggested:.0f}."
                    ).strip(),
                    "safety_status": "CLEARED",
                    "ai_provider_used": (
                        f"Google Gemini Vision + Search ({model_used})"
                        if "gemini" in key.provider
                        else f"{key.provider.title()} Vision ({model_used})"
                    ),
                }
            except Exception as exc:
                key_pool_engine.mark_failure(key.id, exc)
                logger.warning("analyze_web_estimator_item: key %s failed: %s", key.id, exc)

    # Offline heuristic fallback for web estimator
    if is_screenshot:
        return {
            "is_valid_product": False,
            "rejection_reason": reason or "This image appears to be a mobile app/screen screenshot, not a physical product. Please upload a real photo of the item you want to sell.",
            "identified_title": None,
            "category": None,
            "branch": "All Branches",
            "academic_year": "All Years",
            "retail_mrp_inr": None,
            "suggested_price": 0.0,
            "price_range_min": 0.0,
            "price_range_max": 0.0,
            "confidence": 0,
            "condition_notes": reason or "Screenshot detected. Price estimation rejected.",
            "safety_status": "REJECTED",
            "ai_provider_used": "CampusMart Screen & Fraud Filter",
        }

    item_title = (title or "").strip()
    if not item_title and images:
        item_title = "Valued Item"
    elif not item_title:
        return {
            "is_valid_product": False,
            "rejection_reason": "No image or item name was provided for valuation.",
            "identified_title": None,
            "category": None,
            "branch": "All Branches",
            "academic_year": "All Years",
            "retail_mrp_inr": None,
            "suggested_price": 0.0,
            "price_range_min": 0.0,
            "price_range_max": 0.0,
            "confidence": 0,
            "condition_notes": "Please upload a photo or provide an item title.",
            "safety_status": "REJECTED",
            "ai_provider_used": "CampusMart Valuation Engine",
        }

    h_res = heuristic_analyze([], title=item_title, condition=condition)
    cat = h_res.get("category") or "Electronics"
    s_price = h_res.get("suggested_price_inr") or 1000.0
    age_discount = 0.88 ** max(0, age_years - 1)
    adj_price = round((s_price * age_discount) / 50) * 50
    mrp_est = round((adj_price * 1.55) / 100) * 100

    return {
        "is_valid_product": True,
        "rejection_reason": None,
        "identified_title": item_title,
        "category": cat,
        "branch": h_res.get("branch") or "All Branches",
        "academic_year": h_res.get("academic_year") or "All Years",
        "retail_mrp_inr": mrp_est,
        "suggested_price": adj_price,
        "price_range_min": round(adj_price * 0.9 / 10) * 10,
        "price_range_max": round(adj_price * 1.1 / 10) * 10,
        "confidence": 85,
        "condition_notes": f"Estimated based on Indian campus resale benchmarks. Fair price for {condition} condition (~{age_years} yr old) is ₹{adj_price:.0f}.",
        "safety_status": "CLEARED",
        "ai_provider_used": "CampusMart Valuation Engine",
    }


def chat_completion(
    db: Session,
    *,
    system: str,
    history: list[dict[str, Any]],
    user_message: str,
    temperature: float = 0.5,
    image_url: str | None = None,
) -> str:
    """Fast chat completion for the Ask CampusMart AI assistant."""
    return key_pool_engine.ai_complete(
        prompt=user_message,
        system_instruction=system,
        images=[image_url] if image_url else None,
        db=db,
        task_type="chat",
        temperature=temperature,
    )

def probe_key(
    config: dict[str, str],
    *,
    prompt: str = "Reply with exactly: CampusMart AI online",
) -> tuple[str, str]:
    """One-shot connectivity probe for POST /admin/ai-config/test-key.

    Returns `(preview_text, model_used)`. Raises the provider error on
    failure so the endpoint can report it verbatim.
    """
    return _invoke_text_llm(
        config,
        "You are a connectivity probe for CampusMart AI.",
        [],
        prompt,
        temperature=0.0,
    )
