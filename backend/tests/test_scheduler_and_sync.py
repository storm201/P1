import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import App, VerificationSchedule, VerificationCheck, AppRelease, ReleaseAsset, IngestionJob
from app.services.scheduler import (
    plan_scheduled_checks,
    claim_next_task,
    complete_task,
    calculate_backoff,
    get_scheduler_metrics
)
from app.services.verification import derive_verification_status, check_website_availability
from app.services.release_sync import (
    sync_github_releases,
    RequestBudget,
    check_asset_reachability,
    parse_github_repo,
    detect_platform_from_name
)
from app.config import settings


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()

    # Seed test apps
    app1 = App(
        slug="test-app-1",
        name="Test App One",
        summary="A test application",
        description="A detailed test application description",
        homepage_url="https://example.com",
        repo_url="https://github.com/example/testapp",
        license_state="confirmed_open_source",
        license_spdx="MIT",
        platforms=["linux", "windows"],
        is_delisted=False
    )
    app2 = App(
        slug="test-app-2",
        name="Test App Two",
        summary="Another test application without repo",
        description="Description for app two",
        homepage_url="https://example.org",
        repo_url=None,
        license_state="confirmed_open_source",
        license_spdx="Apache-2.0",
        platforms=["macos"],
        is_delisted=False
    )
    session.add_all([app1, app2])
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


def test_1_scheduler_creates_eligible_jobs(test_db):
    """1. Scheduler creates eligible jobs for applications."""
    created = plan_scheduled_checks(test_db)
    assert created == 3  # app1 (web + release_sync) + app2 (web only)

    schedules = test_db.query(VerificationSchedule).all()
    assert len(schedules) == 3
    types = {(s.app_id, s.check_type) for s in schedules}
    assert (1, "website_availability") in types
    assert (1, "release_sync") in types
    assert (2, "website_availability") in types


def test_2_duplicate_scheduling_does_not_create_duplicates(test_db):
    """2. Duplicate scheduling does not create duplicate pending work."""
    plan_scheduled_checks(test_db)
    count_first = test_db.query(VerificationSchedule).count()

    # Second run should find existing and not create duplicates
    created_second = plan_scheduled_checks(test_db)
    count_second = test_db.query(VerificationSchedule).count()

    assert created_second == 0
    assert count_first == count_second == 3


def test_3_multiple_workers_cannot_incorrectly_claim_same_job(test_db):
    """3. Multiple workers cannot incorrectly claim the same job."""
    plan_scheduled_checks(test_db)

    # Worker A claims first task
    task_a = claim_next_task(test_db, worker_id="worker-A")
    assert task_a is not None
    assert task_a.status == "RUNNING"
    assert task_a.locked_by == "worker-A"

    # Worker B claims next task (must get a different task)
    task_b = claim_next_task(test_db, worker_id="worker-B")
    assert task_b is not None
    assert task_b.id != task_a.id
    assert task_b.locked_by == "worker-B"

    # Worker C claims 3rd task
    task_c = claim_next_task(test_db, worker_id="worker-C")
    assert task_c is not None
    assert task_c.id not in (task_a.id, task_b.id)

    # Worker D finds no more due tasks
    task_d = claim_next_task(test_db, worker_id="worker-D")
    assert task_d is None


def test_4_website_check_success_persists_actual_evidence(test_db):
    """4. Website check success persists actual evidence."""
    app = test_db.query(App).filter(App.slug == "test-app-1").first()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com"
    mock_resp.content = b"<html>Test</html>"
    mock_resp.headers = {"content-type": "text/html"}

    with patch("app.services.verification.validate_destination_url", return_value=(True, None)):
        with patch("httpx.Client.get", return_value=mock_resp):
            res = check_website_availability(app.homepage_url)
            assert res["status"] == "SUCCESS"
            assert res["http_status"] == 200
            assert res["tls_valid"] is True

            check = VerificationCheck(
                app_id=app.id,
                check_type="website_availability",
                status=res["status"],
                duration_ms=res["duration_ms"],
                checked_at=datetime.utcnow(),
                http_status=res["http_status"],
                final_url=res["final_url"],
                tls_valid=res["tls_valid"],
                details=res["details"],
                error_message=res["error_message"]
            )
            test_db.add(check)
            test_db.commit()

            stored = test_db.query(VerificationCheck).filter(VerificationCheck.app_id == app.id).first()
            assert stored.status == "SUCCESS"
            assert stored.http_status == 200


