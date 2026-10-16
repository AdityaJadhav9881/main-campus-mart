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
PUT /admin/ai-config - NO redeploy needed):

    gemini      Google  generativelanguage.googleapis.com  (inline base64 parts)
    openai      OpenAI  api.openai.com/v1                  (data-URI image_url)
    groq        Groq    api.groq.com/openai/v1             (OpenAI-compatible)
    openrouter  OpenRouter openrouter.ai/api/v1            (OpenAI-compatible)

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
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..models import SystemConfig
from ..storage import UPLOAD_DIR

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Provider registry
# -----------------------------------------------------------------------------
PROVIDERS: tuple[str, ...] = ("gemini", "openai", "groq", "openrouter")

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-3.5-flash"

# Official default endpoints; PUT /admin/ai-config's `ai_base_url` overrides.
PROVIDER_BASE_URLS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Per-request network budget. Vision calls move real bytes, so this is more
# generous than a plain API timeout (Render cold starts included).
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
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
# Strict-JSON vision prompt
# =============================================================================
_CATEGORY_LIST = (
    "'Electronics', 'Academic Material', 'Lab Gear & Instruments', "
    "'Stationery', 'Hostel & Lifestyle'"
)

ANALYSIS_PROMPT = f"""You are the listing-intelligence engine of Campus Mart Ai, an Indian \
college second-hand marketplace. You receive 4+ photos of one item taken from different \
angles: Front, Back, Side, and a Close-up/Label shot. Study EVERY photo before answering.

Carefully examine all 4 photos and perform deep catalog and brand matching. Read brand names, \
model numbers, serial numbers, labels, engravings, and ports (e.g. recognizing "Bose SoundLink Flex", \
"Casio fx-991EX ClassWiz", "Sony WH-1000XM4", "Logitech MX Master", "Apple MacBook Air M1", \
"HC Verma Concepts of Physics", "SanDisk Ultra 64GB", "Arduino Uno R3", etc.). \
Judge physical wear, scratches, scuffs, dents, and functionality indicators from all angles, and \
calculate accurate realistic resale market prices in Indian Rupees (₹).

Return ONLY one JSON object (no markdown, no commentary, no code fences) with exactly these keys:
{{
  "brand": string or null          - exact brand visible (e.g. "Bose", "Casio", "Apple", "Classmate")
  "model_name": string or null     - exact model/variant (e.g. "SoundLink Flex", "fx-991CW", "AirPods Pro")
  "title": string                  - compelling, accurate marketplace title with brand & model, <= 120 chars
  "description": string            - 2-4 professional, honest sentences: exact specs, condition, included accessories
  "category": string               - exactly one of {_CATEGORY_LIST}
  "condition": string              - exactly one of "Like New", "Good", "Fair"
  "condition_notes": string        - detailed 4-angle inspection summary: front/back/side/label wear,
                                     scratches, dents, button/port condition, accessories/box
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
  * Condition scaling: Like New ~= 85-90% of used fair market, Good ~= 70-75%, Fair ~= 50-60%.

QUALITY RULES:
  * Extract exact brand and model when text or logos are visible in any photo angle.
  * ai_tags must include brand, model, synonyms, and practical college search queries.
  * Return strict valid JSON only."""


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

    price_min = max(5.0, _coerce_float(raw.get("price_min_inr"), 100.0))
    price_max = max(price_min + 10.0, _coerce_float(raw.get("price_max_inr"), price_min * 2))
    suggested = _coerce_float(raw.get("suggested_price_inr"), (price_min + price_max) / 2)
    listed = _coerce_float(raw.get("listed_price_inr"), suggested)
    suggested = round(max(suggested, 5.0) / 10) * 10
    listed = round(max(listed, 5.0) / 10) * 10

    tags = _clean_tags(raw.get("ai_tags"))
    title = str(raw.get("title") or "Campus listing").strip()[:200]

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
        "condition": condition,
        "condition_notes": str(
            raw.get("condition_notes")
            or "No 4-angle inspection notes were produced."
        ).strip()[:2000],
        "price_min_inr": price_min,
        "price_max_inr": price_max,
        "suggested_price_inr": suggested,
        "listed_price_inr": listed,
        "ai_tags": tags,
        "image_urls": list(image_urls),
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


def _gemini_body(prompt: str, images: list[dict[str, Any]]) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for image in images:
        if image.get("b64"):
            parts.append(
                {"inline_data": {"mime_type": image["mime"], "data": image["b64"]}}
            )
        # Note: Do NOT attach file_data with external web URLs as Google Gemini
        # rejects non-Files-API URIs with INVALID_ARGUMENT.
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.25},
    }


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


