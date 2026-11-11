"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"  # development | test | production
    APP_NAME: str = "TEC THA Follow-Up Engine"
    PUBLIC_BASE_URL: str = "http://localhost:3000"  # used to build shareable booking links

    DATABASE_URL: str = "postgresql+psycopg://tectha:tectha_dev_pw@localhost:5432/tectha"

    # Security
    JWT_SECRET: str = Field(default="change-me-in-production-please-32b", min_length=32)
    JWT_EXPIRE_MINUTES: int = 480
    COOKIE_SECURE: bool = False  # must be true behind HTTPS in production
    COOKIE_NAME: str = "tt_session"
    ENCRYPTION_KEY: str = ""  # Fernet key used to encrypt WhatsApp access tokens at rest
    CORS_ORIGINS: str = "http://localhost:3000"
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    PASSWORD_RESET_MINUTES: int = 30

    # WhatsApp Business Platform (Cloud API) — platform-level app credentials
    WHATSAPP_GRAPH_BASE_URL: str = "https://graph.facebook.com"
    WHATSAPP_GRAPH_VERSION: str = "v23.0"
    WHATSAPP_APP_SECRET: str = ""  # used to validate X-Hub-Signature-256 on webhooks
    WHATSAPP_VERIFY_TOKEN: str = ""  # used for the webhook subscription handshake
    WHATSAPP_HTTP_TIMEOUT: float = 15.0
    ALLOW_UNSIGNED_WEBHOOKS: bool = False  # never enable in production

    # Reminder engine
    REMINDER_MAX_ATTEMPTS: int = 3
    REMINDER_RETRY_MINUTES: str = "5,30,120"
    WORKER_INTERVAL_SECONDS: int = 60
    PROCESSING_STALE_MINUTES: int = 10

    # Demo
    ALLOW_DEMO_CLOCK: bool = True  # only affects hospitals flagged is_demo

    # Email for password resets (optional)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@tectha.example"
    SMTP_STARTTLS: bool = True

    @property
    def retry_backoff_minutes(self) -> list[int]:
        return [int(x) for x in self.REMINDER_RETRY_MINUTES.split(",") if x.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
