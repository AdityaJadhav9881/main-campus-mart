"""
state.py
========
Shared state contract for the CampusMart AI multi-agent pipeline (Phase 3).

`ProductState` is the single TypedDict that flows through the LangGraph
orchestrator. Every agent reads the raw listing fields and appends its own
output by returning a PARTIAL state dictionary (LangGraph merges it into the
central state after each node).

Data flow:
    API payload --> [Listing Intelligence] --> [Price Prediction] -->
    [Trust & Fraud Detection] --> final state saved to the Product row.
"""

from typing import TypedDict


class ProductState(TypedDict):
    # -------------------------------------------------------------------------
    # Inputs - raw listing data supplied by POST /products/
    # -------------------------------------------------------------------------
    title: str               # listing title, e.g. "Calculus Textbook"
    description: str         # free-text seller description (scanned for fraud)
    image_url: str           # photo URL - future YOLO .pt model consumes this
    condition: str           # seller-declared condition, e.g. "Like New"
    age: str                 # item age hint, e.g. "2 years" (AI input only,
                             # NOT persisted to the Product table)

    # -------------------------------------------------------------------------
    # Outputs - written by the specialized agents
    # -------------------------------------------------------------------------
    extracted_category: str  # listing_agent    -> "Academic Material" | "Electronics"
    suggested_price: float   # price_agent      -> AI fair-value estimate
    trust_flag: bool         # trust_agent      -> True if fraud indicators found
    trust_reason: str        # trust_agent      -> human-readable justification
