"""
price_agent.py
==============
Price Prediction agent (Phase 3 - MOCK IMPLEMENTATION).

Responsibility
--------------
Estimate a fair-value price for the listing. The production version will run
a Scikit-learn regressor trained on historical campus sales:

    import joblib
    model = joblib.load("models/price_regressor.pkl")   # .pkl file
    suggested = float(model.predict([[features]]))[0]

Features the real model will consume: extracted_category, condition, age,
image embeddings (from YOLO), and market demand.

SWAP POINT: replace the heuristic inside `price_agent()` with the joblib
inference call - the input/output contract stays identical.
"""

from .state import ProductState

# ---------------------------------------------------------------------------
# MOCK pricing table (replace with the trained regressor in a later phase)
# ---------------------------------------------------------------------------
# All amounts are INDIAN RUPEES (₹) - the marketplace prices exclusively in
# INR (Task 7). `BASE_MOCK_PRICE` is the default category base; the per-
# category table below keeps a used textbook around ₹250-450 while still
# leaving room for gadgets.
BASE_MOCK_PRICE = 500.0

# Category -> fair-value base in ₹ BEFORE the condition factor. Keep in sync
# with the client mirror (frontend/lib/services/ai_price_estimate.dart).
CATEGORY_BASE_PRICE_INR: dict[str, float] = {
    "Electronics": 1500.0,
    "Academic Material": 500.0,
    "Lab Gear & Instruments": 600.0,
    "Stationery": 100.0,
    "Hostel & Lifestyle": 400.0,
}

# Multiplier applied to the category base per declared condition.
# "Like New" -> 80% of the base, "Good" -> 60%, and so on.
CONDITION_FACTORS = {
    "new": 1.00,
    "like new": 0.80,
    "good": 0.60,
    "fair": 0.40,
    "poor": 0.20,
}

# Fallback when the condition is missing/unknown - stay conservative.
_DEFAULT_FACTOR = 0.50


def base_price_for(category: str | None) -> float:
    """₹ fair-value base for a marketplace category (unknown -> default)."""
    if not category:
        return BASE_MOCK_PRICE
    return CATEGORY_BASE_PRICE_INR.get(category.strip(), BASE_MOCK_PRICE)


def price_agent(state: ProductState) -> dict:
    """Node: compute the AI suggested price (INR).

    Args:
        state: Current ProductState (condition + category already extracted).

    Returns:
        Partial state update: {"suggested_price": <float>}
    """
    # ---- MOCK / heuristic implementation ------------------------------------
    # TODO(Phase 3 real models): replace with
    #   suggested = float(model.predict([feature_vector(state)]))[0]
    condition = state["condition"].strip().lower()
    factor = CONDITION_FACTORS.get(condition, _DEFAULT_FACTOR)

    suggested_price = round(base_price_for(state.get("extracted_category")) * factor, 2)

    return {"suggested_price": suggested_price}
