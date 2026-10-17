"""
college_discovery.py
====================
Long-tail college lookup for `GET /colleges`.

The bundled CET catalog (cet_colleges.py) covers the institutes students ask
about most; everything else is discovered on demand and cached forever in the
`college_directory` table:

    1. `directory_search()`  - previously discovered rows (instant, offline).
    2. `discover_colleges()`:
         a. Gemini + Google Search grounding through the Multi-Key AI pool
            (`key_pool_engine.select_ordered_keys(db, "search")`, so the
            search lane can be pinned to a dedicated key and 429s fail over
            to the next key). Requires at least one Gemini key in the pool.
         b. Wikipedia, then OpenStreetMap/Nominatim as keyless HTTP
            fallbacks (Nominatim last: it returns the structured city).
       Results are de-duplicated against the catalog and the directory cache,
       then saved via `_save_discovered()`.

Everything is best-effort: any provider/web failure returns [] and the
picker's "use my own college" custom tile still works. Set
COLLEGE_WEB_DISCOVERY=0 to disable the keyless web fallback entirely (the
pytest suite does exactly that to stay offline).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .ai import key_pool_engine
from .cet_colleges import CET_COLLEGES, CetCollege, get_college_by_code
from .models import CollegeDirectory

logger = logging.getLogger(__name__)

__all__ = [
    "directory_search",
    "directory_to_college",
    "discover_colleges",
    "normalize_text",
]

_AI_TIMEOUT_SECONDS = 12.0
_WEB_TIMEOUT_SECONDS = 6.0

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
_NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_USER_AGENT = "CampusMartAI/2.5 (college directory; support@campusmart.in)"

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_INSTITUTE_WORDS = re.compile(
    r"college|institute|university|polytechnic|vidyapeeth|vidyalaya|mahavidyalaya",
    re.IGNORECASE,
)

_PROMPT_TEMPLATE = (
    "You are CampusMart's college directory assistant for Maharashtra, India.\n"
    "Use Google Search to find real colleges/institutes matching this student "
    'query: "{query}".\n'
    "Return STRICT JSON only (no markdown, no commentary):\n"
    '{"colleges": [{"name": "official institute name", '
    '"short_name": "acronym students use", '
    '"code": "DTE/CET Cell institute code or empty string", '
    '"city": "city", "aliases": ["extra names students type"]}]}\n'
    "Rules: 1-5 results; only genuine institutes located in Maharashtra; "
    "prefer engineering / pharmacy / medical / degree colleges; \"code\" must "
    'be the real CET Cell institute code when you are sure, else "".'
)


def normalize_text(value: str | None) -> str:
    """Case/punctuation-insensitive comparison key ("Dr. D.Y. Patil" ->
    "dr d y patil")."""
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _web_enabled() -> bool:
    raw = (os.getenv("COLLEGE_WEB_DISCOVERY") or "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


# =============================================================================
# HTTP helpers (module-level so tests can monkeypatch the network away)
# =============================================================================
def _http_post_json(url: str, payload: dict, *, timeout: float = _AI_TIMEOUT_SECONDS) -> dict:
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _http_get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = _WEB_TIMEOUT_SECONDS,
) -> Any:
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _extract_json(text: str) -> dict | None:
    match = _JSON_BLOCK.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _looks_like_college(name: str) -> bool:
    return bool(_INSTITUTE_WORDS.search(name))


# =============================================================================
# Cached directory search (offline)
# =============================================================================
def directory_to_college(row: CollegeDirectory) -> CetCollege:
    """Adapt a cached directory row to the catalog's `CetCollege` shape so the
    router can serialize both with `college_to_dict`."""
    return CetCollege(
        code=row.code or "",
        name=row.name,
        short_name=row.short_name or "",
        city=row.city or "Other",
        aliases=tuple(a for a in (row.aliases or []) if a),
    )


def _row_blob(row: CollegeDirectory) -> str:
    parts = [row.name or "", row.short_name or "", row.city or "", row.code or ""]
    parts.extend(a for a in (row.aliases or []) if a)
    return " | ".join(parts).lower()


def _row_score(row: CollegeDirectory, term: str) -> int:
    code = (row.code or "").lower()
    short = (row.short_name or "").lower()
    name = (row.name or "").lower()

    if code and code == term:
        return 100
    if short and short == term:
        return 95
    if code and code.startswith(term):
        return 90
    if short and short.startswith(term):
        return 85
    if any(a.lower().startswith(term) for a in (row.aliases or []) if a):
        return 80
    if term in name:
        return 70 if f" {term}" in f" {name}" else 55
    if term in _row_blob(row):
        return 40
    return 0


def directory_search(
    db: Session,
    q: str = "",
    city: str = "",
    limit: int = 20,
) -> list[CollegeDirectory]:
    """Rank cached directory rows with the same relevance contract as the
    catalog's `search_colleges` (multi-word queries are ANDed)."""
    terms = [t for t in (q or "").lower().replace(",", " ").split() if t]
    city_norm = (city or "").strip().lower()

    scored: list[tuple[int, CollegeDirectory]] = []
    for row in db.query(CollegeDirectory).all():
        if (
            city_norm
            and city_norm not in ("all", "all campuses")
            and (row.city or "").lower() != city_norm
        ):
            continue
        if not terms:
            total = 1
        else:
            total = 0
            matched_all = True
            for term in terms:
                score = _row_score(row, term)
                if score == 0:
                    matched_all = False
                    break
                total += score
            if not matched_all:
                continue
        scored.append((total, row))

    scored.sort(key=lambda pair: (-pair[0], pair[1].city or "", pair[1].name))
    return [row for _, row in scored[: max(1, limit)]]


