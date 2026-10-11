import pytest
import html
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.services.verification import (
    validate_destination_url,
    check_website_availability,
    MAX_RESPONSE_BYTES,
    MAX_REDIRECT_HOPS,
)
from app.database import SessionLocal
from app.models.models import App, CorrectionRequest


def test_ssrf_ipv4_and_ipv6_prohibited_ranges():
    """Verify that private, loopback, link-local, multicast, and IPv4-mapped IPv6 destinations are rejected."""
    prohibited_urls = [
        "http://127.0.0.1/status",
        "http://127.0.0.2:8000/api",
        "http://10.0.0.1/admin",
        "http://172.16.0.5/secrets",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "gopher://example.com/",
    ]

    for target in prohibited_urls:
        valid, msg = validate_destination_url(target)
        assert valid is False, f"Expected {target} to be blocked, but it passed validation!"
        assert msg is not None


def test_ssrf_safe_urls_pass_validation():
    """Verify standard public web destinations pass validation."""
    safe_urls = [
        "https://www.google.com",
        "https://github.com",
        "https://www.videolan.org",
    ]
    for url in safe_urls:
        valid, msg = validate_destination_url(url)
        assert valid is True, f"Expected {url} to be valid, but got: {msg}"
        assert msg is None


def test_ssrf_network_execution_blocking():
    """Verify check_website_availability fails closed with status FAILED when given prohibited destination."""
    res = check_website_availability("http://127.0.0.1:9090")
    assert res["status"] == "FAILED"
    assert "Prohibited IP" in res["error_message"]
    assert res["tls_valid"] is False

    res_v6 = check_website_availability("http://[::1]:9090")
    assert res_v6["status"] == "FAILED"
    assert "Prohibited IP" in res_v6["error_message"]


def test_ops_token_fails_closed_when_unset_or_empty(monkeypatch):
    """Verify that ops endpoints strictly fail closed (401 or 403) when OPS_TOKEN is unset or empty."""
    client = TestClient(app)

    # Empty token
    monkeypatch.setattr(settings, "OPS_TOKEN", "")
    resp = client.get("/api/v1/ops/status", headers={"Authorization": "Bearer "})
    assert resp.status_code in [401, 403]

    # Token unset / None
    monkeypatch.setattr(settings, "OPS_TOKEN", None)
    resp = client.get("/api/v1/ops/status", headers={"Authorization": "Bearer any-token"})
    assert resp.status_code in [401, 403]


def test_ops_token_rejected_in_query_params_or_cookies(monkeypatch):
    """Verify ops token is NOT accepted via URL query parameter or cookie."""
    token = "audit-secure-token-999"
    monkeypatch.setattr(settings, "OPS_TOKEN", token)
    client = TestClient(app)

    # In query param -> 401
    resp_query = client.get(f"/api/v1/ops/status?token={token}")
    assert resp_query.status_code == 401

    # In cookies -> 401
    resp_cookie = client.get("/api/v1/ops/status", cookies={"ops_token": token})
    assert resp_cookie.status_code == 401

    # Valid Authorization header -> 200
    resp_auth = client.get("/api/v1/ops/status", headers={"Authorization": f"Bearer {token}"})
    assert resp_auth.status_code == 200


def test_correction_form_input_validation_and_escaping():
    """Verify correction form input sanitization and XSS prevention."""
    client = TestClient(app)

    # Invalid email rejected
    resp_bad_email = client.post("/api/v1/corrections", json={
        "app_identifier": "audacity",
        "request_type": "correction",
        "reason": "Valid reason",
        "contact_email": "not-an-email"
    })
    assert resp_bad_email.status_code == 422

    # Malicious payload escaped
    malicious = "<script>alert('xss')</script><img src=x onerror=alert(1)>"
    resp = client.post("/api/v1/corrections", json={
        "app_identifier": "audacity",
        "request_type": "correction",
        "reason": malicious,
        "contact_email": "security@example.com"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "<script>" not in data["reason"]
    assert "<img" not in data["reason"]
    assert "&lt;script&gt;" in data["reason"]
    assert "&lt;img" in data["reason"]
