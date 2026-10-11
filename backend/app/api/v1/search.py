from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models.models import App, Category
from app.schemas.schemas import SearchResponse, AppListItem, CategoryRead
from app.services.search import execute_hybrid_search

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
def search_apps(
    q: str = Query(..., min_length=1, description="Natural language search query or keywords"),
    platform: Optional[str] = Query(None, description="Filter by platform (e.g., windows, macos, linux, web)"),
    license_state: Optional[str] = Query(None, description="Filter by license state (e.g., confirmed_open_source)"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    results_raw, meta = execute_hybrid_search(
        db=db,
        raw_query=q,
        platform=platform,
        license_state=license_state,
        limit=limit
    )

    items: List[AppListItem] = []
    for r in results_raw:
        app: App = r["app"]
        primary_cat = CategoryRead.model_validate(app.primary_category) if app.primary_category else None
        caps = [c.capability for c in app.capabilities]

        item = AppListItem(
            id=app.id,
            slug=app.slug,
            name=app.name,
            summary=app.summary,
            homepage_url=app.homepage_url,
            repo_url=app.repo_url,
            license_state=app.license_state,
            license_spdx=app.license_spdx,
            platforms=app.platforms or [],
            primary_category=primary_cat,
            capabilities=caps,
            verification_status=r["verification_status"],
            latest_check_at=r["latest_check_at"],
            score=r["score"],
            match_sources=r["sources"]
        )
        items.append(item)

    # If results are empty, provide suggested categories
    suggested_categories: List[CategoryRead] = []
    if not items:
        # Suggest categories that user might explore
        suggested = db.query(Category).limit(6).all()
        suggested_categories = [CategoryRead.model_validate(c) for c in suggested]

    return SearchResponse(
        query=q,
        normalized_query=meta["clean_query"],
        intent=None,
        detected_categories=meta["detected_categories"],
        suggested_categories=suggested_categories,
        applied_filters=meta["applied_filters"],
        total_results=len(items),
        results=items
    )
