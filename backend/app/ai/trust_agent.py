"""
trust_agent.py
==============
Trust & Fraud Detection agent (Phase 3 - MOCK IMPLEMENTATION).

Responsibility
--------------
Scan the listing text for fraud/scam indicators. A positive flag causes the
API to store the product with status='flagged', which keeps it OUT of the
public GET /products/ feed until a human moderator reviews it.

Production versions will combine:
    * Keyword/regex rules (below - cheap, always-on first pass)
    * A Scikit-learn text classifier:  joblib.load("models/fraud_tfidf.pkl")
    * Seller trust_score history (users.trust_score) as a features input

SWAP POINT: append the ML classifier score next to the keyword check.
"""

import re

from .state import ProductState

# Phrases strongly associated with marketplace scams (kept lowercase).
# Matched with word-boundary-aware regex so partial words do not trip them.
FRAUD_PHRASES = (
    "urgent wire transfer",
    "free money",
)


def trust_agent(state: ProductState) -> dict:
    """Node: evaluate the listing for fraud indicators.

    Args:
        state: Current ProductState (description is the primary signal;
               title is included as a secondary signal because scam artists
               often hide keywords there too).

    Returns:
        Partial state update:
            {"trust_flag": <bool>, "trust_reason": <str>}
    """
    # ---- MOCK / rule-based implementation -----------------------------------
    # TODO(Phase 3 real models): combine with
    #   ml_score = fraud_classifier.predict_proba([description])[0][1]
    haystack = f"{state['title']} {state['description']}".lower()

    for phrase in FRAUD_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", haystack):
            return {
                "trust_flag": True,
                "trust_reason": (
                    f"Fraud indicator detected: suspicious phrase "
                    f"'{phrase}' appears in the listing text."
                ),
            }

    return {
        "trust_flag": False,
        "trust_reason": "No fraud indicators detected in the listing text.",
    }
