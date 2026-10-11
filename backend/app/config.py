import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "Open-Source Software Discovery Engine"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./oss_discovery.db")
    OPS_TOKEN: Optional[str] = os.getenv("OPS_TOKEN", None)
    GITHUB_TOKEN: Optional[str] = os.getenv("GITHUB_TOKEN", None)
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    SEMANTIC_ENCODER_TYPE: str = os.getenv("SEMANTIC_ENCODER_TYPE", "deterministic_test")  # "deterministic_test" | "sentence_transformers" | "none"
    WEBSITE_FRESHNESS_DAYS: int = 7
    REPO_FRESHNESS_DAYS: int = 30
    SIMILARITY_THRESHOLD: float = 0.35
    ENABLE_VECTOR_SEARCH: bool = True

    # Scheduler and Synchronization Configuration
    SCHEDULER_INTERVAL_HOURS: int = int(os.getenv("SCHEDULER_INTERVAL_HOURS", "24"))
    SCHEDULER_MAX_APPS_PER_RUN: int = int(os.getenv("SCHEDULER_MAX_APPS_PER_RUN", "50"))
    SCHEDULER_REQUEST_BUDGET: int = int(os.getenv("SCHEDULER_REQUEST_BUDGET", "150"))
    SCHEDULER_MAX_RETRIES: int = int(os.getenv("SCHEDULER_MAX_RETRIES", "5"))
    SCHEDULER_RETRY_BASE_SECONDS: int = int(os.getenv("SCHEDULER_RETRY_BASE_SECONDS", "300"))
    SCHEDULER_RETRY_MAX_SECONDS: int = int(os.getenv("SCHEDULER_RETRY_MAX_SECONDS", "86400"))
    ALERT_WEBHOOK_URL: Optional[str] = os.getenv("ALERT_WEBHOOK_URL", None)
    ALERT_FAILURE_THRESHOLD: int = int(os.getenv("ALERT_FAILURE_THRESHOLD", "3"))

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
