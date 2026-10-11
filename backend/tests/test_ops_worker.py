import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.config import settings
from app.models.models import App, CorrectionRequest, IngestionJob
from app.worker.worker import execute_verification_job
from app.services.search import execute_hybrid_search


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_ops_endpoint_fails_closed_when_no_token():
    # If OPS_TOKEN is unset or not provided, fails closed
    client = TestClient(app)
    resp = client.get("/api/v1/ops/status")
    assert resp.status_code in [401, 403]


def test_ops_endpoint_with_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "OPS_TOKEN", "secret-test-token-123")
    client = TestClient(app)

    # Missing header -> 401
    resp_no_header = client.get("/api/v1/ops/status")
    assert resp_no_header.status_code == 401

    # Invalid header -> 401
    resp_bad = client.get("/api/v1/ops/status", headers={"Authorization": "Bearer wrong-token"})
    assert resp_bad.status_code == 401

    # Valid header -> 200
    resp_ok = client.get("/api/v1/ops/status", headers={"Authorization": "Bearer secret-test-token-123"})
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert "worker_status" in data
    assert "total_apps" in data
    assert "pending_corrections_count" in data


def test_worker_records_persistent_job_state():
    from unittest.mock import patch, MagicMock
    db = SessionLocal()
    try:
        mock_check = {
            "status": "SUCCESS",
            "http_status": 200,
            "final_url": "https://example.com",
            "duration_ms": 50,
            "tls_valid": True,
            "error_message": None,
            "details": {}
        }
        mock_sync = {
            "status": "SUCCESS",
            "releases_synced": 1,
            "assets_synced": 1,
            "requests_used": 1
        }
        with patch("app.worker.worker.record_website_check") as mock_web:
            mock_web.return_value = MagicMock(status="SUCCESS", error_message=None)
            with patch("app.worker.worker.sync_github_releases", return_value=mock_sync):
                job = execute_verification_job(db, max_apps=3)
                assert job.id is not None
                assert job.status == "COMPLETED"
                assert job.items_processed > 0
                assert job.started_at is not None
                assert job.completed_at is not None

                # Verify persisted in database
                saved = db.query(IngestionJob).filter(IngestionJob.id == job.id).first()
                assert saved is not None
                assert saved.status == "COMPLETED"
    finally:
        db.close()


def test_correction_and_delisting_audit_workflow(monkeypatch):
    monkeypatch.setattr(settings, "OPS_TOKEN", "secret-test-token-123")
    client = TestClient(app)
    db = SessionLocal()
    try:
        # Public user submits correction request
        resp = client.post("/api/v1/corrections", json={
            "app_identifier": "7-zip",
            "request_type": "removal",
            "reason": "Test removal request with sanitized details <script>alert(1)</script>",
            "contact_email": "auditor@example.com"
        })
        assert resp.status_code == 201
        created = resp.json()
        req_id = created["id"]
        # Script tags must be escaped
        assert "<script>" not in created["reason"]
        assert "&lt;script&gt;" in created["reason"]

        # Operator reviews and resolves request
        resolve_resp = client.post(
            f"/api/v1/ops/corrections/{req_id}/resolve",
            headers={"Authorization": "Bearer secret-test-token-123"},
            json={
                "status": "APPROVED",
                "resolution_notes": "Delisted per policy audit.",
                "delist_app": True
            }
        )
        assert resolve_resp.status_code == 200
        resolved = resolve_resp.json()
        assert resolved["status"] == "APPROVED"

        # Verify app is marked delisted in DB
        app_7z = db.query(App).filter(App.slug == "7-zip").first()
        assert app_7z.is_delisted is True

        # Delisted app MUST NOT appear in public search results
        search_results, _ = execute_hybrid_search(db, "7-zip")
        slugs = [r["app"].slug for r in search_results]
        assert "7-zip" not in slugs

        # Restore
        app_7z.is_delisted = False
        db.commit()
    finally:
        db.close()
