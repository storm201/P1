from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.models.models import App, VerificationCheck
from app.schemas.schemas import (
    AppDetail, AppListItem, VerificationStatusSummary, VerificationCheckRead,
    CategoryRead, AppCapabilityRead, ReleaseRead
)
from app.services.verification import derive_verification_status, record_website_check

router = APIRouter()


def build_app_detail(app: App, db: Session) -> AppDetail:
    checks = db.query(VerificationCheck).filter(VerificationCheck.app_id == app.id).order_by(VerificationCheck.checked_at.desc()).all()
    overall_status = derive_verification_status(checks)

    web_checks = [c for c in checks if c.check_type == "website_availability"]
    repo_checks = [c for c in checks if c.check_type == "repo_metadata"]
    release_checks = [c for c in checks if c.check_type in ("release_availability", "release_metadata", "release_sync")]

    latest_web = web_checks[0] if web_checks else None
    latest_repo = repo_checks[0] if repo_checks else None
    latest_rel = release_checks[0] if release_checks else None

    v_summary = VerificationStatusSummary(
        overall_status=overall_status,
        website_check=VerificationCheckRead.model_validate(latest_web) if latest_web else None,
        repo_check=VerificationCheckRead.model_validate(latest_repo) if latest_repo else None,
        release_check=VerificationCheckRead.model_validate(latest_rel) if latest_rel else None,
        all_checks=[VerificationCheckRead.model_validate(c) for c in checks]
    )

    primary_cat = CategoryRead.model_validate(app.primary_category) if app.primary_category else None
    all_cats = [CategoryRead.model_validate(ac.category) for ac in app.categories if ac.category]
    caps = [AppCapabilityRead.model_validate(c) for c in app.capabilities]
    rels = [ReleaseRead.model_validate(r) for r in app.releases]

    return AppDetail(
        id=app.id,
        slug=app.slug,
        name=app.name,
        summary=app.summary,
        description=app.description,
        homepage_url=app.homepage_url,
        repo_url=app.repo_url,
        license_state=app.license_state,
        license_spdx=app.license_spdx,
        platforms=app.platforms or [],
        is_delisted=app.is_delisted,
        primary_category=primary_cat,
        categories=all_cats,
        capabilities=caps,
        releases=rels,
        verification_summary=v_summary,
        created_at=app.created_at,
        updated_at=app.updated_at
    )


@router.get("/apps", response_model=List[AppListItem])
def list_apps(
    platform: Optional[str] = Query(None),
    license_state: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(App).filter(App.is_delisted == False)

    if license_state:
        query = query.filter(App.license_state == license_state)

    apps = query.limit(limit).all()
    results = []

    for app in apps:
        if platform and platform.lower() not in [p.lower() for p in (app.platforms or [])]:
            continue

        checks = db.query(VerificationCheck).filter(VerificationCheck.app_id == app.id).all()
        v_status = derive_verification_status(checks)
        latest_check = max([c.checked_at for c in checks]) if checks else None

        results.append(AppListItem(
            id=app.id,
            slug=app.slug,
            name=app.name,
            summary=app.summary,
            homepage_url=app.homepage_url,
            repo_url=app.repo_url,
            license_state=app.license_state,
            license_spdx=app.license_spdx,
            platforms=app.platforms or [],
            primary_category=CategoryRead.model_validate(app.primary_category) if app.primary_category else None,
            capabilities=[c.capability for c in app.capabilities],
            verification_status=v_status,
            latest_check_at=latest_check,
            score=None,
            match_sources=[]
        ))

    return results


@router.get("/apps/{slug}", response_model=AppDetail)
def get_app_by_slug(slug: str, db: Session = Depends(get_db)):
    app = db.query(App).filter(App.slug == slug, App.is_delisted == False).first()
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{slug}' not found")
    return build_app_detail(app, db)


@router.get("/apps/{slug}/verification", response_model=VerificationStatusSummary)
def get_app_verification(slug: str, db: Session = Depends(get_db)):
    app = db.query(App).filter(App.slug == slug, App.is_delisted == False).first()
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{slug}' not found")

    checks = db.query(VerificationCheck).filter(VerificationCheck.app_id == app.id).order_by(VerificationCheck.checked_at.desc()).all()
    overall_status = derive_verification_status(checks)

    web_checks = [c for c in checks if c.check_type == "website_availability"]
    repo_checks = [c for c in checks if c.check_type == "repo_metadata"]
    release_checks = [c for c in checks if c.check_type in ("release_availability", "release_metadata", "release_sync")]

    return VerificationStatusSummary(
        overall_status=overall_status,
        website_check=VerificationCheckRead.model_validate(web_checks[0]) if web_checks else None,
        repo_check=VerificationCheckRead.model_validate(repo_checks[0]) if repo_checks else None,
        release_check=VerificationCheckRead.model_validate(release_checks[0]) if release_checks else None,
        all_checks=[VerificationCheckRead.model_validate(c) for c in checks]
    )


@router.post("/apps/{slug}/verify", response_model=VerificationCheckRead)
def trigger_real_website_check(slug: str, db: Session = Depends(get_db)):
    """Perform on-demand real website check and return the fresh stored record."""
    app = db.query(App).filter(App.slug == slug).first()
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{slug}' not found")

    check = record_website_check(db, app)
    return VerificationCheckRead.model_validate(check)
