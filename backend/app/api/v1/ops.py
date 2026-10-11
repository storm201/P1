from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, List
from app.config import settings
from app.database import get_db
from app.models.models import (
    CorrectionRequest, App, VerificationCheck, IngestionJob, VerificationSchedule
)
from app.schemas.schemas import (
    OpsStatusResponse, CorrectionRequestRead, CorrectionResolution
)
from app.services.scheduler import get_scheduler_metrics
from app.services.verification import derive_verification_status
from app.services.search import get_encoder_diagnostics

router = APIRouter()


def require_ops_token(authorization: Optional[str] = Header(None)):
    """Enforce OPS_TOKEN in Authorization header. If OPS_TOKEN is unset, fail closed."""
    if not settings.OPS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operations access disabled: OPS_TOKEN is not configured"
        )
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header"
        )

    expected = f"Bearer {settings.OPS_TOKEN}"
    if authorization != expected and authorization != settings.OPS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operations token"
        )


@router.get("/ops/status", response_model=OpsStatusResponse, dependencies=[Depends(require_ops_token)])
def get_ops_status(db: Session = Depends(get_db)):
    pending_corrections = db.query(CorrectionRequest).filter(CorrectionRequest.status == "PENDING").all()
    pending_count = len(pending_corrections)

    oldest_age = None
    if pending_corrections:
        oldest_time = min(c.submitted_at for c in pending_corrections)
        oldest_age = (datetime.utcnow() - oldest_time).total_seconds()

    total_apps = db.query(App).count()
    checks = db.query(VerificationCheck).all()
    total_checks = len(checks)

    checks_by_status = {}
    for c in checks:
        checks_by_status[c.status] = checks_by_status.get(c.status, 0) + 1

    last_job = db.query(IngestionJob).order_by(IngestionJob.started_at.desc()).first()
    last_worker_run = last_job.completed_at if last_job else None

    # Scheduler cycle timestamps
    last_completed_job = db.query(IngestionJob).filter(
        IngestionJob.source == "scheduled_verification_worker",
        IngestionJob.status == "COMPLETED"
    ).order_by(IngestionJob.completed_at.desc()).first()
    last_scheduler_cycle = last_completed_job.completed_at if last_completed_job else None
    next_expected_cycle = (
        last_scheduler_cycle + timedelta(hours=settings.SCHEDULER_INTERVAL_HOURS)
        if last_scheduler_cycle else None
    )

    # Detailed scheduler metrics
    sched_metrics = get_scheduler_metrics(db)

    # Count stale apps accurately using standard verification status derivation
    apps = db.query(App).filter(App.is_delisted == False).all()
    stale_count = 0
    for app in apps:
        app_checks = [c for c in checks if c.app_id == app.id]
        if derive_verification_status(app_checks) == "STALE":
            stale_count += 1

    # Most recent successful and failed release sync checks
    succ_sync = db.query(VerificationCheck).filter(
        VerificationCheck.check_type.in_(["release_metadata", "release_sync"]),
        VerificationCheck.status == "SUCCESS"
    ).order_by(VerificationCheck.checked_at.desc()).first()

    fail_sync = db.query(VerificationCheck).filter(
        VerificationCheck.check_type.in_(["release_metadata", "release_sync"]),
        VerificationCheck.status == "FAILED"
    ).order_by(VerificationCheck.checked_at.desc()).first()

    # Rate-limited jobs / checks count
    rate_limited_count = db.query(VerificationSchedule).filter(
        VerificationSchedule.last_error.like("%rate limit%")
    ).count()

    recent_jobs = db.query(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(5).all()
    jobs_data = [
        {
            "id": j.id,
            "source": j.source,
            "status": j.status,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "items_processed": j.items_processed,
            "items_added": j.items_added,
            "requests_made": j.requests_made,
            "error_message": j.error_message
        }
        for j in recent_jobs
    ]

    return OpsStatusResponse(
        worker_status="IDLE" if (not last_job or last_job.status != "RUNNING") else "RUNNING",
        last_worker_run=last_worker_run,
        pending_corrections_count=pending_count,
        oldest_pending_age_seconds=round(oldest_age, 2) if oldest_age else None,
        total_apps=total_apps,
        total_checks=total_checks,
        checks_by_status=checks_by_status,
        recent_jobs=jobs_data,
        last_scheduler_cycle=last_scheduler_cycle,
        next_expected_cycle=next_expected_cycle,
        pending_jobs=sched_metrics["pending_tasks"],
        running_jobs=sched_metrics["running_tasks"],
        failed_jobs=sched_metrics["failed_tasks"],
        oldest_pending_job_age_seconds=sched_metrics["oldest_pending_age_seconds"],
        jobs_retried=sched_metrics["retried_tasks"],
        jobs_skipped_rate_limit=rate_limited_count,
        stale_apps_count=stale_count,
        most_recent_successful_sync=succ_sync.checked_at if succ_sync else None,
        most_recent_sync_failure=fail_sync.error_message if fail_sync else None,
        recent_sanitized_failures=sched_metrics["recent_failures"],
        encoder_diagnostics=get_encoder_diagnostics(),
    )


@router.get("/ops/corrections", response_model=List[CorrectionRequestRead], dependencies=[Depends(require_ops_token)])
def list_corrections(status_filter: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(CorrectionRequest)
    if status_filter:
        query = query.filter(CorrectionRequest.status == status_filter)
    return [CorrectionRequestRead.model_validate(c) for c in query.order_by(CorrectionRequest.submitted_at.desc()).all()]


@router.post("/ops/corrections/{request_id}/resolve", response_model=CorrectionRequestRead, dependencies=[Depends(require_ops_token)])
def resolve_correction(
    request_id: int,
    payload: CorrectionResolution,
    db: Session = Depends(get_db)
):
    req = db.query(CorrectionRequest).filter(CorrectionRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Correction request not found")

    req.status = payload.status
    req.resolution_notes = payload.resolution_notes
    req.resolved_at = datetime.utcnow()

    # If operator decides to delist the app without destroying audit trail
    if payload.delist_app and req.app_id:
        app = db.query(App).filter(App.id == req.app_id).first()
        if app:
            app.is_delisted = True

    db.commit()
    db.refresh(req)
    return CorrectionRequestRead.model_validate(req)
