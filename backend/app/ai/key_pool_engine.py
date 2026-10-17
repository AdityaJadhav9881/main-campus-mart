"""
key_pool_engine.py
==================
Multi-key AI routing for CampusMart AI.

One small engine that lets the Master Admin register MANY provider keys
(Gemini, Groq, OpenRouter, OpenAI, Mistral, Cerebras) and have every AI call
route around rate limits and slow keys automatically:

    * `ai_keys_pool`     JSON array of pool entries (system_config table)
    * `ai_routing_mode`  'smart_speed' | 'round_robin' | 'role_based'

Task types
----------
`select_ordered_keys(db, task_type)` serves three lanes:
    vision  - POST /products/analyze-images (4-angle photo inspection)
    chat    - POST /ai/chat (assistant replies, photo questions)
    search  - Google-Search-grounded lookups (college discovery)

An entry whose `roles` list is empty serves EVERY lane; otherwise it only
serves the lanes it names. When a lane has no dedicated key, the engine
degrades to the full pool instead of starving the request.

Health & routing
----------------
Per-key health lives in process memory (`calls_count`, `errors_count`,
`ewma_latency_ms`, `cooldown_until`). Rate-limited / upstream-error keys
(HTTP 429/5xx) cool down for 60s and are skipped by every mode until they
recover; `smart_speed` then prefers the fastest reliable key, `round_robin`
spreads load evenly, and `role_based` pins each task to its dedicated keys.

Backward compatibility
----------------------
Old installs only have the legacy single-key rows (ai_provider / ai_model /
ai_api_key / ai_base_url written by the original PUT /admin/ai-config).
`get_key_pool()` synthesizes one pool entry from them on the fly, so nothing
needs migrating: the moment the admin saves a real pool, it takes over.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..models import SystemConfig

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Providers (must stay in sync with vision_master.PROVIDERS)
# -----------------------------------------------------------------------------
PROVIDERS: tuple[str, ...] = (
    "gemini",
    "openai",
    "groq",
    "openrouter",
    "mistral",
    "cerebras",
)

PROVIDER_BASE_URLS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
}

DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "google/gemini-2.5-flash",
    "mistral": "mistral-small-latest",
    "cerebras": "llama-3.3-70b",
}

TASK_TYPES: tuple[str, ...] = ("vision", "chat", "search")
ROUTING_MODES: tuple[str, ...] = ("smart_speed", "round_robin", "role_based")
DEFAULT_ROUTING_MODE = "smart_speed"

# system_config row keys owned by this engine.
POOL_CONFIG_KEY = "ai_keys_pool"
ROUTING_CONFIG_KEY = "ai_routing_mode"
LEGACY_CONFIG_KEYS = ("ai_provider", "ai_model", "ai_api_key", "ai_base_url")

MAX_POOL_KEYS = 50

# Cooldowns applied by the health tracker after a failed upstream call.
RATE_LIMIT_COOLDOWN_SECONDS = 60.0
ERROR_COOLDOWN_SECONDS = 10.0
_RATE_LIMIT_STATUSES = (429, 500, 502, 503, 504)


# =============================================================================
# Pool entry
# =============================================================================
@dataclass
class PoolKey:
    """One provider key in the routing pool."""

    id: str
    label: str
    provider: str
    model: str
    api_key: str
    base_url: str = ""
    roles: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True

    def to_row(self) -> dict[str, Any]:
        """Serializable `system_config` row (raw key included - it is the
        admin's own storage)."""
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "roles": list(self.roles),
            "enabled": self.enabled,
        }


def mask_key(key: str | None) -> str | None:
    """'sk-abc...wxyz' style mask so screens never show the raw secret."""
    if not key:
        return None
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


# =============================================================================
# Pool persistence
# =============================================================================
def _read_config_rows(db: Session, keys: tuple[str, ...]) -> dict[str, str]:
    return {
        row.key: (row.value or "")
        for row in db.query(SystemConfig).filter(SystemConfig.key.in_(keys)).all()
    }


