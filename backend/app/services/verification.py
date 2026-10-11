import ipaddress
import socket
import time
from urllib.parse import urlparse
from datetime import datetime, timedelta
import httpx
from typing import Optional, Tuple, Dict, Any, List
from sqlalchemy.orm import Session
from app.config import settings
from app.models.models import App, VerificationCheck, VerificationRun

# Private/prohibited CIDRs for SSRF prevention
PROHIBITED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECT_HOPS = 5


def validate_destination_url(url: str) -> Tuple[bool, Optional[str]]:
    """Protect against SSRF: check scheme, parse host, resolve DNS, and verify destination IP."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported URL scheme: {parsed.scheme}"
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid URL host"

        # Explicitly check for localhost aliases
        if hostname.lower() in ("localhost", "ip6-localhost", "ip6-loopback"):
            return False, f"Prohibited loopback host: {hostname}"

        # Resolve hostname across all address families (IPv4 and IPv6)
        addr_info = socket.getaddrinfo(hostname, None)
        for entry in addr_info:
            ip_str = entry[4][0]
            ip = ipaddress.ip_address(ip_str)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            for net in PROHIBITED_NETWORKS:
                if ip in net:
                    return False, f"Prohibited IP destination: {ip_str}"
        return True, None
    except Exception as e:
        return False, f"Host resolution error: {str(e)}"


def check_website_availability(url: str, timeout_sec: float = 8.0, max_redirects: int = 5) -> Dict[str, Any]:
    """Execute real website availability check with duration, status, redirect hop validation, and TLS verification."""
    is_safe, error = validate_destination_url(url)
    if not is_safe:
        return {
            "status": "FAILED",
            "http_status": None,
            "final_url": url,
            "duration_ms": 0,
            "tls_valid": False,
            "error_message": error,
            "details": {"security_block": True, "reason": error},
        }

    start = time.perf_counter()
    current_url = url
    redirect_count = 0

    try:
        from urllib.parse import urljoin
        with httpx.Client(
            follow_redirects=False,  # Intercept and validate every redirect hop
            timeout=timeout_sec,
            headers={"User-Agent": "OSSDiscoveryBot/1.0 (+https://github.com/oss-discovery)"},
        ) as client:
            while redirect_count <= max_redirects:
                resp = client.get(current_url)

                # Enforce response body size limit (max 2MB)
                if len(resp.content) > 2 * 1024 * 1024:
                    return {
                        "status": "FAILED",
                        "http_status": resp.status_code,
                        "final_url": current_url,
                        "duration_ms": int((time.perf_counter() - start) * 1000),
                        "tls_valid": False,
                        "error_message": "Response exceeds maximum allowed size (2MB)",
                        "details": {"size_exceeded": True},
                    }

                # If redirect, validate target URL before following
                if 300 <= resp.status_code < 400 and "location" in resp.headers:
                    redirect_count += 1
                    target_url = urljoin(current_url, resp.headers["location"])
                    is_target_safe, target_error = validate_destination_url(target_url)
                    if not is_target_safe:
                        return {
                            "status": "FAILED",
                            "http_status": resp.status_code,
                            "final_url": target_url,
                            "duration_ms": int((time.perf_counter() - start) * 1000),
                            "tls_valid": False,
                            "error_message": f"SSRF blocked redirect to prohibited destination: {target_error}",
                            "details": {"security_block": True, "redirect_block": True, "reason": target_error},
                        }
                    current_url = target_url
                    continue

                duration_ms = int((time.perf_counter() - start) * 1000)
                is_success = 200 <= resp.status_code < 400
                tls_valid = (resp.url.scheme == "https") if hasattr(resp.url, "scheme") else str(resp.url).startswith("https")

                return {
                    "status": "SUCCESS" if is_success else "FAILED",
                    "http_status": resp.status_code,
                    "final_url": str(resp.url),
                    "duration_ms": duration_ms,
                    "tls_valid": tls_valid,
                    "error_message": None if is_success else f"HTTP status {resp.status_code}",
                    "details": {
                        "redirect_count": redirect_count,
                        "headers_content_type": resp.headers.get("content-type", ""),
                    },
                }

            return {
                "status": "FAILED",
                "http_status": None,
                "final_url": current_url,
                "duration_ms": int((time.perf_counter() - start) * 1000),
                "tls_valid": False,
                "error_message": "Exceeded maximum redirect hops (5)",
                "details": {"too_many_redirects": True},
            }
    except httpx.TimeoutException:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "FAILED",
            "http_status": None,
            "final_url": url,
            "duration_ms": duration_ms,
            "tls_valid": False,
            "error_message": "Request timed out",
            "details": {"timeout": True},
        }
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "FAILED",
            "http_status": None,
            "final_url": url,
            "duration_ms": duration_ms,
            "tls_valid": False,
            "error_message": f"Connection error: {type(e).__name__}",
            "details": {"error_type": type(e).__name__},
        }


def record_website_check(db: Session, app: App, run: Optional[VerificationRun] = None) -> VerificationCheck:
    """Run real website check and persist check record."""
    result = check_website_availability(app.homepage_url)
    check = VerificationCheck(
        run_id=run.id if run else None,
        app_id=app.id,
        check_type="website_availability",
        status=result["status"],
        duration_ms=result["duration_ms"],
        checked_at=datetime.utcnow(),
        http_status=result["http_status"],
        final_url=result["final_url"],
        tls_valid=result["tls_valid"],
        details=result["details"],
        error_message=result["error_message"],
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


def derive_verification_status(checks: List[VerificationCheck]) -> str:
    """
    Centralized derivation of public verification status:
    - VERIFIED_RECENTLY: All applicable checks present, passed, and fresh (<7d website, <30d repo).
    - PARTIALLY_VERIFIED: At least one passed and fresh, but others missing or stale.
    - VERIFICATION_FAILED: Any check has explicitly FAILED.
    - STALE: All checks passed, but latest check older than freshness threshold.
    - UNVERIFIED: No checks recorded.
    """
    if not checks:
        return "UNVERIFIED"

    has_failed = any(c.status == "FAILED" for c in checks)
    if has_failed:
        return "VERIFICATION_FAILED"

    now = datetime.utcnow()
    web_threshold = timedelta(days=settings.WEBSITE_FRESHNESS_DAYS)
    repo_threshold = timedelta(days=settings.REPO_FRESHNESS_DAYS)

    web_checks = [c for c in checks if c.check_type == "website_availability"]
    repo_checks = [c for c in checks if c.check_type in ("repo_metadata", "release_availability", "release_metadata", "release_sync")]

    # Check website freshness
    latest_web = max(web_checks, key=lambda c: c.checked_at) if web_checks else None
    web_fresh = latest_web and (now - latest_web.checked_at <= web_threshold) and latest_web.status == "SUCCESS"

    latest_repo = max(repo_checks, key=lambda c: c.checked_at) if repo_checks else None
    repo_fresh = latest_repo and (now - latest_repo.checked_at <= repo_threshold) and latest_repo.status == "SUCCESS"

    if web_fresh and (repo_fresh or not repo_checks):
        return "VERIFIED_RECENTLY"

    if (latest_web and now - latest_web.checked_at > web_threshold) or (latest_repo and now - latest_repo.checked_at > repo_threshold):
        return "STALE"

    if web_fresh or repo_fresh:
        return "PARTIALLY_VERIFIED"

    return "UNVERIFIED"