def _invoke_vision_llm(
    config: dict[str, str],
    prompt: str,
    images: list[dict[str, Any]],
) -> str:
    """Send the strict-JSON prompt + photos to the configured provider."""
    provider = config["ai_provider"]
    model = config["ai_model"]
    api_key = config["ai_api_key"]

    if provider == "gemini":
        gemini_models: list[str] = []
        for candidate in [model, "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]:
            if candidate and candidate not in gemini_models:
                gemini_models.append(candidate)

        last_exc: Exception | None = None
        for m in gemini_models:
            try:
                payload = _post_json(
                    _gemini_url(config["ai_base_url"], m, api_key),
                    headers={"Content-Type": "application/json"},
                    body=_gemini_body(prompt, images),
                )
                candidates = payload.get("candidates") or []
                if not candidates:
                    raise ValueError(f"gemini ({m}) returned no candidates")
                parts = ((candidates[0].get("content") or {}).get("parts")) or []
                text = "".join(part.get("text", "") for part in parts)
                if not text.strip():
                    raise ValueError(f"gemini ({m}) returned empty content")
                return text
            except Exception as exc:
                last_exc = exc
                logger.warning("Gemini vision model %s failed: %s; trying next fallback", m, exc)
                continue
        if last_exc:
            raise last_exc

    base = (config["ai_base_url"] or PROVIDER_BASE_URLS[provider]).rstrip("/")
    body = _openai_body(prompt, images)
    body["model"] = model
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
    return _openai_text(payload)


def _invoke_text_llm(
    config: dict[str, str],
    system: str,
    history: list[dict[str, Any]],
    user_message: str,
    *,
    temperature: float = 0.5,
) -> str:
    """Text-only completion used by POST /ai/chat."""
    provider = config["ai_provider"]
    model = config["ai_model"]
    api_key = config["ai_api_key"]

    if provider == "gemini":
        gemini_models: list[str] = []
        for candidate in [model, "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]:
            if candidate and candidate not in gemini_models:
                gemini_models.append(candidate)

        contents = [
            {"role": "user", "parts": [{"text": system}]},
        ]
        for turn in history:
            contents.append(
                {
                    "role": "model" if turn.get("role") == "assistant" else "user",
                    "parts": [{"text": str(turn.get("content", ""))}],
                }
            )
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        last_exc: Exception | None = None
        for m in gemini_models:
            try:
                payload = _post_json(
                    _gemini_url(config["ai_base_url"], m, api_key),
                    headers={"Content-Type": "application/json"},
                    body={
                        "contents": contents,
                        "generationConfig": {"temperature": temperature},
                    },
                )
                candidates = payload.get("candidates") or []
                parts = ((candidates[0].get("content") or {}).get("parts")) or [] if candidates else []
                text = "".join(part.get("text", "") for part in parts)
                if not text.strip():
                    raise ValueError(f"gemini ({m}) returned empty content")
                return text
            except Exception as exc:
                last_exc = exc
                logger.warning("Gemini text model %s failed: %s; trying next fallback", m, exc)
                continue
        if last_exc:
            raise last_exc

    base = (config["ai_base_url"] or PROVIDER_BASE_URLS[provider]).rstrip("/")
    messages = [{"role": "system", "content": system}]
    messages.extend(
        {"role": str(turn.get("role", "user")), "content": str(turn.get("content", ""))}
        for turn in history
    )
    messages.append({"role": "user", "content": user_message})
    payload = _post_json(
        f"{base}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        body={"model": model, "messages": messages, "temperature": temperature},
    )
    return _openai_text(payload)


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
) -> dict[str, Any]:
    """Rule-based INR analysis used when no vision API key is configured.

    Deliberately honest in `condition_notes`: it tells the seller the 4-angle
    AI inspection will switch on once the Master Admin saves a key.
    """
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

    return {
        "source": "heuristic",
        "provider": "heuristic",
        "model": "inr-heuristic-v1",
        "brand": None,
        "model_name": None,
        "title": base_title[:200],
        "description": base_description[:4000],
        "category": matched_category,
        "condition": normalized_condition,
        "condition_notes": (
            f"Heuristic INR estimate from {len(image_urls)} photo(s): "
            f"{matched_category}, condition '{normalized_condition}'. Configure a "
            "Vision AI key (Master Admin -> AI Config) for the full 4-angle "
            "wear inspection, brand/model detection and exact pricing."
        )[:2000],
        "price_min_inr": float(price_min),
        "price_max_inr": float(price_max),
        "suggested_price_inr": suggested,
        "listed_price_inr": listed,
        "ai_tags": tags,
        "image_urls": list(image_urls),
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
    """Inspect 4+ listing photos with the configured vision model.

    Falls back to [heuristic_analyze] when no API key is stored yet, and also
    when the provider errors (logged) - the Sell flow always gets a usable
    INR answer instead of a 500.
    """
    config = get_ai_config(db)

    if not config["ai_api_key"]:
        logger.info("vision_master: no API key configured -> INR heuristic")
        return heuristic_analyze(
            image_urls, title=title, description=description, condition=condition
        )

    prompt = ANALYSIS_PROMPT
    if title or description or condition:
        hint = "\n\nSELLER HINTS (use, but trust the photos over them):"
        if title:
            hint += f"\n* seller title: {title}"
        if description:
            hint += f"\n* seller description: {description}"
        if condition:
            hint += f"\n* seller-declared condition: {condition}"
        prompt += hint

    try:
        images = _gather_images(image_urls)
        raw_text = _invoke_vision_llm(config, prompt, images)
        raw = _extract_json(raw_text)
        return _normalize_analysis(
            raw,
            provider=config["ai_provider"],
            model=config["ai_model"],
            image_urls=image_urls,
        )
    except Exception as exc:  # noqa: BLE001 - upstream -> deterministic fallback
        logger.exception(
            "vision_master: %s vision call failed; using INR heuristic",
            config["ai_provider"],
        )
        result = heuristic_analyze(
            image_urls, title=title, description=description, condition=condition
        )
        result["condition_notes"] = (
            f"{config['ai_provider']} vision error ({exc.__class__.__name__}); "
            f"{result['condition_notes']}"
        )[:2000]
        return result


def chat_completion(
    db: Session,
    *,
    system: str,
    history: list[dict[str, Any]],
    user_message: str,
    temperature: float = 0.5,
) -> str:
    """Text completion for the Ask CampusMart AI assistant.

    Raises when no key is configured or the provider fails - callers fall back
    to the local catalog assistant.
    """
    config = get_ai_config(db)
    if not config["ai_api_key"]:
        raise RuntimeError("No AI API key configured")
    return _invoke_text_llm(
        config, system, history, user_message, temperature=temperature
    )
