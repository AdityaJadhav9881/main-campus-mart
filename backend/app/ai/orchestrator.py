"""
orchestrator.py
===============
LangGraph agent orchestrator for CampusMart AI (Phase 3, Task 3).

Builds and compiles the multi-agent graph:

    START --> Listing Intelligence --> Price Prediction -->
              Trust & Fraud Detection --> END

Each node is a plain function that accepts ProductState and returns a partial
state update; LangGraph merges updates and passes the growing state along the
single sequential path.

Phase 7 addition — RUNTIME AGENT TOGGLES
----------------------------------------
The React Admin Dashboard can enable/disable individual agents at runtime
(GET/PATCH /admin/ai-agents). Each graph node is wrapped by a gate that
checks the module-level AGENT_FLAGS dict; a disabled agent is skipped and a
safe default is written into the state instead:

    listing_intelligence    off -> extracted_category = "Uncategorized"
    price_prediction        off -> suggested_price   = None
    trust_fraud_detection  off -> trust_flag        = False
                                   trust_reason      = "...disabled..."

Exported symbols:
    `ai_orchestrator`   - the compiled graph, invoked by the API as:
                          result = ai_orchestrator.invoke({...raw fields...})
    `AGENT_KEYS`        - valid agent keys for the admin API
    `get_agent_flags()` / `set_agent_enabled()` / `reset_agent_flags()`
"""

import logging

from langgraph.graph import END, START, StateGraph

from .listing_agent import listing_agent
from .price_agent import price_agent
from .state import ProductState
from .trust_agent import trust_agent

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Runtime flags (module-level so every request worker shares one view)
# -----------------------------------------------------------------------------
AGENT_KEYS: tuple[str, ...] = (
    "listing_intelligence",
    "price_prediction",
    "trust_fraud_detection",
)

_AGENT_FLAGS: dict[str, bool] = {key: True for key in AGENT_KEYS}

# Category used when the listing-intelligence agent is disabled.
FALLBACK_CATEGORY = "Uncategorized"


def get_agent_flags() -> dict[str, bool]:
    """Return a copy of the current runtime agent flags (admin GET)."""
    return dict(_AGENT_FLAGS)


def set_agent_enabled(agent_key: str, enabled: bool) -> None:
    """Enable/disable one agent at runtime (admin PATCH).

    Raises:
        KeyError: unknown agent_key (caller maps to HTTP 404).
    """
    if agent_key not in _AGENT_FLAGS:
        raise KeyError(agent_key)
    _AGENT_FLAGS[agent_key] = bool(enabled)
    logger.warning("AI agent '%s' runtime flag set to %s", agent_key, enabled)


def reset_agent_flags() -> None:
    """Restore every agent to enabled (used by verification harnesses)."""
    for key in AGENT_KEYS:
        _AGENT_FLAGS[key] = True


# -----------------------------------------------------------------------------
# Gated node wrappers: skip disabled agents, write safe defaults
# -----------------------------------------------------------------------------
def _gated_listing(state: ProductState) -> dict:
    if not _AGENT_FLAGS["listing_intelligence"]:
        return {"extracted_category": FALLBACK_CATEGORY}
    return listing_agent(state)


def _gated_price(state: ProductState) -> dict:
    if not _AGENT_FLAGS["price_prediction"]:
        return {"suggested_price": None}  # type: ignore[dict-item]
    return price_agent(state)


def _gated_trust(state: ProductState) -> dict:
    if not _AGENT_FLAGS["trust_fraud_detection"]:
        return {
            "trust_flag": False,
            "trust_reason": "Trust & Fraud Detection agent disabled via admin control.",
        }
    return trust_agent(state)


# -----------------------------------------------------------------------------
# 1. Declare the state machine over the shared ProductState schema
# -----------------------------------------------------------------------------
builder = StateGraph(ProductState)

# -----------------------------------------------------------------------------
# 2. Add the gated agent nodes
#    (node IDs are snake_case; the human-readable names from the spec are:
#     "Listing Intelligence", "Price Prediction", "Trust & Fraud Detection")
# -----------------------------------------------------------------------------
builder.add_node("listing_intelligence", _gated_listing)
builder.add_node("price_prediction", _gated_price)
builder.add_node("trust_fraud_detection", _gated_trust)

# -----------------------------------------------------------------------------
# 3. Sequential edges: START -> Listing -> Price -> Trust -> END
# -----------------------------------------------------------------------------
builder.add_edge(START, "listing_intelligence")
builder.add_edge("listing_intelligence", "price_prediction")
builder.add_edge("price_prediction", "trust_fraud_detection")
builder.add_edge("trust_fraud_detection", END)

# -----------------------------------------------------------------------------
# 4. Compile once at import time (thread-safe, reused across all requests)
# -----------------------------------------------------------------------------
ai_orchestrator = builder.compile()
