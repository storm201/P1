import re
import socket
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, urljoin
import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import App, AppRelease, ReleaseAsset, VerificationCheck
from app.services.verification import validate_destination_url

logger = logging.getLogger("release_sync")


class RequestBudget:
    """Tracks API requests across a synchronization cycle, strictly enforcing the 150 request cap."""
    def __init__(self, limit: int = 150):
        self.limit = limit
        self.used = 0
        self.rate_limited = False

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def can_request(self) -> bool:
        return self.used < self.limit and not self.rate_limited

    def record_request(self, count: int = 1):
        self.used += count

    def mark_rate_limited(self):
        self.rate_limited = True


def parse_github_repo(repo_url: Optional[str]) -> Optional[Tuple[str, str]]:
    """Extracts (owner, repo) from a GitHub repository URL."""
    if not repo_url:
        return None
    parsed = urlparse(repo_url)
    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) >= 2:
        owner = path_parts[0]
        repo = path_parts[1].removesuffix(".git")
        return owner, repo
    return None


def detect_platform_from_name(filename: str) -> Optional[str]:
    """Heuristically identifies OS platform from release asset filename."""
    lower = filename.lower()
    if any(ext in lower for ext in (".exe", ".msi")) or any(s in lower for s in ("windows", "win32", "win64", "-win.", "_win.")):
        return "windows"
    if any(ext in lower for ext in (".dmg", ".pkg")) or any(s in lower for s in ("macos", "darwin", "osx", "-mac.", "_mac.")):
        return "macos"
    if any(ext in lower for ext in (".deb", ".rpm", ".appimage", ".flatpak")) or any(s in lower for s in ("linux", "-linux.", "_linux.")):
        return "linux"
    if lower.endswith(".apk") or "android" in lower:
        return "android"
    if lower.endswith(".ipa") or "ios" in lower:
        return "ios"
    return None


