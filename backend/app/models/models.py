from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, BigInteger, JSON, Float
)
from sqlalchemy.orm import relationship
from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(100), index=True, nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    parent = relationship("Category", remote_side=[id], backref="subcategories")
    aliases = relationship("CategoryAlias", back_populates="category", cascade="all, delete-orphan")
    apps = relationship("AppCategory", back_populates="category")


class CategoryAlias(Base):
    __tablename__ = "category_aliases"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    alias = Column(String(100), index=True, nullable=False)
    match_type = Column(String(50), default="exact")

    category = relationship("Category", back_populates="aliases")


class App(Base):
    __tablename__ = "apps"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(120), unique=True, index=True, nullable=False)
    name = Column(String(150), index=True, nullable=False)
    summary = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    homepage_url = Column(String(500), nullable=False)
    repo_url = Column(String(500), nullable=True)
    license_state = Column(String(50), default="confirmed_open_source", nullable=False)
    license_spdx = Column(String(100), nullable=True)
    primary_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    platforms = Column(JSON, default=list, nullable=False)
    is_delisted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    primary_category = relationship("Category", foreign_keys=[primary_category_id])
    categories = relationship("AppCategory", back_populates="app", cascade="all, delete-orphan")
    capabilities = relationship("AppCapability", back_populates="app", cascade="all, delete-orphan")
    releases = relationship("AppRelease", back_populates="app", cascade="all, delete-orphan")
    search_document = relationship("SearchDocument", back_populates="app", uselist=False, cascade="all, delete-orphan")
    verification_checks = relationship("VerificationCheck", back_populates="app", cascade="all, delete-orphan")
    correction_requests = relationship("CorrectionRequest", back_populates="app")
    schedules = relationship("VerificationSchedule", back_populates="app", cascade="all, delete-orphan")


class AppCategory(Base):
    __tablename__ = "app_categories"

    app_id = Column(Integer, ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True)
    is_primary = Column(Boolean, default=False)

    app = relationship("App", back_populates="categories")
    category = relationship("Category", back_populates="apps")


class AppCapability(Base):
    __tablename__ = "app_capabilities"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id", ondelete="CASCADE"), nullable=False)
    capability = Column(String(120), index=True, nullable=False)
    detail = Column(Text, nullable=True)

    app = relationship("App", back_populates="capabilities")


class AppRelease(Base):
    __tablename__ = "app_releases"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id", ondelete="CASCADE"), nullable=False)
    tag_name = Column(String(100), nullable=False)
    name = Column(String(200), nullable=True)
    published_at = Column(DateTime, nullable=True)
    release_url = Column(String(500), nullable=False)
    is_prerelease = Column(Boolean, default=False)
    source_commit = Column(String(100), nullable=True)
    last_synced_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    etag = Column(String(200), nullable=True)

    app = relationship("App", back_populates="releases")
    assets = relationship("ReleaseAsset", back_populates="release", cascade="all, delete-orphan")


class ReleaseAsset(Base):
    __tablename__ = "release_assets"

    id = Column(Integer, primary_key=True, index=True)
    release_id = Column(Integer, ForeignKey("app_releases.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(250), nullable=False)
    download_url = Column(String(500), nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    checksum = Column(String(128), nullable=True)
    checksum_algorithm = Column(String(30), nullable=True)
    content_type = Column(String(100), nullable=True)
    platform = Column(String(50), nullable=True)
    is_reachable = Column(Boolean, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)

    release = relationship("AppRelease", back_populates="assets")


class VerificationSchedule(Base):
    __tablename__ = "verification_schedules"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True)
    check_type = Column(String(60), nullable=False, index=True)
    status = Column(String(50), default="IDLE", nullable=False, index=True)
    scheduled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=5, nullable=False)
    last_error = Column(Text, nullable=True)
    locked_by = Column(String(100), nullable=True)
    locked_at = Column(DateTime, nullable=True)

    app = relationship("App", back_populates="schedules")


class SearchDocument(Base):
    __tablename__ = "search_documents"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id", ondelete="CASCADE"), unique=True, nullable=False)
    title = Column(String(200), nullable=False)
    document_text = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=True)
    model_name = Column(String(100), nullable=True)
    embedding_dim = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    app = relationship("App", back_populates="search_document")


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id", ondelete="CASCADE"), nullable=True)
    run_type = Column(String(50), default="manual", nullable=False)
    status = Column(String(50), default="SUCCESS", nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    summary = Column(Text, nullable=True)


class VerificationCheck(Base):
    __tablename__ = "verification_checks"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("verification_runs.id", ondelete="SET NULL"), nullable=True)
    app_id = Column(Integer, ForeignKey("apps.id", ondelete="CASCADE"), nullable=False)
    check_type = Column(String(60), nullable=False)
    status = Column(String(50), nullable=False)
    duration_ms = Column(Integer, nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    http_status = Column(Integer, nullable=True)
    final_url = Column(String(500), nullable=True)
    tls_valid = Column(Boolean, nullable=True)
    details = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    app = relationship("App", back_populates="verification_checks")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(100), nullable=False)
    status = Column(String(50), default="PENDING", nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    items_processed = Column(Integer, default=0, nullable=False)
    items_added = Column(Integer, default=0, nullable=False)
    items_updated = Column(Integer, default=0, nullable=False)
    requests_made = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)


class CorrectionRequest(Base):
    __tablename__ = "correction_requests"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id", ondelete="SET NULL"), nullable=True)
    app_identifier = Column(String(200), nullable=True)
    request_type = Column(String(50), nullable=False)
    reason = Column(Text, nullable=False)
    contact_email = Column(String(250), nullable=True)
    status = Column(String(50), default="PENDING", nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    app = relationship("App", back_populates="correction_requests")
