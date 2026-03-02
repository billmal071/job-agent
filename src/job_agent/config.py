"""Configuration loading with Pydantic settings (env → YAML → defaults)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseModel):
    activity_start_hour: int = 8
    activity_end_hour: int = 23
    schedule_interval: int = 60
    dry_run: bool = False


class MatchingConfig(BaseModel):
    auto_apply_threshold: float = 0.80
    review_threshold: float = 0.70
    model: str = ""


class ResumeConfig(BaseModel):
    master_resume: str = "config/resumes/master.pdf"
    cover_letter_tone: str = "professional"
    default_cover_note: str = (
        "I'm excited about this opportunity and believe my skills "
        "are a strong match. Please see my attached resume for details."
    )


class PlatformConfig(BaseModel):
    enabled: bool = False
    max_requests_per_minute: int = 5
    max_applications_per_day: int = 30
    session_duration_minutes: int = 45
    cooldown_minutes: int = 20
    max_connections_per_day: int = 0


class PlatformsConfig(BaseModel):
    linkedin: PlatformConfig = PlatformConfig(
        enabled=True,
        max_requests_per_minute=3,
        max_applications_per_day=25,
        max_connections_per_day=20,
        session_duration_minutes=45,
        cooldown_minutes=30,
    )
    indeed: PlatformConfig = PlatformConfig(
        max_requests_per_minute=5,
        max_applications_per_day=40,
        session_duration_minutes=60,
    )
    glassdoor: PlatformConfig = PlatformConfig(
        max_requests_per_minute=4,
        max_applications_per_day=30,
        session_duration_minutes=60,
    )
    ziprecruiter: PlatformConfig = PlatformConfig(
        max_requests_per_minute=5,
        max_applications_per_day=40,
        session_duration_minutes=60,
        cooldown_minutes=20,
    )
    dice: PlatformConfig = PlatformConfig(
        max_requests_per_minute=4,
        max_applications_per_day=35,
        session_duration_minutes=60,
        cooldown_minutes=20,
    )
    wellfound: PlatformConfig = PlatformConfig(
        max_requests_per_minute=3,
        max_applications_per_day=20,
        session_duration_minutes=45,
        cooldown_minutes=25,
    )


class BrowserConfig(BaseModel):
    headless: bool = True
    state_dir: str = "~/.job-agent/browser_state"
    proxy: str | None = None


class EmailNotificationConfig(BaseModel):
    enabled: bool = False
    triggers: list[str] = Field(default_factory=lambda: ["failed"])


class WebhookNotificationConfig(BaseModel):
    enabled: bool = False
    triggers: list[str] = Field(
        default_factory=lambda: ["auto_applied", "queued", "failed"]
    )


class NotificationsConfig(BaseModel):
    email: EmailNotificationConfig = EmailNotificationConfig()
    webhook: WebhookNotificationConfig = WebhookNotificationConfig()


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOB_AGENT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AI provider: anthropic, gemini, groq, openrouter, ollama
    ai_provider: str = "gemini"

    # API keys from environment (set the one for your chosen provider)
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""

    flask_secret_key: str = "change-me"
    database_url: str = ""

    # SMTP settings
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_email: str = ""

    # Webhooks
    slack_webhook_url: str = ""
    discord_webhook_url: str = ""

    # Proxy
    proxy_url: str = ""

    # Nested config from YAML
    agent: AgentConfig = AgentConfig()
    matching: MatchingConfig = MatchingConfig()
    resume: ResumeConfig = ResumeConfig()
    platforms: PlatformsConfig = PlatformsConfig()
    browser: BrowserConfig = BrowserConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    dashboard: DashboardConfig = DashboardConfig()

    @property
    def data_dir(self) -> Path:
        path = Path.home() / ".job-agent"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'agent.db'}"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from YAML config file, then override with env vars."""
    yaml_data: dict[str, Any] = {}

    # Load default YAML
    default_path = Path("config/default.yaml")
    if default_path.exists():
        with open(default_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Load override YAML if specified
    if config_path:
        override_path = Path(config_path)
        if override_path.exists():
            with open(override_path) as f:
                override = yaml.safe_load(f) or {}
            yaml_data = _deep_merge(yaml_data, override)

    # Pydantic settings will layer env vars on top
    return Settings(**yaml_data)


def load_profile(profile_path: str | Path) -> dict[str, Any]:
    """Load a job search profile from YAML."""
    with open(profile_path) as f:
        return yaml.safe_load(f) or {}
