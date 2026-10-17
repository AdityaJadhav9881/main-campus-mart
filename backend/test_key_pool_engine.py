"""
test_key_pool_engine.py - pytest suite for the multi-key AI routing engine.

Offline by design (in-memory SQLite via the dependency override, no real
provider calls - vision/chat invokers are monkeypatched):

    * Legacy single-key config is synthesized into the pool (no migration).
    * GET /admin/ai-config masks every pooled key + exposes health/routing.
    * PUT accepts the full `keys_pool` + `routing_mode` (inherit/remove ids).
    * smart_speed / round_robin / role_based ordering + 429 cooldowns.
    * analyze_listing_images() + chat_completion() fall through the pool.
    * POST /admin/ai-config/test-key probes a stored id or raw credentials.

Run (from /backend):
    pytest -q test_key_pool_engine.py
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai import key_pool_engine, vision_master
from app.database import Base, get_db
from app.main import app
from app.models import SystemConfig

# --- In-memory SQLite + dependency override (same pattern as the others) -----
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _db_override():
    app.dependency_overrides[get_db] = _override_get_db
    key_pool_engine.reset_health()
    yield
    key_pool_engine.reset_health()
    app.dependency_overrides.pop(get_db, None)
    # Isolate tests: wipe stored AI config rows between runs.
    db = TestingSessionLocal()
    try:
        db.query(SystemConfig).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def db():
    session = TestingSessionLocal()
    yield session
    session.close()


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeHTTPError(Exception):
    """Mimics httpx.HTTPStatusError for the health tracker."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = _FakeResponse(status_code)


def _entry(
    entry_id: str,
    provider: str,
    model: str,
    api_key: str,
    *,
    roles: list[str] | None = None,
) -> dict:
    body: dict = {
        "id": entry_id,
        "provider": provider,
        "model": model,
        "api_key": api_key,
    }
    if roles is not None:
        body["roles"] = roles
    return body


# =============================================================================
# Backward compatibility: legacy single-key config -> synthesized pool
# =============================================================================
def test_legacy_single_key_synthesized_into_pool(client, db):
    raw_key = "gsk_live_key_1234567890abcd"
    saved = client.put(
        "/admin/ai-config",
        json={
            "ai_provider": "groq",
            "ai_model": "llama-3.3-70b-versatile",
            "ai_api_key": raw_key,
        },
    )
    assert saved.status_code == 200, saved.text

    body = client.get("/admin/ai-config").json()
    assert body["has_api_key"] is True
    assert body["active_keys_count"] == 1
    assert body["routing_mode"] == "smart_speed"
    assert len(body["keys_pool"]) == 1
    legacy = body["keys_pool"][0]
    assert legacy["id"] == "legacy-primary"
    assert legacy["provider"] == "groq"
    assert legacy["masked_key"] == "gsk_...abcd"
    # The raw key never appears anywhere in the response.
    assert raw_key not in json.dumps(body)

    keys = key_pool_engine.select_ordered_keys(db, "vision")
    assert [key.id for key in keys] == ["legacy-primary"]
    assert key_pool_engine.build_provider_config(keys[0]) == {
        "ai_provider": "groq",
        "ai_model": "llama-3.3-70b-versatile",
        "ai_api_key": raw_key,
        "ai_base_url": "",
    }


