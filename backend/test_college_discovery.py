"""
test_college_discovery.py - pytest suite for the college discovery upgrade.

Offline by design (in-memory SQLite + dependency override; the keyless
Wikipedia/Nominatim fallback is disabled via COLLEGE_WEB_DISCOVERY=0 in
conftest and every HTTP helper is monkeypatched):

    * Karad cluster in the bundled catalog (Daulatrao Aher 6303, GCOE Karad
      6005, Govt College of Pharmacy 6008, KIMS/SGM code-less entries).
    * Search order: catalog -> cached directory -> on-demand discovery.
    * Gemini Google-Search grounding through the multi-key pool (health
      tracking + 429 fail-over + non-Gemini pools are skipped).
    * Wikipedia / Nominatim parsers + persistence + de-duplication + city
      pills for discovered cities.

Run (from /backend):
    pytest -q test_college_discovery.py
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import college_discovery
from app.ai import key_pool_engine
from app.database import Base, get_db
from app.main import app
from app.models import CollegeDirectory, SystemConfig

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
    # Isolate tests: wipe cached colleges + AI config between runs.
    db = TestingSessionLocal()
    try:
        db.query(CollegeDirectory).delete()
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
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = _FakeResponse(status_code)


def _vcet_row() -> dict:
    return {
        "name": "Vidyavardhini's College of Engineering and Technology, Vasai",
        "short_name": "VCET",
        "code": "3431",
        "city": "Vasai",
        "aliases": ["Vidyavardhini Vasai", "VCET Vasai"],
    }


def _gemini_payload(items: list[dict]) -> dict:
    text = json.dumps({"colleges": items})
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _search(client: TestClient, q: str, **params) -> dict:
    response = client.get("/colleges", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


# =============================================================================
# Karad cluster (verified against mahacet.org / DTE Pune regional lists)
# =============================================================================
def test_karad_search_returns_daulatrao_aher_first(client):
    body = _search(client, "karad")
    first = body["colleges"][0]
    assert first["code"] == "6303"
    assert "Daulatrao Aher" in first["name"]

    codes = {college["code"] for college in body["colleges"]}
    assert {"6303", "6005", "6008", "6516", "6332"}.issubset(codes)

    by_code = {college["code"]: college["name"] for college in body["colleges"]}
    assert by_code["6005"] == "Government College of Engineering, Karad"
    assert by_code["6008"] == "Government College of Pharmacy, Karad"

    kims = [c for c in body["colleges"] if "Krishna Institute of Medical Sciences" in c["name"]]
    sgm = [c for c in body["colleges"] if "Sadguru Gadage Maharaj" in c["name"]]
    assert kims and kims[0]["code"] == ""
    assert sgm and sgm[0]["code"] == ""


def test_gcoe_karad_code_stays_6005(client):
    body = _search(client, "gcoek")
    assert body["colleges"][0]["code"] == "6005"
    assert body["colleges"][0]["name"] == "Government College of Engineering, Karad"


# =============================================================================
# Search order: catalog -> directory cache -> discovery
# =============================================================================
def test_local_catalog_match_never_triggers_discovery(client, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        college_discovery, "discover_colleges",
        lambda db_, q: (calls.append(q), [])[1],
    )
    body = _search(client, "coep")
    assert body["colleges"][0]["code"] == "6006"
    assert calls == []


def test_low_length_query_never_triggers_discovery(client, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        college_discovery, "discover_colleges",
        lambda db_, q: (calls.append(q), [])[1],
    )
    body = _search(client, "xq")
    assert body["count"] == 0
    assert calls == []


def test_empty_query_lists_cities_only(client):
    body = _search(client, "")
    assert body["count"] == 50  # default browse-all page, no discovery
    assert body["cities"][0] == "All"
    assert "Pune" in body["cities"]


def test_ai_discovery_saves_and_second_lookup_is_local(client, db, monkeypatch):
    discovery_calls: list[str] = []

    def fake_ai(db_, query):
        discovery_calls.append(query)
        return [_vcet_row()]

    monkeypatch.setattr(college_discovery, "_discover_via_ai", fake_ai)

    body = _search(client, "vidyavardhini")
    assert body["count"] >= 1
    vcet = body["colleges"][0]
    assert vcet["short_name"] == "VCET"
    assert vcet["code"] == "3431"
    assert vcet["custom"] is False
    assert discovery_calls == ["vidyavardhini"]

    saved = db.query(CollegeDirectory).all()
    assert len(saved) == 1
    assert saved[0].source == "ai"
    assert saved[0].verified is True

    # Second lookup hits the cache: discovery must NOT run again.
    discovery_calls.clear()
    again = _search(client, "vidyavardhini")
    assert again["count"] >= 1
    assert again["colleges"][0]["code"] == "3431"
    assert discovery_calls == []
    assert db.query(CollegeDirectory).count() == 1


def test_web_fallback_used_when_ai_returns_nothing(client, db, monkeypatch):
    monkeypatch.setenv("COLLEGE_WEB_DISCOVERY", "1")
    monkeypatch.setattr(college_discovery, "_discover_via_ai", lambda db_, q: [])

    wiki_calls: list[str] = []

    def fake_wiki(query):
        wiki_calls.append(query)
        return [{"name": "Sathaye College, Vile Parle", "short_name": "",
                 "code": "", "city": "", "aliases": []}]

    monkeypatch.setattr(college_discovery, "_discover_via_wikipedia", fake_wiki)
    monkeypatch.setattr(
        college_discovery, "_discover_via_nominatim",
        lambda q: (_ for _ in ()).throw(AssertionError("nominatim should not run")),
    )

    body = _search(client, "sathaye")
    assert body["count"] >= 1
    assert "Sathaye College" in body["colleges"][0]["name"]
    assert wiki_calls == ["sathaye"]

    saved = db.query(CollegeDirectory).one()
    assert saved.source == "wikipedia"
    assert saved.verified is True


def test_nominatim_runs_when_wikipedia_is_empty(client, db, monkeypatch):
    monkeypatch.setenv("COLLEGE_WEB_DISCOVERY", "1")
    monkeypatch.setattr(college_discovery, "_discover_via_ai", lambda db_, q: [])
    monkeypatch.setattr(college_discovery, "_discover_via_wikipedia", lambda q: [])
    monkeypatch.setattr(
        college_discovery, "_discover_via_nominatim",
        lambda q: [{"name": "Sathaye College, Vile Parle", "short_name": "",
                    "code": "", "city": "Mumbai", "aliases": []}],
    )

    body = _search(client, "sathaye")
    assert body["count"] >= 1
    saved = db.query(CollegeDirectory).one()
    assert saved.source == "osm"
    assert saved.city == "Mumbai"


def test_allow_custom_echoes_after_empty_discovery(client, monkeypatch):
    monkeypatch.setattr(college_discovery, "discover_colleges", lambda db_, q: [])
    body = _search(client, "Zilla Tech Institute Ulhasnagar", allow_custom=True)
    assert body["count"] == 1
    assert body["colleges"][0]["custom"] is True


def test_cached_directory_row_served_without_discovery(client, db, monkeypatch):
    college_discovery._save_discovered(db, [_vcet_row()], "ai")

    calls: list[str] = []
    monkeypatch.setattr(
        college_discovery, "discover_colleges",
        lambda db_, q: (calls.append(q), [])[1],
    )

    body = _search(client, "vidyavardhini")
    assert body["colleges"][0]["code"] == "3431"
    assert calls == []

    filtered = _search(client, "vidyavardhini", city="Vasai")
    assert filtered["count"] >= 1

    wrong_city = _search(client, "vidyavardhini", city="Pune")
    assert wrong_city["count"] == 0


def test_discovered_city_appears_in_pills(client, db):
    college_discovery._save_discovered(db, [_vcet_row()], "ai")
    body = _search(client, "")
    assert "Vasai" in body["cities"]
    assert "Other" not in body["cities"]


# =============================================================================
# Gemini grounding through the multi-key pool
# =============================================================================
def test_gemini_grounding_parses_and_marks_health(db, monkeypatch):
    key_pool_engine.save_key_pool(
        db,
        [{"id": "gem", "provider": "gemini", "model": "gemini-2.5-flash",
          "api_key": "AIzaGemKey0001"}],
    )

    sent: list[dict] = []

    def fake_post(url, payload, *, timeout=12.0):
        sent.append({"url": url, "payload": payload})
        return _gemini_payload([_vcet_row()])

    monkeypatch.setattr(college_discovery, "_http_post_json", fake_post)

    rows = college_discovery._discover_via_ai(db, "vidyavardhini college")
    assert rows and rows[0]["name"].startswith("Vidyavardhini")
    assert len(sent) == 1
    assert "AIzaGemKey0001" in sent[0]["url"]
    assert sent[0]["payload"]["tools"] == [{"google_search": {}}]

    health = key_pool_engine.health_snapshot()
    assert health["gem"]["calls_count"] == 1
    assert health["gem"]["errors_count"] == 0


def test_gemini_429_fails_over_to_next_key(db, monkeypatch):
    key_pool_engine.save_key_pool(
        db,
        [
            {"id": "first", "provider": "gemini", "model": "gemini-2.5-flash",
             "api_key": "AIzaFirst0001"},
            {"id": "second", "provider": "gemini", "model": "gemini-2.5-flash",
             "api_key": "AIzaSecond0002"},
        ],
    )

    def fake_post(url, payload, *, timeout=12.0):
        if "AIzaFirst0001" in url:
            raise _FakeHTTPError(429)
        return _gemini_payload([_vcet_row()])

    monkeypatch.setattr(college_discovery, "_http_post_json", fake_post)

    rows = college_discovery._discover_via_ai(db, "vidyavardhini college")
    assert rows and rows[0]["code"] == "3431"

    health = key_pool_engine.health_snapshot()
    assert health["first"]["errors_count"] == 1
    assert health["first"]["cooldown_seconds_left"] > 0
    assert health["second"]["calls_count"] == 1


def test_ai_discovery_retries_next_key_on_unparseable_answer(db, monkeypatch):
    key_pool_engine.save_key_pool(
        db,
        [
            {"id": "mute", "provider": "gemini", "model": "gemini-2.5-flash",
             "api_key": "AIzaMute0001"},
            {"id": "talk", "provider": "gemini", "model": "gemini-2.5-flash",
             "api_key": "AIzaTalk0002"},
        ],
    )

    def fake_post(url, payload, *, timeout=12.0):
        if "AIzaMute0001" in url:
            return {"candidates": [{"content": {"parts": [{"text": "no json"}]}}]}
        return _gemini_payload([_vcet_row()])

    monkeypatch.setattr(college_discovery, "_http_post_json", fake_post)

    rows = college_discovery._discover_via_ai(db, "vidyavardhini college")
    assert rows and rows[0]["code"] == "3431"


def test_ai_discovery_skips_non_gemini_pools(db, monkeypatch):
    key_pool_engine.save_key_pool(
        db,
        [{"id": "groq-only", "provider": "groq",
          "model": "llama-3.3-70b-versatile", "api_key": "gsk_Only0001"}],
    )
    monkeypatch.setattr(
        college_discovery, "_http_post_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")),
    )
    assert college_discovery._discover_via_ai(db, "vidyavardhini college") == []


# =============================================================================
# Web parsers (httpx monkeypatched at the helper level)
# =============================================================================
def test_wikipedia_parser_filters_non_institutes(monkeypatch):
    monkeypatch.setattr(
        college_discovery, "_http_get_json",
        lambda *a, **k: [
            "sathaye college",
            ["Sathaye College", "Sathaye family", "Vile Parle"],
            [],
            [],
        ],
    )
    rows = college_discovery._discover_via_wikipedia("sathaye")
    assert [row["name"] for row in rows] == ["Sathaye College"]
    assert rows[0]["code"] == ""


def test_nominatim_parser_extracts_name_and_city(monkeypatch):
    monkeypatch.setattr(
        college_discovery, "_http_get_json",
        lambda *a, **k: [
            {
                "display_name": "Sathaye College, Vile Parle, Mumbai, Maharashtra, India",
                "name": "Sathaye College",
                "address": {"city": "Mumbai", "state": "Maharashtra"},
            },
            {"display_name": "Some Park, Mumbai", "name": "Some Park",
             "address": {"city": "Mumbai"}},
        ],
    )
    rows = college_discovery._discover_via_nominatim("sathaye")
    assert len(rows) == 1
    assert rows[0]["name"] == "Sathaye College"
    assert rows[0]["city"] == "Mumbai"


def test_discovery_dedupes_against_catalog_and_repeats(db):
    saved = college_discovery._save_discovered(
        db,
        [
            {"name": "COEP Technological University, Pune", "short_name": "COEP",
             "code": "6006", "city": "Pune", "aliases": []},
            _vcet_row(),
            _vcet_row(),
        ],
        "ai",
    )
    assert [row.name for row in saved] == [_vcet_row()["name"]]
    assert db.query(CollegeDirectory).count() == 1
