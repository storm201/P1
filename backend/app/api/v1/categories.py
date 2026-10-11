from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.models import Category
from app.schemas.schemas import CategoryRead, CategoryTree

router = APIRouter()


@router.get("/categories", response_model=List[CategoryRead])
def list_categories(db: Session = Depends(get_db)):
    categories = db.query(Category).all()
    return [CategoryRead.model_validate(c) for c in categories]


@router.get("/categories/tree", response_model=List[CategoryTree])
def get_category_tree(db: Session = Depends(get_db)):
    root_categories = db.query(Category).filter(Category.parent_id == None).all()
    return [CategoryTree.model_validate(c) for c in root_categories]


@router.get("/categories/{slug}", response_model=CategoryRead)
def get_category_by_slug(slug: str, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.slug == slug).first()
    if not cat:
        raise HTTPException(status_code=404, detail=f"Category '{slug}' not found")
    return CategoryRead.model_validate(cat)
