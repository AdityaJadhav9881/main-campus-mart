"""
routers/colleges.py
===================
Maharashtra CET Cell college directory (College Network feature).

    GET /colleges?q=<search>&city=<city>   (public)

Returns CET/DTE colleges ranked by relevance across official name, short
alias ("COEP", "VJTI", "PICT"), DTE institute code, and city. Used by the
Sign Up / Profile college picker and the Discover "My College" filter.

Search order:
    1. the bundled CET catalog (cet_colleges.py);
    2. the `college_directory` cache of previously discovered colleges;
    3. on a full miss, on-demand discovery (Gemini Search grounding through
       the multi-key AI pool, then Wikipedia / Nominatim fallbacks) with the
       result saved to `college_directory` - see college_discovery.py.

Custom colleges: students whose institute is missing from the directory can
add their own entry in the app; the API stores plain college_name/code
strings, so custom picks round-trip without any extra server state. When
`allow_custom=true` is sent with a `q` that matches nothing (even after
discovery), the response echoes the typed text back as a `custom: true`
college so the picker can offer it as a "Use '<text>'" tile.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import college_discovery
from ..cet_colleges import CET_CITIES, CetCollege, college_to_dict, search_colleges
from ..database import get_db
from ..models import CollegeDirectory
from ..schemas import CollegeRead, CollegeSearchResponse

router = APIRouter(prefix="/colleges", tags=["colleges"])


@router.get(
    "",
    response_model=CollegeSearchResponse,
    summary="Search the Maharashtra CET Cell college directory",
)
@router.get(
    "/",
    response_model=CollegeSearchResponse,
    include_in_schema=False,
)
def list_colleges(
    q: str = Query(
        default="",
        max_length=120,
        description="Free-text query matched against college name, short "
                    "alias, DTE code, city and aliases (multi-word = AND). "
                    "Unknown colleges are discovered on demand and cached.",
    ),
    city: str = Query(
        default="",
        max_length=60,
        description="Optional city filter ('All' / blank = every campus).",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    allow_custom: bool = Query(
        default=False,
        description="When true and nothing matches (after discovery), echo q "
                    "back as a custom college entry so unlisted institutes "
                    "can sign up.",
    ),
    db: Session = Depends(get_db),
) -> CollegeSearchResponse:
    """Ranked college search for the picker sheet."""
    colleges: list[CollegeRead] = []
    seen: set[str] = set()

    def _add(college: CetCollege, custom: bool = False) -> None:
        name_key = college_discovery.normalize_text(college.name)
        code_key = f"code:{college.code.strip().lower()}" if college.code.strip() else ""
        if name_key in seen or (code_key and code_key in seen):
            return
        seen.add(name_key)
        if code_key:
            seen.add(code_key)
        colleges.append(CollegeRead(**college_to_dict(college, custom=custom)))

    # 1. Bundled CET catalog.
    for college in search_colleges(q=q, city=city, limit=limit):
        _add(college)

    query = q.strip()

    # 2. Previously discovered colleges (offline, instant).
    if query:
        for row in college_discovery.directory_search(
            db, q=q, city=city, limit=limit
        ):
            _add(college_discovery.directory_to_college(row))

    # 3. Full miss -> discover + cache (AI grounding, then web fallbacks).
    if not colleges and len(query) >= 3:
        for row in college_discovery.discover_colleges(db, query):
            _add(college_discovery.directory_to_college(row))

    if allow_custom and not colleges and query:
        # Unlisted institute: hand the typed text back as a pickable entry.
        custom = CetCollege(
            code="",
            name=query[:255],
            short_name=query[:60],
            city=(city or "Other").strip() or "Other",
        )
        _add(custom, custom=True)

    # City pills: canonical CET list + any cities the discovery cache added.
    canonical = {name.lower() for name in CET_CITIES}
    discovered_cities = sorted(
        {
            (row_city or "").strip()
            for (row_city,) in db.query(CollegeDirectory.city).distinct().all()
            if (row_city or "").strip()
            and (row_city or "").strip().lower() not in canonical
            and (row_city or "").strip().lower() != "other"
        }
    )

    colleges = colleges[:limit]
    return CollegeSearchResponse(
        colleges=colleges,
        cities=["All", *CET_CITIES, *discovered_cities],
        count=len(colleges),
    )