def _legacy_pool(db: Session) -> list[PoolKey]:
    """Synthesize one pool entry from the legacy single-key config rows."""
    rows = _read_config_rows(db, LEGACY_CONFIG_KEYS)
    api_key = (rows.get("ai_api_key") or "").strip()
    if not api_key:
        return []
    provider = (rows.get("ai_provider") or "gemini").strip().lower()
    if provider not in PROVIDERS:
        provider = "gemini"
    model = (rows.get("ai_model") or DEFAULT_MODELS[provider]).strip()
    return [
        PoolKey(
            id="legacy-primary",
            label="Primary key (legacy config)",
            provider=provider,
            model=model or DEFAULT_MODELS[provider],
            api_key=api_key,
            base_url=(rows.get("ai_base_url") or "").strip(),
        )
    ]


def get_key_pool(db: Session) -> list[PoolKey]:
    """Full pool in admin-defined order (enabled + disabled entries).

    Falls back to the legacy single-key rows so existing installs keep
    running with zero migration.
    """
    row = db.get(SystemConfig, POOL_CONFIG_KEY)
    raw = (row.value or "").strip() if row is not None else ""
    if not raw:
        return _legacy_pool(db)
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("ai_keys_pool is not valid JSON; using legacy config")
        return _legacy_pool(db)
    if not isinstance(rows, list) or not rows:
        return _legacy_pool(db)
    pool: list[PoolKey] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = _entry_from_row(item)
        if key is not None:
            pool.append(key)
    return pool


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "key"


