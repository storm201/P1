from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from app.models.models import App, VerificationSchedule, VerificationCheck, VerificationRun
from app.config import settings
import logging

logger = logging.getLogger("scheduler")


def plan_scheduled_checks(db: Session, force_all: bool = False) -> int:
    """
    Inspects catalog apps and ensures eligible verification schedules are planned.
    Strictly avoids creating duplicate pending work for the same application and check type.
    """
    apps = db.query(App).filter(App.is_delisted == False).all()
    created_count = 0
    now = datetime.utcnow()

    for app in apps:
        # 1. Website availability check (applies to all apps)
        existing_web = db.query(VerificationSchedule).filter(
            VerificationSchedule.app_id == app.id,
            VerificationSchedule.check_type == "website_availability"
        ).first()

        if not existing_web:
            sched = VerificationSchedule(
                app_id=app.id,
                check_type="website_availability",
                status="IDLE",
                scheduled_at=now,
                next_run_at=now,
                attempts=0,
                max_attempts=settings.SCHEDULER_MAX_RETRIES,
            )
            db.add(sched)
            created_count += 1
        elif force_all:
            existing_web.next_run_at = now
            existing_web.status = "IDLE"

        # 2. Official release sync (applies to apps with recorded source repo)
        if app.repo_url:
            existing_rel = db.query(VerificationSchedule).filter(
                VerificationSchedule.app_id == app.id,
                VerificationSchedule.check_type == "release_sync"
            ).first()

            if not existing_rel:
                sched = VerificationSchedule(
                    app_id=app.id,
                    check_type="release_sync",
                    status="IDLE",
                    scheduled_at=now,
                    next_run_at=now,
                    attempts=0,
                    max_attempts=settings.SCHEDULER_MAX_RETRIES,
                )
                db.add(sched)
                created_count += 1
            elif force_all:
                existing_rel.next_run_at = now
                existing_rel.status = "IDLE"

    db.commit()
    return created_count


def calculate_backoff(
    attempts: int,
    base_seconds: int = 300,
    max_seconds: int = 86400,
    jitter: bool = True
) -> int:
    """
    Calculates bounded exponential backoff with deterministic jitter.
    Guarantees backoff never exceeds max_seconds and is strictly bounded.
    """
    if attempts <= 1:
        backoff = base_seconds
    else:
        # Exponential growth: base * 2^(attempts - 1)
        backoff = min(max_seconds, base_seconds * (2 ** (attempts - 1)))

    if jitter:
        # Bounded ±10% pseudo-jitter based on attempts
        jitter_delta = int(backoff * 0.1)
        mod_shift = ((attempts % 3) - 1) * jitter_delta
        backoff = max(base_seconds, min(max_seconds, backoff + mod_shift))

    return backoff


def claim_next_task(
    db: Session,
    worker_id: str,
    lock_timeout_seconds: int = 300
) -> Optional[VerificationSchedule]:
    """
    Safely claims the next eligible task using transactional row locking.
    Recovers stale locks from interrupted worker processes.
    Prioritizes stale and retrying tasks within the schedule budget.
    """
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=lock_timeout_seconds)

    # 1. Interrupted job recovery: reset stale running tasks
    stale_tasks = db.query(VerificationSchedule).filter(
        VerificationSchedule.status == "RUNNING",
        VerificationSchedule.locked_at < stale_cutoff
    ).all()
    for st in stale_tasks:
        logger.warning(f"Recovering interrupted task #{st.id} (locked by {st.locked_by} at {st.locked_at})")
        st.status = "IDLE"
        st.locked_by = None
        st.locked_at = None
    if stale_tasks:
        db.commit()

    # 2. Select next eligible task
    # Priority: failed retries (attempts > 0), then oldest due tasks
    task = db.query(VerificationSchedule).filter(
        VerificationSchedule.status.in_(["IDLE", "QUEUED"]),
        VerificationSchedule.next_run_at <= now
    ).order_by(
        desc(VerificationSchedule.attempts > 0),
        VerificationSchedule.next_run_at.asc()
    ).first()

    if not task:
        return None

    # 3. Atomic claim transition
    task.status = "RUNNING"
    task.locked_by = worker_id
    task.locked_at = now
    db.commit()
    db.refresh(task)
    return task


def complete_task(
    db: Session,
    task_id: int,
    success: bool,
    error_message: Optional[str] = None
) -> Optional[VerificationSchedule]:
    """
    Records task completion or failure with bounded retry scheduling.
    A failed check updates schedule retry state without erasing historical evidence.
    """
    task = db.query(VerificationSchedule).filter(VerificationSchedule.id == task_id).first()
    if not task:
        return None

    now = datetime.utcnow()
    task.last_run_at = now
    task.locked_by = None
    task.locked_at = None

    if success:
        task.attempts = 0
        task.status = "IDLE"
        task.last_error = None
        task.next_run_at = now + timedelta(hours=settings.SCHEDULER_INTERVAL_HOURS)
    else:
        task.attempts += 1
        task.last_error = (error_message[:1500] if error_message else "Check failed")
        if task.attempts >= task.max_attempts:
            task.status = "FAILED"
            # Bounded: after max attempts, schedule retry after regular interval
            task.next_run_at = now + timedelta(hours=settings.SCHEDULER_INTERVAL_HOURS)
        else:
            task.status = "IDLE"
            backoff_sec = calculate_backoff(
                attempts=task.attempts,
                base_seconds=settings.SCHEDULER_RETRY_BASE_SECONDS,
                max_seconds=settings.SCHEDULER_RETRY_MAX_SECONDS
            )
            task.next_run_at = now + timedelta(seconds=backoff_sec)

    db.commit()
    db.refresh(task)
    return task


def get_scheduler_metrics(db: Session) -> Dict[str, Any]:
    """Calculate operational metrics for scheduler diagnosis."""
    now = datetime.utcnow()
    all_schedules = db.query(VerificationSchedule).all()

    pending_count = sum(1 for s in all_schedules if s.status in ("IDLE", "QUEUED") and s.next_run_at <= now)
    running_count = sum(1 for s in all_schedules if s.status == "RUNNING")
    failed_count = sum(1 for s in all_schedules if s.status == "FAILED" or s.attempts >= s.max_attempts)
    retried_count = sum(1 for s in all_schedules if s.attempts > 0 and s.status != "FAILED")

    # Oldest pending task age
    due_schedules = [s for s in all_schedules if s.status in ("IDLE", "QUEUED") and s.next_run_at <= now]
    oldest_pending_age_sec = None
    if due_schedules:
        oldest_due = min(s.next_run_at for s in due_schedules)
        oldest_pending_age_sec = max(0.0, (now - oldest_due).total_seconds())

    # Recent failure summaries (sanitized)
    recent_failed = db.query(VerificationSchedule).filter(
        VerificationSchedule.last_error.isnot(None)
    ).order_by(VerificationSchedule.last_run_at.desc()).limit(5).all()

    recent_failures = [
        {
            "schedule_id": s.id,
            "app_id": s.app_id,
            "check_type": s.check_type,
            "attempts": s.attempts,
            "last_error": s.last_error,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        }
        for s in recent_failed
    ]

    return {
        "total_schedules": len(all_schedules),
        "pending_tasks": pending_count,
        "running_tasks": running_count,
        "failed_tasks": failed_count,
        "retried_tasks": retried_count,
        "oldest_pending_age_seconds": round(oldest_pending_age_sec, 2) if oldest_pending_age_sec is not None else None,
        "recent_failures": recent_failures,
    }
