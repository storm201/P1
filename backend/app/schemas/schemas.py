from datetime import datetime
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, HttpUrl


class CategoryAliasRead(BaseModel):
    alias: str
    match_type: str

    class Config:
        from_attributes = True


class CategoryRead(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    aliases: List[CategoryAliasRead] = []

    class Config:
        from_attributes = True


class CategoryTree(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    subcategories: List["CategoryTree"] = []

    class Config:
        from_attributes = True


class ReleaseAssetRead(BaseModel):
    id: int
    name: str
    download_url: str
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    checksum_algorithm: Optional[str] = None
    content_type: Optional[str] = None
    platform: Optional[str] = None
    is_reachable: Optional[bool] = None
    last_checked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReleaseRead(BaseModel):
    id: int
    tag_name: str
    name: Optional[str] = None
    published_at: Optional[datetime] = None
    release_url: str
    is_prerelease: bool = False
    source_commit: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    assets: List[ReleaseAssetRead] = []

    class Config:
        from_attributes = True


class VerificationCheckRead(BaseModel):
    id: int
    check_type: str
    status: str
    duration_ms: Optional[int] = None
    checked_at: datetime
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    tls_valid: Optional[bool] = None
    details: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class VerificationStatusSummary(BaseModel):
    overall_status: str
    website_check: Optional[VerificationCheckRead] = None
    repo_check: Optional[VerificationCheckRead] = None
    release_check: Optional[VerificationCheckRead] = None
    all_checks: List[VerificationCheckRead] = []


class AppCapabilityRead(BaseModel):
    capability: str
    detail: Optional[str] = None

    class Config:
        from_attributes = True


class AppListItem(BaseModel):
    id: int
    slug: str
    name: str
    summary: str
    homepage_url: str
    repo_url: Optional[str] = None
    license_state: str
    license_spdx: Optional[str] = None
    platforms: List[str] = []
    primary_category: Optional[CategoryRead] = None
    capabilities: List[str] = []
    verification_status: str
    latest_check_at: Optional[datetime] = None
    score: Optional[float] = None
    match_sources: List[str] = []

    class Config:
        from_attributes = True


class AppDetail(BaseModel):
    id: int
    slug: str
    name: str
    summary: str
    description: str
    homepage_url: str
    repo_url: Optional[str] = None
    license_state: str
    license_spdx: Optional[str] = None
    platforms: List[str] = []
    is_delisted: bool = False
    primary_category: Optional[CategoryRead] = None
    categories: List[CategoryRead] = []
    capabilities: List[AppCapabilityRead] = []
    releases: List[ReleaseRead] = []
    verification_summary: VerificationStatusSummary
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SearchResponse(BaseModel):
    query: str
    normalized_query: str
    intent: Optional[str] = None
    detected_categories: List[str] = []
    suggested_categories: List[CategoryRead] = []
    applied_filters: Dict[str, Any] = {}
    total_results: int
    results: List[AppListItem]


class CorrectionRequestCreate(BaseModel):
    app_identifier: str = Field(..., min_length=1, max_length=200)
    request_type: str = Field(..., pattern="^(correction|removal)$")
    reason: str = Field(..., min_length=5, max_length=5000)
    contact_email: Optional[str] = Field(None, max_length=250, pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class CorrectionRequestRead(BaseModel):
    id: int
    app_id: Optional[int] = None
    app_identifier: Optional[str] = None
    request_type: str
    reason: str
    contact_email: Optional[str] = None
    status: str
    submitted_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None

    class Config:
        from_attributes = True


class CorrectionResolution(BaseModel):
    status: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    resolution_notes: str = Field(..., min_length=1, max_length=2000)
    delist_app: bool = False


class OpsStatusResponse(BaseModel):
    worker_status: str
    last_worker_run: Optional[datetime] = None
    pending_corrections_count: int
    oldest_pending_age_seconds: Optional[float] = None
    total_apps: int
    total_checks: int
    checks_by_status: Dict[str, int]
    recent_jobs: List[Dict[str, Any]] = []

    # Scheduler and Synchronization Observability
    last_scheduler_cycle: Optional[datetime] = None
    next_expected_cycle: Optional[datetime] = None
    pending_jobs: int = 0
    running_jobs: int = 0
    failed_jobs: int = 0
    oldest_pending_job_age_seconds: Optional[float] = None
    jobs_retried: int = 0
    jobs_skipped_rate_limit: int = 0
    stale_apps_count: int = 0
    most_recent_successful_sync: Optional[datetime] = None
    most_recent_sync_failure: Optional[str] = None
    recent_sanitized_failures: List[Dict[str, Any]] = []
    encoder_diagnostics: Optional[Dict[str, Any]] = None
