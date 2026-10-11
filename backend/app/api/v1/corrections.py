import html
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models.models import CorrectionRequest, App
from app.schemas.schemas import CorrectionRequestCreate, CorrectionRequestRead

router = APIRouter()


@router.post("/corrections", response_model=CorrectionRequestRead, status_code=status.HTTP_201_CREATED)
def submit_correction_request(payload: CorrectionRequestCreate, db: Session = Depends(get_db)):
    # Sanitize inputs - plain text escaping
    safe_reason = html.escape(payload.reason.strip())
    safe_identifier = html.escape(payload.app_identifier.strip())
    safe_email = html.escape(payload.contact_email.strip()) if payload.contact_email else None

    # Check if identifier matches an existing app slug or name
    matched_app = db.query(App).filter(
        (App.slug == safe_identifier.lower()) | (App.name == safe_identifier)
    ).first()

    req = CorrectionRequest(
        app_id=matched_app.id if matched_app else None,
        app_identifier=safe_identifier,
        request_type=payload.request_type,
        reason=safe_reason,
        contact_email=safe_email,
        status="PENDING",
        submitted_at=datetime.utcnow()
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    return CorrectionRequestRead.model_validate(req)