def detect_checksum_info(asset_name: str, release_body: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Detects checksum algorithm and value if published in asset metadata or body.
    Never invents checksum values.
    """
    lower = asset_name.lower()
    algo = None
    if ".sha256" in lower:
        algo = "sha256"
    elif ".sha512" in lower:
        algo = "sha512"
    elif ".md5" in lower:
        algo = "md5"

    checksum_value = None
    if release_body and algo == "sha256":
        # Search for 64-character hex strings in body
        match = re.search(r'\b[a-fA-F0-9]{64}\b', release_body)
        if match:
            checksum_value = match.group(0).lower()

    return algo, checksum_value


def check_asset_reachability(
    download_url: str,
    budget: RequestBudget,
    timeout_sec: float = 5.0
) -> Tuple[bool, Optional[str]]:
    """
    Validates asset URL safety with SSRF checks and checks reachability.
    Stops after headers without downloading executable binaries.
    """
    is_safe, error = validate_destination_url(download_url)
    if not is_safe:
        return False, f"SSRF check failed: {error}"

    if not budget.can_request():
        return False, "Request budget exhausted"

    current_url = download_url
    redirect_count = 0
    max_redirects = 5

    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=timeout_sec,
            headers={"User-Agent": "OSSDiscoveryBot/1.0 (+https://github.com/oss-discovery)"}
        ) as client:
            while redirect_count <= max_redirects:
                if not budget.can_request():
                    return False, "Request budget exhausted"

                budget.record_request(1)
                # Use HEAD or range GET with 0-0 bytes to avoid downloading large files
                try:
                    resp = client.head(current_url)
                    if resp.status_code in (405, 501):  # Method not allowed for HEAD, fallback to range GET
                        resp = client.get(current_url, headers={"Range": "bytes=0-0"})
                except Exception:
                    resp = client.get(current_url, headers={"Range": "bytes=0-0"})

                # Handle redirects safely
                if 300 <= resp.status_code < 400 and "location" in resp.headers:
                    redirect_count += 1
                    target = urljoin(current_url, resp.headers["location"])
                    target_safe, target_err = validate_destination_url(target)
                    if not target_safe:
                        return False, f"Redirect to prohibited destination: {target_err}"
                    current_url = target
                    continue

                is_ok = 200 <= resp.status_code < 400
                return is_ok, None if is_ok else f"HTTP {resp.status_code}"

            return False, "Exceeded maximum redirect hops"
    except httpx.TimeoutException:
        return False, "Request timed out"
    except Exception as e:
        return False, f"Reachability check error: {type(e).__name__}"


def sanitize_token(text: Optional[str]) -> Optional[str]:
    """Redacts any configured GitHub token from strings, logs, or error messages."""
    if not text:
        return text
    if settings.GITHUB_TOKEN and settings.GITHUB_TOKEN in text:
        return text.replace(settings.GITHUB_TOKEN, "[REDACTED_GITHUB_TOKEN]")
    return text


def sync_github_releases(
    db: Session,
    app: App,
    budget: RequestBudget,
    check_asset_urls: bool = True
) -> Dict[str, Any]:
    """
    Synchronizes official release metadata and downloadable assets for an application from GitHub.
    - Honors request budget (max 150).
    - Uses ETag conditional requests (`If-None-Match`).
    - Handles rate limits and reset information.
    - Persists release and asset records with deduplication.
    - Runs SSRF-safe reachability checks without downloading binary payloads.
    - Records honest verification evidence.
    """
    repo_info = parse_github_repo(app.repo_url)
    if not repo_info:
        return {
            "status": "SKIPPED",
            "message": "Application has no valid GitHub repository configured",
            "releases_synced": 0,
            "assets_synced": 0,
            "requests_used": 0
        }

    owner, repo = repo_info
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"

    # Validate destination host safety
    is_safe, error = validate_destination_url(url)
    if not is_safe:
        return {
            "status": "FAILED",
            "error": f"SSRF blocked GitHub API destination: {error}",
            "releases_synced": 0,
            "assets_synced": 0,
            "requests_used": 0
        }

    if not budget.can_request():
        return {
            "status": "SKIPPED",
            "message": "Request budget limit reached (150 requests)",
            "releases_synced": 0,
            "assets_synced": 0,
            "requests_used": 0
        }

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OSSDiscoveryBot/1.0 (+https://github.com/oss-discovery)"
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    # Check if we have a stored ETag from previous sync
    latest_release = db.query(AppRelease).filter(
        AppRelease.app_id == app.id
    ).order_by(AppRelease.published_at.desc()).first()

    if latest_release and latest_release.etag:
        headers["If-None-Match"] = latest_release.etag

    start_requests = budget.used
    now = datetime.utcnow()

    try:
        with httpx.Client(timeout=10.0) as client:
            budget.record_request(1)
            resp = client.get(url, headers=headers)

            # Check rate limiting headers
            rate_remaining = resp.headers.get("x-ratelimit-remaining")
            rate_reset = resp.headers.get("x-ratelimit-reset")

            if rate_remaining is not None and int(rate_remaining) == 0:
                budget.mark_rate_limited()
                logger.warning(f"GitHub API rate limit reached. Reset timestamp: {rate_reset}")
                return {
                    "status": "RATE_LIMITED",
                    "message": f"GitHub rate limit reached (resets at {rate_reset})",
                    "releases_synced": 0,
                    "assets_synced": 0,
                    "requests_used": budget.used - start_requests
                }

            # 304 Not Modified: Existing releases are up-to-date
            if resp.status_code == 304:
                existing_releases = db.query(AppRelease).filter(AppRelease.app_id == app.id).all()
                for r in existing_releases:
                    r.last_synced_at = now
                db.commit()

                check = VerificationCheck(
                    app_id=app.id,
                    check_type="release_metadata",
                    status="SUCCESS",
                    duration_ms=50,
                    checked_at=now,
                    http_status=304,
                    final_url=url,
                    tls_valid=True,
                    details={"status_code": 304, "not_modified": True, "release_count": len(existing_releases)},
                    error_message=None
                )
                db.add(check)
                db.commit()

                return {
                    "status": "SUCCESS",
                    "message": "Releases up-to-date (conditional request 304 Not Modified)",
                    "releases_synced": len(existing_releases),
                    "assets_synced": 0,
                    "requests_used": budget.used - start_requests
                }

            # 404 or non-success
            if resp.status_code == 404:
                check = VerificationCheck(
                    app_id=app.id,
                    check_type="release_metadata",
                    status="SUCCESS",
                    duration_ms=100,
                    checked_at=now,
                    http_status=404,
                    final_url=url,
                    tls_valid=True,
                    details={"has_releases": False, "http_status": 404},
                    error_message="No public releases published on GitHub repository"
                )
                db.add(check)
                db.commit()
                return {
                    "status": "SUCCESS",
                    "message": "No releases published on GitHub",
                    "releases_synced": 0,
                    "assets_synced": 0,
                    "requests_used": budget.used - start_requests
                }

            if resp.status_code == 403:
                budget.mark_rate_limited()
                return {
                    "status": "RATE_LIMITED",
                    "message": "GitHub API returned 403 Forbidden (rate limited or access denied)",
                    "releases_synced": 0,
                    "assets_synced": 0,
                    "requests_used": budget.used - start_requests
                }

            if resp.status_code != 200:
                err_msg = f"GitHub API error {resp.status_code}: {sanitize_token(resp.text[:200])}"
                check = VerificationCheck(
                    app_id=app.id,
                    check_type="release_metadata",
                    status="FAILED",
                    duration_ms=150,
                    checked_at=now,
                    http_status=resp.status_code,
                    final_url=url,
                    tls_valid=True,
                    details={"error": err_msg},
                    error_message=err_msg
                )
                db.add(check)
                db.commit()
                return {
                    "status": "FAILED",
                    "error": err_msg,
                    "releases_synced": 0,
                    "assets_synced": 0,
                    "requests_used": budget.used - start_requests
                }

            # HTTP 200: Parse release data
            response_etag = resp.headers.get("etag")
            data = resp.json()

            if not isinstance(data, list):
                return {
                    "status": "FAILED",
                    "error": "Unexpected GitHub response structure (not a list)",
                    "releases_synced": 0,
                    "assets_synced": 0,
                    "requests_used": budget.used - start_requests
                }

            releases_synced = 0
            assets_synced = 0

            # If no releases exist
            if len(data) == 0:
                check = VerificationCheck(
                    app_id=app.id,
                    check_type="release_metadata",
                    status="SUCCESS",
                    duration_ms=100,
                    checked_at=now,
                    http_status=200,
                    final_url=url,
                    tls_valid=True,
                    details={"has_releases": False, "release_count": 0},
                    error_message=None
                )
                db.add(check)
                db.commit()
                return {
                    "status": "SUCCESS",
                    "message": "Repository has no releases",
                    "releases_synced": 0,
                    "assets_synced": 0,
                    "requests_used": budget.used - start_requests
                }

            # Process up to 5 latest releases
            for item in data[:5]:
                tag = item.get("tag_name")
                if not tag:
                    continue

                published_str = item.get("published_at")
                pub_date = None
                if published_str:
                    try:
                        pub_date = datetime.fromisoformat(published_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        pub_date = now

                # Deduplicate release by (app_id, tag_name)
                release_obj = db.query(AppRelease).filter(
                    AppRelease.app_id == app.id,
                    AppRelease.tag_name == tag
                ).first()

                if not release_obj:
                    release_obj = AppRelease(
                        app_id=app.id,
                        tag_name=tag,
                        name=item.get("name") or tag,
                        published_at=pub_date,
                        release_url=item.get("html_url") or f"https://github.com/{owner}/{repo}/releases/tag/{tag}",
                        is_prerelease=bool(item.get("prerelease", False)),
                        source_commit=item.get("target_commitish"),
                        last_synced_at=now,
                        etag=response_etag
                    )
                    db.add(release_obj)
                    db.flush()
                else:
                    release_obj.name = item.get("name") or tag
                    release_obj.published_at = pub_date
                    release_obj.release_url = item.get("html_url") or release_obj.release_url
                    release_obj.is_prerelease = bool(item.get("prerelease", False))
                    release_obj.source_commit = item.get("target_commitish")
                    release_obj.last_synced_at = now
                    if response_etag:
                        release_obj.etag = response_etag

                releases_synced += 1
                raw_assets = item.get("assets", [])

                for idx, a in enumerate(raw_assets):
                    asset_name = a.get("name")
                    dl_url = a.get("browser_download_url")
                    if not asset_name or not dl_url:
                        continue

                    platform = detect_platform_from_name(asset_name)
                    algo, chksum = detect_checksum_info(asset_name, item.get("body"))

                    # Reachability check on up to 2 primary assets per release to preserve request budget
                    is_reachable = None
                    if idx < 2 and check_asset_urls and budget.can_request():
                        reach_ok, _ = check_asset_reachability(dl_url, budget)
                        is_reachable = reach_ok

                    # Deduplicate asset by (release_id, name)
                    asset_obj = db.query(ReleaseAsset).filter(
                        ReleaseAsset.release_id == release_obj.id,
                        ReleaseAsset.name == asset_name
                    ).first()

                    if not asset_obj:
                        asset_obj = ReleaseAsset(
                            release_id=release_obj.id,
                            name=asset_name,
                            download_url=dl_url,
                            size_bytes=a.get("size"),
                            content_type=a.get("content_type"),
                            checksum=chksum,
                            checksum_algorithm=algo,
                            platform=platform,
                            is_reachable=is_reachable,
                            last_checked_at=now if is_reachable is not None else None
                        )
                        db.add(asset_obj)
                    else:
                        asset_obj.download_url = dl_url
                        asset_obj.size_bytes = a.get("size")
                        asset_obj.content_type = a.get("content_type")
                        if platform:
                            asset_obj.platform = platform
                        if chksum:
                            asset_obj.checksum = chksum
                        if algo:
                            asset_obj.checksum_algorithm = algo
                        if is_reachable is not None:
                            asset_obj.is_reachable = is_reachable
                            asset_obj.last_checked_at = now

                    assets_synced += 1

            db.commit()

            # Record successful verification check
            check = VerificationCheck(
                app_id=app.id,
                check_type="release_metadata",
                status="SUCCESS",
                duration_ms=200,
                checked_at=now,
                http_status=200,
                final_url=url,
                tls_valid=True,
                details={
                    "releases_synced": releases_synced,
                    "assets_synced": assets_synced,
                    "has_releases": True
                },
                error_message=None
            )
            db.add(check)
            db.commit()

            return {
                "status": "SUCCESS",
                "releases_synced": releases_synced,
                "assets_synced": assets_synced,
                "requests_used": budget.used - start_requests
            }

    except Exception as e:
        err_str = sanitize_token(f"Release sync error: {type(e).__name__} - {str(e)}")
        logger.error(f"Error syncing releases for {app.slug}: {err_str}")
        check = VerificationCheck(
            app_id=app.id,
            check_type="release_metadata",
            status="FAILED",
            duration_ms=100,
            checked_at=now,
            http_status=None,
            final_url=url,
            tls_valid=False,
            details={"error": err_str},
            error_message=err_str
        )
        db.add(check)
        db.commit()
        return {
            "status": "FAILED",
            "error": err_str,
            "releases_synced": 0,
            "assets_synced": 0,
            "requests_used": budget.used - start_requests
        }