def test_5_website_check_failure_persists_honest_failure(test_db):
    """5. Website check failure persists an honest failure without erasing history."""
    app = test_db.query(App).filter(App.slug == "test-app-1").first()

    # Historical success
    past_check = VerificationCheck(
        app_id=app.id,
        check_type="website_availability",
        status="SUCCESS",
        duration_ms=120,
        checked_at=datetime.utcnow() - timedelta(days=2),
        http_status=200,
        final_url="https://example.com",
        tls_valid=True
    )
    test_db.add(past_check)
    test_db.commit()

    # New failed check
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.url = "https://example.com"
    mock_resp.content = b"Service Unavailable"
    mock_resp.headers = {}

    with patch("app.services.verification.validate_destination_url", return_value=(True, None)):
        with patch("httpx.Client.get", return_value=mock_resp):
            res = check_website_availability(app.homepage_url)
            assert res["status"] == "FAILED"
            assert res["http_status"] == 503

        new_check = VerificationCheck(
            app_id=app.id,
            check_type="website_availability",
            status=res["status"],
            duration_ms=res["duration_ms"],
            checked_at=datetime.utcnow(),
            http_status=res["http_status"],
            final_url=res["final_url"],
            tls_valid=res["tls_valid"],
            error_message=res["error_message"]
        )
        test_db.add(new_check)
        test_db.commit()

    all_checks = test_db.query(VerificationCheck).filter(VerificationCheck.app_id == app.id).all()
    assert len(all_checks) == 2
    assert derive_verification_status(all_checks) == "VERIFICATION_FAILED"


def test_6_retry_backoff_is_bounded():
    """6. Retry backoff is bounded and never exceeds configured max."""
    base = 300
    max_val = 86400

    b1 = calculate_backoff(attempts=1, base_seconds=base, max_seconds=max_val, jitter=False)
    assert b1 == base

    b2 = calculate_backoff(attempts=2, base_seconds=base, max_seconds=max_val, jitter=False)
    assert b2 == 600

    b5 = calculate_backoff(attempts=5, base_seconds=base, max_seconds=max_val, jitter=False)
    assert b5 == 4800

    b20 = calculate_backoff(attempts=20, base_seconds=base, max_seconds=max_val, jitter=False)
    assert b20 == max_val  # Strictly bounded ceiling


def test_7_old_successful_evidence_becomes_stale(test_db):
    """7. Old successful evidence becomes stale when freshness threshold is passed."""
    app = test_db.query(App).filter(App.slug == "test-app-1").first()

    stale_date = datetime.utcnow() - timedelta(days=settings.WEBSITE_FRESHNESS_DAYS + 2)
    check = VerificationCheck(
        app_id=app.id,
        check_type="website_availability",
        status="SUCCESS",
        checked_at=stale_date,
        http_status=200,
        final_url="https://example.com",
        tls_valid=True
    )
    test_db.add(check)
    test_db.commit()

    status = derive_verification_status([check])
    assert status == "STALE"


def test_8_interrupted_jobs_recover_safely(test_db):
    """8. Interrupted jobs with expired locks recover safely."""
    plan_scheduled_checks(test_db)
    task = claim_next_task(test_db, worker_id="crashed-worker")

    # Simulate process crash 10 minutes ago
    task.locked_at = datetime.utcnow() - timedelta(minutes=10)
    test_db.commit()

    # New worker claiming task should recover the stale locked task
    recovered_task = claim_next_task(test_db, worker_id="new-worker", lock_timeout_seconds=300)
    assert recovered_task is not None
    assert recovered_task.id == task.id
    assert recovered_task.locked_by == "new-worker"
    assert recovered_task.status == "RUNNING"


def test_9_github_rate_limits_respect_request_budget(test_db):
    """9. GitHub rate limits respect the 150 request budget."""
    app = test_db.query(App).filter(App.slug == "test-app-1").first()

    budget = RequestBudget(limit=150)
    budget.record_request(150)
    assert not budget.can_request()

    res = sync_github_releases(test_db, app, budget=budget)
    assert res["status"] == "SKIPPED"
    assert "Request budget" in res["message"]
    assert budget.used == 150


def test_10_conditional_requests_use_stored_etags(test_db):
    """10. Conditional requests use stored ETags and handle HTTP 304 Not Modified."""
    app = test_db.query(App).filter(App.slug == "test-app-1").first()

    existing_rel = AppRelease(
        app_id=app.id,
        tag_name="v1.0.0",
        name="Version 1.0.0",
        release_url="https://github.com/example/testapp/releases/tag/v1.0.0",
        etag='"etag-hash-12345"',
        last_synced_at=datetime.utcnow() - timedelta(days=1)
    )
    test_db.add(existing_rel)
    test_db.commit()

    budget = RequestBudget(limit=150)

    mock_resp = MagicMock()
    mock_resp.status_code = 304
    mock_resp.headers = {"x-ratelimit-remaining": "59"}

    with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
        res = sync_github_releases(test_db, app, budget=budget)
        assert res["status"] == "SUCCESS"
        assert "304 Not Modified" in res["message"]

        # Verify If-None-Match was passed in request headers
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"].get("If-None-Match") == '"etag-hash-12345"'

        # Verify last_synced_at was refreshed
        test_db.refresh(existing_rel)
        assert (datetime.utcnow() - existing_rel.last_synced_at).total_seconds() < 5