# =============================================================================
# Dedupe + persistence
# =============================================================================
def _dupe_in_catalog(name: str, code: str) -> bool:
    if code and get_college_by_code(code) is not None:
        return True
    norm = normalize_text(name)
    if not norm:
        return True
    for college in CET_COLLEGES:
        if norm == normalize_text(college.name):
            return True
        if norm == normalize_text(college.short_name):
            return True
    return False


def _dupe_in_directory(db: Session, name: str, code: str) -> bool:
    norm = normalize_text(name)
    for row in db.query(CollegeDirectory).all():
        if code and row.code and row.code == code:
            return True
        if norm and norm == normalize_text(row.name):
            return True
        if norm and row.short_name and norm == normalize_text(row.short_name):
            return True
    return False


def _clean_items(rows: list[dict]) -> list[dict]:
    """Normalize raw provider rows into storable dicts (dropping junk)."""
    cleaned: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:255]
        if not name:
            continue
        aliases_raw = item.get("aliases")
        aliases = (
            [str(a).strip()[:120] for a in aliases_raw if str(a).strip()][:8]
            if isinstance(aliases_raw, list)
            else []
        )
        cleaned.append(
            {
                "name": name,
                "short_name": str(item.get("short_name") or "").strip()[:120],
                "code": str(item.get("code") or "").strip()[:16],
                "city": str(item.get("city") or "").strip()[:120],
                "aliases": aliases,
            }
        )
    return cleaned


def _save_discovered(db: Session, rows: list[dict], source: str) -> list[CollegeDirectory]:
    saved: list[CollegeDirectory] = []
    seen_names: set[str] = set()
    seen_codes: set[str] = set()
    for item in _clean_items(rows):
        norm = normalize_text(item["name"])
        code = item["code"].lower() if item["code"] else ""
        # Duplicates inside the same batch (autoflush is off) + against the
        # catalog + against previously cached rows.
        if norm in seen_names or (code and code in seen_codes):
            continue
        if _dupe_in_catalog(item["name"], item["code"]):
            continue
        if _dupe_in_directory(db, item["name"], item["code"]):
            continue
        seen_names.add(norm)
        if code:
            seen_codes.add(code)
        row = CollegeDirectory(
            code=item["code"],
            name=item["name"],
            short_name=item["short_name"],
            city=item["city"],
            aliases=item["aliases"],
            source=source,
            verified=source in ("ai", "wikipedia"),
        )
        db.add(row)
        saved.append(row)
    if saved:
        db.commit()
    return saved


