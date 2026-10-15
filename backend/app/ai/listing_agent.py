"""
listing_agent.py
================
Listing Intelligence agent (Phase 3 - MOCK IMPLEMENTATION).

Responsibility
--------------
Classify the listing into a marketplace category. Today this is a rule-based
heuristic over the title; the production version will combine:

    * YOLOv8 object detection on `state["image_url"]`
      -> load with:  from ultralytics import YOLO
                     model = YOLO("models/listing_classifier.pt")   # .pt file
    * NLP/embedding classifier over the title + description

SWAP POINT: replace the body of `listing_agent()` with the model inference
call - the input/output contract (ProductState -> partial state) stays the
same, so the orchestrator needs no changes.
"""

from .state import ProductState

# Categories the marketplace supports (kept explicit so downstream UI can
# render a fixed filter list).
CATEGORY_ACADEMIC = "Academic Material"
CATEGORY_ELECTRONICS = "Electronics"

# Title keywords that identify books / course material.
_ACADEMIC_KEYWORDS = ("book", "math")


def listing_agent(state: ProductState) -> dict:
    """Node: extract the product category from the raw listing.

    Args:
        state: Current ProductState (at minimum title/description/image_url).

    Returns:
        Partial state update: {"extracted_category": <str>}
    """
    # ---- MOCK / heuristic implementation ------------------------------------
    # TODO(Phase 3 real models): replace with
    #   detections = model(state["image_url"])       # YOLOv8 .pt inference
    #   + embedding_classifier(state["title"] + " " + state["description"])
    title_lower = state["title"].lower()
    if any(keyword in title_lower for keyword in _ACADEMIC_KEYWORDS):
        category = CATEGORY_ACADEMIC
    else:
        category = CATEGORY_ELECTRONICS

    # LangGraph nodes return partial state; the reducer merges this key.
    return {"extracted_category": category}