def _entry_from_row(item: dict[str, Any]) -> PoolKey | None:
    provider = str(item.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        return None
    api_key = str(item.get("api_key") or "").strip()
    if not api_key:
        return None
    model = str(item.get("model") or "").strip() or DEFAULT_MODELS[provider]
    roles_raw = item.get("roles")
    roles: tuple[str, ...] = ()
    if isinstance(roles_raw, list):
        roles = tuple(
            role for role in (str(r).strip().lower() for r in roles_raw)
            if role in TASK_TYPES
        )
    entry_id = str(item.get("id") or "").strip() or _slugify(
        f"{provider}-{model}"
    )
    return PoolKey(
        id=entry_id,
        label=str(item.get("label") or "").strip() or f"{provider} · {model}",
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=str(item.get("base_url") or "").strip(),
        roles=roles,
        enabled=bool(item.get("enabled", True)),
    )


def save_key_pool(db: Session, entries: list[dict[str, Any]]) -> list[PoolKey]:
    """Replace the pool with [entries] (PUT /admin/ai-config `keys_pool`).

    Merge rules:
      * an entry whose `id` matches a stored one INHERITS the stored raw key
        when the payload omits `api_key` (admin edited only label/model);
      * an entry with an empty-string `api_key` is dropped (that is how a key
        is removed while keeping the rest of the list untouched);
      * ids are generated from provider + model when missing, de-duplicated.
    """
    if len(entries) > MAX_POOL_KEYS:
        raise ValueError(f"The pool accepts at most {MAX_POOL_KEYS} keys.")
    existing = {key.id: key for key in get_key_pool(db)}
    used_ids: set[str] = set()
    pool: list[PoolKey] = []

    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError(f"keys_pool[{index}] must be an object.")
        provider = str(item.get("provider") or "").strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(
                f"keys_pool[{index}]: unsupported provider "
                f"'{provider or '(missing)'}'."
            )
        model = str(item.get("model") or "").strip() or DEFAULT_MODELS[provider]
        base_url = str(item.get("base_url") or "").strip()
        if base_url and not base_url.lower().startswith(("http://", "https://")):
            raise ValueError(
                f"keys_pool[{index}]: base_url must be an http(s) URL."
            )

        entry_id = str(item.get("id") or "").strip()
        inherited = existing.get(entry_id) if entry_id else None

        raw_key = item.get("api_key")
        if raw_key is None:
            api_key = inherited.api_key if inherited else ""
        else:
            api_key = str(raw_key).strip()
        if not api_key:
            # Explicit empty string (or brand-new entry without one) -> skip.
            continue

        if not entry_id:
            entry_id = _slugify(f"{provider}-{model}")
        candidate = entry_id
        suffix = 2
        while candidate in used_ids:
            candidate = f"{entry_id}-{suffix}"
            suffix += 1
        entry_id = candidate
        used_ids.add(entry_id)

        roles_raw = item.get("roles")
        roles: tuple[str, ...] = ()
        if isinstance(roles_raw, list):
            roles = tuple(
                role for role in (str(r).strip().lower() for r in roles_raw)
                if role in TASK_TYPES
            )

        pool.append(
            PoolKey(
                id=entry_id,
                label=str(item.get("label") or "").strip()
                or f"{provider} · {model}",
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                roles=roles,
                enabled=bool(item.get("enabled", True)),
            )
        )

    _upsert_config(
        db, POOL_CONFIG_KEY, json.dumps([key.to_row() for key in pool])
    )
    logger.info("AI key pool saved: %d active entries", len(pool))
    return pool


def _upsert_config(db: Session, key: str, value: str) -> None:
    row = db.get(SystemConfig, key)
    if row is None:
        db.add(SystemConfig(key=key, value=value))
    else:
        row.value = value
    db.commit()


# =============================================================================
# Routing mode
# =============================================================================
def get_routing_mode(db: Session) -> str:
    row = db.get(SystemConfig, ROUTING_CONFIG_KEY)
    mode = (row.value or "").strip().lower() if row is not None else ""
    return mode if mode in ROUTING_MODES else DEFAULT_ROUTING_MODE


def save_routing_mode(db: Session, mode: str) -> str:
    cleaned = (mode or "").strip().lower()
    if cleaned not in ROUTING_MODES:
        raise ValueError(
            f"Unsupported routing mode '{mode}'. "
            f"Valid: {', '.join(ROUTING_MODES)}"
        )
    _upsert_config(db, ROUTING_CONFIG_KEY, cleaned)
    return cleaned


# =============================================================================
# Per-key health (process memory - resets on redeploy, by design)
# =============================================================================
@dataclass
class KeyHealth:
    cooldown_until: float = 0.0
    ewma_latency_ms: float | None = None
    calls_count: int = 0
    errors_count: int = 0
    last_ok_at: float | None = None
    last_error: str | None = None


_HEALTH: dict[str, KeyHealth] = {}
_HEALTH_LOCK = threading.Lock()
_RR_COUNTER = 0


def _health_of(key_id: str) -> KeyHealth:
    return _HEALTH.setdefault(key_id, KeyHealth())


def reset_health() -> None:
    """Clear all health state (tests + admin troubleshooting)."""
    global _RR_COUNTER
    with _HEALTH_LOCK:
        _HEALTH.clear()
        _RR_COUNTER = 0


def mark_success(key_id: str, *, latency_ms: float) -> None:
    """Record a healthy call: resets cooldown, folds the latency EWMA."""
    now = time.time()
    with _HEALTH_LOCK:
        health = _health_of(key_id)
        health.calls_count += 1
        health.ewma_latency_ms = (
            latency_ms
            if health.ewma_latency_ms is None
            else 0.3 * latency_ms + 0.7 * health.ewma_latency_ms
        )
        health.cooldown_until = 0.0
        health.last_ok_at = now
        health.last_error = None


def _http_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def mark_failure(key_id: str, exc: Exception) -> None:
    """Record a failed call: 429/5xx park the key for 60s, other errors 10s."""
    status = _http_status(exc)
    cooldown = (
        RATE_LIMIT_COOLDOWN_SECONDS
        if status in _RATE_LIMIT_STATUSES
        else ERROR_COOLDOWN_SECONDS
    )
    now = time.time()
    with _HEALTH_LOCK:
        health = _health_of(key_id)
        health.calls_count += 1
        health.errors_count += 1
        health.cooldown_until = max(health.cooldown_until, now + cooldown)
        health.last_error = f"{type(exc).__name__}: {exc}"[:300]
    logger.warning(
        "AI key %s failed (status=%s, cooldown=%.0fs): %s",
        key_id,
        status or "n/a",
        cooldown,
        exc,
    )


def health_snapshot() -> dict[str, dict[str, Any]]:
    """Read-only health view for GET /admin/ai-config (dashboard)."""
    now = time.time()
    with _HEALTH_LOCK:
        return {
            key_id: {
                "calls_count": health.calls_count,
                "errors_count": health.errors_count,
                "ewma_latency_ms": (
                    round(health.ewma_latency_ms, 1)
                    if health.ewma_latency_ms is not None
                    else None
                ),
                "cooldown_seconds_left": max(
                    0, round(health.cooldown_until - now, 1)
                ),
                "last_ok_at": health.last_ok_at,
                "last_error": health.last_error,
            }
            for key_id, health in _HEALTH.items()
        }


# =============================================================================
# Selection
# =============================================================================
def select_ordered_keys(db: Session, task_type: str = "chat") -> list[PoolKey]:
    """The ordered attempt list for [task_type] under the active mode.

    Always excludes cooling keys when a healthy alternative exists; when
    every candidate is cooling, returns them ordered by soonest recovery so
    the request still gets its best shot.
    """
    global _RR_COUNTER

    task = task_type if task_type in TASK_TYPES else "chat"
    pool = [key for key in get_key_pool(db) if key.enabled]
    if not pool:
        return []

    eligible = [key for key in pool if not key.roles or task in key.roles]
    if not eligible:
        # No dedicated key for this lane: degrade to the full pool rather
        # than starving the request.
        eligible = pool

    now = time.time()
    with _HEALTH_LOCK:
        ready = [
            key
            for key in eligible
            if _health_of(key.id).cooldown_until <= now
        ]
    if ready:
        candidates = ready
    else:
        candidates = sorted(
            eligible,
            key=lambda key: _health_of(key.id).cooldown_until,
        )

    mode = get_routing_mode(db)
    if mode == "round_robin":
        with _HEALTH_LOCK:
            _RR_COUNTER += 1
            offset = _RR_COUNTER % len(candidates)
        return candidates[offset:] + candidates[:offset]

    def _health_rank(key: PoolKey) -> tuple[int, float]:
        health = _health_of(key.id)
        return (health.errors_count, health.ewma_latency_ms or 10**9)

    if mode == "role_based":
        return sorted(
            candidates,
            key=lambda key: (
                0 if (key.roles and task in key.roles) else 1,
                *_health_rank(key),
            ),
        )

    # smart_speed (default): proven-fast, low-error keys first.
    order = {key.id: index for index, key in enumerate(candidates)}
    return sorted(
        candidates,
        key=lambda key: (*_health_rank(key), order[key.id]),
    )


def build_provider_config(key: PoolKey) -> dict[str, str]:
    """Shape one pool entry like the legacy `get_ai_config` dict so the
    vision_master provider invokers run unchanged."""
    return {
        "ai_provider": key.provider,
        "ai_model": key.model,
        "ai_api_key": key.api_key,
        "ai_base_url": key.base_url,
    }


# =============================================================================
# Admin views
# =============================================================================
def active_keys_count(db: Session) -> int:
    return len([key for key in get_key_pool(db) if key.enabled and key.api_key])


def pool_snapshot(db: Session) -> list[dict[str, Any]]:
    """GET-side view: masked keys + live health, never raw secrets."""
    health = health_snapshot()
    return [
        {
            "id": key.id,
            "label": key.label,
            "provider": key.provider,
            "model": key.model,
            "base_url": key.base_url or None,
            "roles": list(key.roles),
            "enabled": key.enabled,
            "has_api_key": bool(key.api_key),
            "masked_key": mask_key(key.api_key),
            "health": health.get(key.id),
        }
        for key in get_key_pool(db)
    ]
