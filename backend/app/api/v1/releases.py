from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.models import App, AppRelease
from app.schemas.schemas import ReleaseRead

router = APIRouter()


@router.get("/apps/{slug}/releases", response_model=List[ReleaseRead])
def get_app_releases(slug: str, db: Session = Depends(get_db)):
    app = db.query(App).filter(App.slug == slug, App.is_delisted == False).first()
    if not app:
        raise HTTPException(status_code=404, detail=f"Application '{slug}' not found")

    releases = db.query(AppRelease).filter(AppRelease.app_id == app.id).order_by(AppRelease.published_at.desc()).all()
    return [ReleaseRead.model_validate(r) for r in releases]
