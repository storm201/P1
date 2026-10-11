import os
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.models import IngestionJob, App, VerificationRun, VerificationCheck, VerificationSchedule
from app.services.verification import record_website_check
from app.services.scheduler import plan_scheduled_checks, claim_next_task, complete_task, get_scheduler_metrics
from app.services.release_sync import sync_github_releases, RequestBudget, sanitize_token
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


def send_alert_webhook(event: str, message: str, details: Dict[str, Any]) -> bool:
    """
    Sends configurable webhook notification when repeated failures indicate
    that scheduling or synchronization is unhealthy.
    Does not spam on transient single failures.
    """
    if not settings.ALERT_WEBHOOK_URL:
        return False

    payload = {
        "event": event,
        "message": sanitize_token(message),
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(settings.ALERT_WEBHOOK_URL, json=payload)
            return resp.status_code < 400
    except Exception as e:
        logger.error(f"Failed to deliver alert webhook: {e}")
        return False


def run_scheduler_cycle(
    db: Session,
    max_tasks: int = 50,
    worker_id: Optional[str] = None
) -> IngestionJob:
    """
    Executes a periodic verification scheduler cycle:
    1. Ensures eligible checks are planned without duplicates.
    2. Atomically claims eligible due tasks.
    3. Respects the 150 request budget for external calls.
    4. Records honest evidence for website and release checks.
    5. Updates schedule states with bounded exponential backoff.
    6. Triggers webhook alerts when consecutive failures exceed threshold.
    """
    if not worker_id:
        worker_id = f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"

    # Ensure eligible catalog items have schedules planned
    plan_scheduled_checks(db)

    job = IngestionJob(
        source="scheduled_verification_worker",
        status="RUNNING",
        started_at=datetime.utcnow(),
        items_processed=0,
        items_added=0,
        items_updated=0,
        requests_made=0,
        error_message=None
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    run = VerificationRun(
        run_type="worker_scheduled",
        status="RUNNING",
        started_at=datetime.utcnow(),
        summary=f"Automated verification cycle #{job.id} (worker {worker_id})"
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    budget = RequestBudget(limit=settings.SCHEDULER_REQUEST_BUDGET)
    consecutive_failures = 0
    cycle_errors = []

    try:
        tasks_processed = 0
        while tasks_processed < max_tasks and budget.can_request():
            task = claim_next_task(db, worker_id=worker_id)
            if not task:
                break  # No tasks currently due

            app = db.query(App).filter(App.id == task.app_id).first()
            if not app or app.is_delisted:
                complete_task(db, task.id, success=True)
                tasks_processed += 1
                continue

            success = False
            err_msg = None

            if task.check_type == "website_availability":
                try:
                    check = record_website_check(db, app, run=run)
                    budget.record_request(1)
                    if check.status == "SUCCESS":
                        success = True
                        consecutive_failures = 0
                    else:
                        success = False
                        err_msg = check.error_message or f"HTTP {check.http_status}"
                        consecutive_failures += 1
                except Exception as ex:
                    success = False
                    err_msg = f"Website check exception: {str(ex)}"
                    consecutive_failures += 1

            elif task.check_type == "release_sync":
                try:
                    res = sync_github_releases(db, app, budget=budget)
                    if res["status"] == "SUCCESS":
                        success = True
                        consecutive_failures = 0
                    elif res["status"] == "RATE_LIMITED":
                        # Rate limit reached; do not mark as permanent task failure, pause cycle
                        logger.warning("Worker paused due to GitHub rate limit.")
                        complete_task(db, task.id, success=False, error_message=res.get("message"))
                        break
                    elif res["status"] == "SKIPPED":
                        success = True
                    else:
                        success = False
                        err_msg = res.get("error") or "Release sync failed"
                        consecutive_failures += 1
                except Exception as ex:
                    success = False
                    err_msg = f"Release sync exception: {str(ex)}"
                    consecutive_failures += 1
            else:
                success = True

            complete_task(db, task.id, success=success, error_message=err_msg)
            job.items_processed += 1
            tasks_processed += 1
            if success:
                job.items_updated += 1
            else:
                if err_msg:
                    cycle_errors.append(f"{task.check_type} for app {app.slug}: {err_msg}")

            # Check consecutive failure threshold for alerts
            if consecutive_failures >= settings.ALERT_FAILURE_THRESHOLD:
                send_alert_webhook(
                    event="consecutive_verification_failures",
                    message=f"Worker encountered {consecutive_failures} consecutive verification failures.",
                    details={"recent_errors": cycle_errors[-3:], "job_id": job.id}
                )

        job.status = "COMPLETED"
        job.requests_made = budget.used
        job.completed_at = datetime.utcnow()
        run.status = "SUCCESS"
        run.completed_at = datetime.utcnow()
        if cycle_errors:
            job.error_message = sanitize_token("; ".join(cycle_errors[:3]))
        db.commit()
        logger.info(f"Worker cycle #{job.id} completed. Processed {job.items_processed} tasks, {budget.used} requests made.")

    except Exception as e:
        job.status = "FAILED"
        job.requests_made = budget.used
        job.completed_at = datetime.utcnow()
        job.error_message = sanitize_token(str(e))
        run.status = "FAILED"
        run.completed_at = datetime.utcnow()
        db.commit()
        logger.error(f"Worker cycle #{job.id} failed: {e}")

        send_alert_webhook(
            event="worker_cycle_fatal_error",
            message=f"Worker cycle fatal failure: {str(e)}",
            details={"job_id": job.id}
        )

    return job


def execute_verification_job(db: Session, max_apps: int = 50) -> IngestionJob:
    """Backwards-compatible wrapper that dispatches the scheduler cycle."""
    return run_scheduler_cycle(db, max_tasks=max_apps)


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run_scheduler_cycle(db, max_tasks=10)
    finally:
        db.close()
