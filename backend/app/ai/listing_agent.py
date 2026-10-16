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
# render a fixed filter list). Matches the vision engine's vocabulary
# (vision_master.VALID_CATEGORIES) so POST /products/analyze-images and the
# feed chips always agree.
CATEGORY_ACADEMIC = "Academic Material"
CATEGORY_ELECTRONICS = "Electronics"
CATEGORY_LAB = "Lab Gear & Instruments"
CATEGORY_STATIONERY = "Stationery"
CATEGORY_HOSTEL = "Hostel & Lifestyle"
CATEGORY_OTHER = "Other"

# First match wins: specific buckets are checked BEFORE the generic ones so
# "engineering lab notebook" lands in Stationery rather than Electronics.
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CATEGORY_ACADEMIC,
        ("book", "textbook", "math", "notes", "manual", "guide", "dictionary",
         "edition", "semester", "syllabus", "reference"),
    ),
    (
        CATEGORY_LAB,
        ("multimeter", "drafter", "oscilloscope", "solder", "lab", "protractor",
         "vernier", "calliper", "caliper", "microscope", "instrument", "sensor",
         "breadboard", "power supply", "optical"),
    ),
    (
        CATEGORY_STATIONERY,
        ("pen", "pencil", "marker", "highlighter", "refill", "sticky", "geometry",
         "eraser", "sharpener", "file", "folder", "stapler", "scale", "ruler"),
    ),
    (
        CATEGORY_HOSTEL,
        ("bedsheet", "pillow", "mug", "lamp", "hostel", "curtain", "mattress",
         "bucket", "fan", "mat", "hanger", "cupboard"),
    ),
    (
        CATEGORY_ELECTRONICS,
        ("laptop", "phone", "calculator", "speaker", "headphone", "earbud",
         "camera", "watch", "drone", "esp32", "arduino", "raspberry", "chip",
         "battery", "charger", "monitor", "keyboard", "mouse", "tablet",
         "electronics", "bluetooth", "wifi", "usb", "projector", "tv"),
    ),
)


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
    #   + embedding_classifier(state["title"] + state["description"])
    haystack = f"{state['title']} {state.get('description', '')}".lower()

    category = CATEGORY_OTHER  # broad browse bucket when nothing matches
    for candidate, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            category = candidate
            break

    # LangGraph nodes return partial state; the reducer merges this key.
    return {"extracted_category": category}
