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
BASE_MOCK_PRICE = 100.0

# Multiplier applied to BASE_MOCK_PRICE per declared condition.
# Spec example: "Like New" -> 80% of the base mock value (= 80.0).
CONDITION_FACTORS = {
    "new": 1.00,
    "like new": 0.80,
    "good": 0.60,
    "fair": 0.40,
    "poor": 0.20,
}

# Fallback when the condition is missing/unknown - stay conservative.
_DEFAULT_FACTOR = 0.50


def price_agent(state: ProductState) -> dict:
    """Node: compute the AI suggested price.

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

    suggested_price = round(BASE_MOCK_PRICE * factor, 2)

    return {"suggested_price": suggested_price}