# =============================================================================
# Pool round-trip via PUT / GET (masking + counts + routing mode)
# =============================================================================
def test_pool_roundtrip_masks_keys_and_reports_counts(client):
    response = client.put(
        "/admin/ai-config",
        json={
            "keys_pool": [
                _entry("gem-main", "gemini", "gemini-2.5-flash", "AIzaGeminiKey0001"),
                _entry("groq-fast", "groq", "llama-3.3-70b-versatile", "gsk_groq_0002"),
                _entry("cerebras-1", "cerebras", "llama-3.3-70b", "csk_cerebras_0003"),
            ],
            "routing_mode": "round_robin",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_keys_count"] == 3
    assert body["routing_mode"] == "round_robin"
    assert [entry["id"] for entry in body["keys_pool"]] == [
        "gem-main",
        "groq-fast",
        "cerebras-1",
    ]
    for entry in body["keys_pool"]:
        assert entry["masked_key"] is not None
        assert entry["has_api_key"] is True
    for secret in ("AIzaGeminiKey0001", "gsk_groq_0002", "csk_cerebras_0003"):
        assert secret not in json.dumps(body)

    # Persists across reads.
    reread = client.get("/admin/ai-config").json()
    assert reread["routing_mode"] == "round_robin"
    assert reread["active_keys_count"] == 3


def test_pool_entry_inherits_stored_key_and_empty_string_removes_it(db):
    key_pool_engine.save_key_pool(
        db,
        [_entry("g1", "gemini", "gemini-2.5-flash", "AIzaStoredKey98765")],
    )

    # Same id without api_key -> the stored key is inherited (model edit).
    key_pool_engine.save_key_pool(
        db, [{"id": "g1", "provider": "gemini", "model": "gemini-2.0-flash"}]
    )
    pool = key_pool_engine.get_key_pool(db)
    assert len(pool) == 1
    assert pool[0].api_key == "AIzaStoredKey98765"
    assert pool[0].model == "gemini-2.0-flash"

    # Explicit empty string -> entry removed entirely.
    key_pool_engine.save_key_pool(
        db,
        [{"id": "g1", "provider": "gemini", "model": "gemini-2.0-flash",
          "api_key": ""}],
    )
    assert key_pool_engine.get_key_pool(db) == []


def test_pool_validation_rejects_bad_entries(db):
    with pytest.raises(ValueError):
        key_pool_engine.save_key_pool(
            db, [_entry("x", "deepseek", "deepseek-chat", "sk_x")]
        )
    with pytest.raises(ValueError):
        key_pool_engine.save_key_pool(
            db,
            [{"id": "x", "provider": "groq", "model": "m", "base_url": "not-a-url",
              "api_key": "sk_x"}],
        )
    with pytest.raises(ValueError):
        key_pool_engine.save_routing_mode(db, "fastest")
    assert key_pool_engine.get_routing_mode(db) == "smart_speed"


# =============================================================================
# Routing modes + health
# =============================================================================
def test_smart_speed_prefers_fast_healthy_key(db):
    key_pool_engine.save_key_pool(
        db,
        [
            _entry("slow", "gemini", "gemini-2.5-flash", "AIzaSlow"),
            _entry("fast", "groq", "llama-3.3-70b-versatile", "gsk_Fast"),
        ],
    )
    key_pool_engine.mark_success("slow", latency_ms=5000)
    key_pool_engine.mark_success("fast", latency_ms=150)

    order = key_pool_engine.select_ordered_keys(db, "vision")
    assert [key.id for key in order] == ["fast", "slow"]

    # A 429 parks the fast key for 60s -> the pool routes around it.
    key_pool_engine.mark_failure("fast", _FakeHTTPError(429))
    order = key_pool_engine.select_ordered_keys(db, "vision")
    assert [key.id for key in order] == ["slow"]

    health = key_pool_engine.health_snapshot()["fast"]
    assert health["errors_count"] == 1
    assert health["cooldown_seconds_left"] > 0


def test_cooldown_still_returns_keys_when_everything_is_cooled(db):
    key_pool_engine.save_key_pool(
        db,
        [
            _entry("a", "gemini", "gemini-2.5-flash", "AIzaA"),
            _entry("b", "groq", "llama-3.3-70b-versatile", "gsk_B"),
        ],
    )
    key_pool_engine.mark_failure("a", _FakeHTTPError(429))
    key_pool_engine.mark_failure("b", _FakeHTTPError(503))

    order = key_pool_engine.select_ordered_keys(db, "chat")
    assert sorted(key.id for key in order) == ["a", "b"]


def test_role_based_pins_dedicated_keys_first(db):
    key_pool_engine.save_key_pool(
        db,
        [
            _entry("vision-only", "gemini", "gemini-2.5-flash", "AIzaV",
                   roles=["vision"]),
            _entry("chat-only", "groq", "llama-3.3-70b-versatile", "gsk_C",
                   roles=["chat"]),
        ],
    )
    key_pool_engine.save_routing_mode(db, "role_based")

    assert key_pool_engine.select_ordered_keys(db, "chat")[0].id == "chat-only"
    assert key_pool_engine.select_ordered_keys(db, "vision")[0].id == "vision-only"

    # A lane with no dedicated key degrades to the full pool (no starvation).
    assert len(key_pool_engine.select_ordered_keys(db, "search")) == 2

    # role_based is the only mode that fully excludes other lanes when the
    # lane has a dedicated key: smart_speed still prefers the dedicated key.
    key_pool_engine.save_routing_mode(db, "smart_speed")
    assert key_pool_engine.select_ordered_keys(db, "chat")[0].id == "chat-only"


def test_round_robin_rotates_across_calls(db):
    key_pool_engine.save_key_pool(
        db,
        [
            _entry("k1", "gemini", "gemini-2.5-flash", "AIzaK1"),
            _entry("k2", "groq", "llama-3.3-70b-versatile", "gsk_K2"),
            _entry("k3", "mistral", "mistral-small-latest", "msk_K3"),
        ],
    )
    key_pool_engine.save_routing_mode(db, "round_robin")

    firsts = [
        key_pool_engine.select_ordered_keys(db, "chat")[0].id
        for _ in range(3)
    ]
    assert len(set(firsts)) == 3


def test_disabled_keys_are_skipped(db):
    key_pool_engine.save_key_pool(
        db,
        [
            {"id": "on", "provider": "gemini", "model": "gemini-2.5-flash",
             "api_key": "AIzaOn", "enabled": True},
            {"id": "off", "provider": "groq", "model": "llama-3.3-70b-versatile",
             "api_key": "gsk_Off", "enabled": False},
        ],
    )
    order = key_pool_engine.select_ordered_keys(db, "vision")
    assert [key.id for key in order] == ["on"]
    assert key_pool_engine.active_keys_count(db) == 1


# =============================================================================
# vision_master wiring: pool fall-through on provider failure
# =============================================================================
_VISION_JSON = json.dumps(
    {
        "brand": "Bose",
        "model_name": "SoundLink Flex",
        "title": "Bose SoundLink Flex Bluetooth Speaker",
        "description": "Great campus condition with original cable.",
        "category": "Electronics",
        "condition": "Good",
        "condition_notes": "Minor scuffs on the base.",
        "price_min_inr": 7000,
        "price_max_inr": 9500,
        "suggested_price_inr": 8500,
        "listed_price_inr": 7900,
        "ai_tags": ["bose", "speaker", "bluetooth"],
    }
)


def test_vision_analysis_falls_through_pool_keys(db, monkeypatch):
    key_pool_engine.save_key_pool(
        db,
        [
            _entry("broken", "gemini", "gemini-2.5-flash", "AIzaBroken"),
            _entry("working", "groq", "llama-3.3-70b-versatile", "gsk_Working"),
        ],
    )
    monkeypatch.setattr(vision_master, "_gather_images", lambda urls: [])

    calls: list[str] = []

    def fake_invoke(config, prompt, images):
        calls.append(config["ai_provider"])
        if config["ai_provider"] == "gemini":
            raise _FakeHTTPError(503)
        return _VISION_JSON, "llama-3.3-70b-versatile"

    monkeypatch.setattr(vision_master, "_invoke_vision_llm", fake_invoke)

    result = vision_master.analyze_listing_images(
        db, ["https://cdn.example.com/1.jpg"]
    )
    assert calls == ["gemini", "groq"]  # first key failed, second answered
    assert result["provider"] == "groq"
    assert result["model"] == "llama-3.3-70b-versatile"
    assert result["title"].startswith("Bose SoundLink Flex")

    health = key_pool_engine.health_snapshot()
    assert health["broken"]["errors_count"] == 1
    assert health["working"]["calls_count"] == 1


def test_vision_analysis_heuristic_when_every_key_fails(db, monkeypatch):
    key_pool_engine.save_key_pool(
        db, [_entry("only", "gemini", "gemini-2.5-flash", "AIzaOnly")]
    )
    monkeypatch.setattr(vision_master, "_gather_images", lambda urls: [])
    monkeypatch.setattr(
        vision_master,
        "_invoke_vision_llm",
        lambda config, prompt, images: (_ for _ in ()).throw(
            _FakeHTTPError(429)
        ),
    )

    result = vision_master.analyze_listing_images(
        db, ["https://cdn.example.com/1.jpg"], title="Casio calculator"
    )
    assert result["source"] == "heuristic"
    assert "Every configured Vision AI key" in result["condition_notes"]


def test_chat_completion_routes_through_pool_and_raises_when_empty(db, monkeypatch):
    with pytest.raises(RuntimeError):
        vision_master.chat_completion(
            db, system="s", history=[], user_message="hi"
        )

    key_pool_engine.save_key_pool(
        db,
        [
            _entry("c1", "gemini", "gemini-2.5-flash", "AIzaC1"),
            _entry("c2", "mistral", "mistral-small-latest", "msk_C2"),
        ],
    )

    seen: list[str] = []

    def fake_text(config, system, history, user_message, *, temperature=0.5,
                  images=None):
        seen.append(config["ai_provider"])
        if config["ai_provider"] == "gemini":
            raise _FakeHTTPError(429)
        return "Namaste! The speaker is worth about ₹8,500.", "mistral-small-latest"

    monkeypatch.setattr(vision_master, "_invoke_text_llm", fake_text)
    reply = vision_master.chat_completion(
        db, system="s", history=[], user_message="price?"
    )
    assert seen == ["gemini", "mistral"]
    assert "8,500" in reply


# =============================================================================
# POST /admin/ai-config/test-key
# =============================================================================
def test_test_key_endpoint_success_and_failure(client, db, monkeypatch):
    client.put(
        "/admin/ai-config",
        json={
            "keys_pool": [
                _entry("g1", "gemini", "gemini-2.5-flash", "AIzaProbeKey01"),
            ]
        },
    )

    monkeypatch.setattr(
        vision_master,
        "probe_key",
        lambda config, prompt=None: ("CampusMart AI online", "gemini-2.5-flash"),
    )
    ok = client.post("/admin/ai-config/test-key", json={"id": "g1"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True
    assert body["preview"] == "CampusMart AI online"
    assert body["latency_ms"] is not None
    assert body["active_keys_count"] == 1

    # The probe fed the health tracker for that pool entry.
    pool = client.get("/admin/ai-config").json()["keys_pool"]
    assert pool[0]["health"]["calls_count"] == 1
    assert pool[0]["health"]["ewma_latency_ms"] is not None

    def boom(config, prompt=None):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(vision_master, "probe_key", boom)
    failed = client.post("/admin/ai-config/test-key", json={"id": "g1"})
    assert failed.status_code == 200
    assert failed.json()["ok"] is False
    assert "provider exploded" in failed.json()["error"]

    missing = client.post("/admin/ai-config/test-key", json={"id": "nope"})
    assert missing.status_code == 404

    no_key = client.post(
        "/admin/ai-config/test-key", json={"provider": "groq"}
    )
    assert no_key.status_code == 400


def test_test_key_endpoint_accepts_raw_credentials(client, monkeypatch):
    monkeypatch.setattr(
        vision_master, "probe_key", lambda config, prompt=None: ("ok", config["ai_model"])
    )
    response = client.post(
        "/admin/ai-config/test-key",
        json={
            "provider": "cerebras",
            "model": "llama-3.3-70b",
            "api_key": "csk_raw_probe_key",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "cerebras"
    assert body["model"] == "llama-3.3-70b"
    assert "csk_raw_probe_key" not in response.text