# =============================================================================
# Step 3a - Gemini + Google Search grounding (multi-key pool)
# =============================================================================
def _ask_gemini(key: key_pool_engine.PoolKey, query: str) -> tuple[list[dict], bool]:
    """One grounded generateContent call.

    Returns (rows, parsed_ok): `parsed_ok=False` means the model did not
    answer with JSON (truncated / blocked) - callers may try the next key.
    """
    config = key_pool_engine.build_provider_config(key)
    base_url = config["ai_base_url"] or _GEMINI_BASE_URL
    url = f"{base_url}/models/{config['ai_model']}:generateContent?key={config['ai_api_key']}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _PROMPT_TEMPLATE.replace("{query}", query)}],
            }
        ],
        # Google Search grounding - the model searches the live web.
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }
    data = _http_post_json(url, payload)

    text = ""
    candidates = data.get("candidates") or []
    if candidates:
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        text = " ".join(str(part.get("text") or "") for part in parts)

    parsed = _extract_json(text)
    if parsed is None:
        return [], False
    rows = parsed.get("colleges")
    if not isinstance(rows, list):
        return [], True
    return [row for row in rows if isinstance(row, dict)], True


def _discover_via_ai(db: Session, query: str) -> list[dict]:
    """Try every ordered Gemini key until one answers with JSON."""
    keys = [
        key
        for key in key_pool_engine.select_ordered_keys(db, "search")
        if key.provider == "gemini"
    ]
    for key in keys:
        started = time.perf_counter()
        try:
            rows, parsed_ok = _ask_gemini(key, query)
        except Exception as exc:  # noqa: BLE001 - any provider failure falls over
            key_pool_engine.mark_failure(key.id, exc)
            logger.info("College AI discovery: key %s failed (%s)", key.id, exc)
            continue
        key_pool_engine.mark_success(
            key.id, latency_ms=(time.perf_counter() - started) * 1000
        )
        if parsed_ok:
            return rows
        logger.info("College AI discovery: key %s returned no parseable JSON", key.id)
    return []


# =============================================================================
# Step 3b - keyless web fallbacks
# =============================================================================
def _discover_via_wikipedia(query: str) -> list[dict]:
    payload = _http_get_json(
        _WIKIPEDIA_ENDPOINT,
        params={
            "action": "opensearch",
            "search": f"{query} college Maharashtra",
            "limit": 5,
            "namespace": 0,
            "format": "json",
        },
    )
    titles = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    rows: list[dict] = []
    for title in titles:
        name = str(title or "").strip()
        if name and _looks_like_college(name):
            rows.append(
                {"name": name, "short_name": "", "code": "", "city": "", "aliases": []}
            )
    return rows


def _discover_via_nominatim(query: str) -> list[dict]:
    payload = _http_get_json(
        _NOMINATIM_ENDPOINT,
        params={
            "q": f"{query} college",
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5,
            "countrycodes": "in",
        },
        headers={"User-Agent": _NOMINATIM_USER_AGENT},
    )
    rows: list[dict] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        display = str(item.get("display_name") or "")
        name = str(item.get("name") or "").strip() or display.split(",")[0].strip()
        if not name or not _looks_like_college(name):
            continue
        address = item.get("address") or {}
        city = ""
        for field in ("city", "town", "village", "municipality", "state_district"):
            if address.get(field):
                city = str(address[field]).strip()[:120]
                break
        rows.append(
            {"name": name, "short_name": "", "code": "", "city": city, "aliases": []}
        )
    return rows


# =============================================================================
# Orchestrator (called by GET /colleges on a full miss)
# =============================================================================
def discover_colleges(db: Session, query: str) -> list[CollegeDirectory]:
    """Discover + persist colleges for [query]; [] when nothing is found.

    Never raises: a broken provider/web request must not take the picker down.
    """
    query = (query or "").strip()
    if len(query) < 3:
        return []

    try:
        rows = _discover_via_ai(db, query)
    except Exception as exc:  # noqa: BLE001 - defensive; _discover_via_ai already guards
        logger.warning("College AI discovery crashed: %s", exc)
        rows = []
    source = "ai"

    if not rows and _web_enabled():
        for source, fallback in (
            ("wikipedia", _discover_via_wikipedia),
            ("osm", _discover_via_nominatim),
        ):
            try:
                rows = fallback(query)
            except Exception as exc:  # noqa: BLE001 - best-effort fallback
                logger.info("College web discovery (%s) failed: %s", source, exc)
                rows = []
            if rows:
                break

    if not rows:
        return []
    try:
        return _save_discovered(db, rows, source)
    except Exception as exc:  # noqa: BLE001 - duplicate races etc.
        db.rollback()
        logger.warning("College discovery save failed: %s", exc)
        return []
