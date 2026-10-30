from functools import lru_cache

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = Field(
        default="postgresql+psycopg://personal_dot:personal_dot_dev@localhost:5432/personal_dot"
    )
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "personal-dot"
    rq_job_timeout_seconds: int = Field(default=3600, ge=60, le=86_400)
    rq_result_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    rq_failure_ttl_seconds: int = Field(default=604_800, ge=0, le=2_592_000)
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    scheduler_poll_seconds: float = Field(default=5.0, gt=0)
    scheduler_batch_size: int = Field(default=100, ge=1, le=1000)
    scheduler_max_catch_up: int = Field(default=10, ge=1, le=1000)
    scheduler_requeue_after_seconds: int = Field(default=60, ge=5)
    scheduler_stale_task_seconds: int = Field(default=3900, ge=60)
    notification_provider: Literal["pushover"] = "pushover"
    notification_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    pushover_api_token: SecretStr | None = None
    pushover_user_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_service_tier: Literal["default"] | None = None
    docs_maintenance_live_enabled: bool = False
    openai_model: str = "gpt-6-luna"
    openai_reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max"
    ] = "low"
    openai_output_verbosity: Literal["low", "medium", "high"] | None = "medium"
    openai_max_output_tokens: int = Field(default=4096, gt=0)
    openai_timeout_seconds: float = Field(default=120.0, gt=0)
    openai_max_retries: int = Field(default=2, ge=0, le=10)
    # GitHub credentials are file-backed; no key/token values enter task data.
    github_owner: str = ""
    github_app_id: int | None = Field(default=None, ge=1)
    github_installation_id: int | None = Field(default=None, ge=1)
    github_app_private_key_path: str = ""
    github_timeout_seconds: float = Field(default=15, gt=0, le=60)
    github_response_bytes: int = Field(default=2_097_152, ge=1024, le=8_388_608)
    github_max_pages: int = Field(default=100, ge=1, le=100)
    github_inventory_entries: int = Field(default=2000, ge=1, le=10_000)
    github_tree_requests: int = Field(default=64, ge=1, le=200)
    github_max_files: int = Field(default=40, ge=1, le=100)
    github_file_bytes: int = Field(default=65_536, ge=1, le=262_144)
    github_context_bytes: int = Field(default=262_144, ge=2, le=1_048_576)
    docs_publish_live_enabled: bool = False
    docs_publish_check_polls: int = Field(default=12, ge=1, le=60)
    docs_publish_poll_seconds: float = Field(default=5, gt=0, le=30)
    github_commit_author_name: str = "Zachary Kralec"
    github_commit_author_email: str = "157630586+zkralec@users.noreply.github.com"
    docs_preview_live_enabled: bool = False
    docs_preview_editor_model: str = ""
    docs_preview_reviewer_model: str = ""
    docs_preview_output_tokens: int = Field(default=2048, ge=128, le=4096)
    docs_preview_max_files: int = Field(default=3, ge=1, le=3)
    docs_preview_max_changed_lines: int = Field(default=300, ge=1, le=300)
    agent_max_tool_rounds: int = Field(default=8, ge=1, le=32)


@lru_cache
def get_settings() -> Settings:
    return Settings()