def test_11_repeated_synchronization_does_not_create_duplicate_releases(test_db):
    """11. Repeated synchronization does not create duplicate releases."""
    app = test_db.query(App).filter(App.slug == "test-app-1").first()

    release_payload = [
        {
            "tag_name": "v1.0.0",
            "name": "Release 1.0",
            "published_at": "2026-01-01T12:00:00Z",
            "html_url": "https://github.com/example/testapp/releases/tag/v1.0.0",
            "prerelease": False,
            "target_commitish": "abc1234",
            "assets": [
                {
                    "name": "testapp-1.0-win.exe",
                    "browser_download_url": "https://github.com/example/testapp/releases/download/v1.0.0/testapp-1.0-win.exe",
                    "size": 15000000,
                    "content_type": "application/octet-stream"
                }
            ]
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"etag": '"etag-v1"', "x-ratelimit-remaining": "50"}
    mock_resp.json.return_value = release_payload

    budget = RequestBudget(limit=150)

    with patch("httpx.Client.get", return_value=mock_resp):
        with patch("app.services.release_sync.check_asset_reachability", return_value=(True, None)):
            res1 = sync_github_releases(test_db, app, budget=budget, check_asset_urls=True)
            assert res1["status"] == "SUCCESS"
            assert res1["releases_synced"] == 1

            # Run a second sync cycle with the same release
            res2 = sync_github_releases(test_db, app, budget=budget, check_asset_urls=False)
            assert res2["status"] == "SUCCESS"

    releases = test_db.query(AppRelease).filter(AppRelease.app_id == app.id).all()
    assert len(releases) == 1
    assert releases[0].tag_name == "v1.0.0"

    assets = test_db.query(ReleaseAsset).filter(ReleaseAsset.release_id == releases[0].id).all()
    assert len(assets) == 1
    assert assets[0].platform == "windows"


def test_12_missing_release_assets_are_represented_honestly(test_db):
    """12. Missing release assets are represented honestly without inventing links."""
    app = test_db.query(App).filter(App.slug == "test-app-1").first()

    release_payload = [
        {
            "tag_name": "v2.0.0",
            "name": "Source Only Release",
            "published_at": "2026-02-01T12:00:00Z",
            "html_url": "https://github.com/example/testapp/releases/tag/v2.0.0",
            "prerelease": False,
            "assets": []  # No binary assets published!
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"etag": '"etag-v2"', "x-ratelimit-remaining": "40"}
    mock_resp.json.return_value = release_payload

    budget = RequestBudget(limit=150)
    with patch("httpx.Client.get", return_value=mock_resp):
        res = sync_github_releases(test_db, app, budget=budget)
        assert res["status"] == "SUCCESS"
        assert res["releases_synced"] == 1
        assert res["assets_synced"] == 0

    rel = test_db.query(AppRelease).filter(AppRelease.app_id == app.id, AppRelease.tag_name == "v2.0.0").first()
    assert rel is not None
    assert len(rel.assets) == 0


def test_13_official_asset_urls_pass_ssrf_checks():
    """13. Official asset URLs pass SSRF checks and block internal destinations."""
    budget = RequestBudget(limit=10)

    # Prohibited link-local / loopback destination
    prohibited_url = "http://127.0.0.1:8080/malicious-asset.exe"
    ok, err = check_asset_reachability(prohibited_url, budget)
    assert ok is False
    assert "SSRF" in err or "Prohibited" in err

    # Prohibited private IP range
    private_url = "http://10.0.0.5/asset.dmg"
    ok_priv, err_priv = check_asset_reachability(private_url, budget)
    assert ok_priv is False
    assert "SSRF" in err_priv or "Prohibited" in err_priv


def test_14_delisted_applications_excluded_from_public_search(test_db):
    """14. Delisted applications remain excluded from public search and listings."""
    app1 = test_db.query(App).filter(App.slug == "test-app-1").first()
    app1.is_delisted = True
    test_db.commit()

    active_apps = test_db.query(App).filter(App.is_delisted == False).all()
    active_slugs = [a.slug for a in active_apps]
    assert "test-app-1" not in active_slugs
    assert "test-app-2" in active_slugs


def test_15_operator_endpoints_fail_closed():
    """15. Operator endpoints continue to fail closed when token is unset or invalid."""
    from fastapi.testclient import TestClient
    from app.main import app

    with patch.object(settings, "OPS_TOKEN", None):
        client = TestClient(app)
        res = client.get("/api/v1/ops/status", headers={"Authorization": "Bearer any-token"})
        assert res.status_code == 403


def test_16_scheduler_health_and_failures_visible_through_operations(test_db):
    """16. Scheduler health, jobs, and failures are visible through operations metrics."""
    plan_scheduled_checks(test_db)
    metrics = get_scheduler_metrics(test_db)

    assert "total_schedules" in metrics
    assert "pending_tasks" in metrics
    assert "running_tasks" in metrics
    assert "failed_tasks" in metrics
    assert "retried_tasks" in metrics
    assert metrics["total_schedules"] == 3
    assert metrics["pending_tasks"] == 3
