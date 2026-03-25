"""
core/config.py
--------------
Central configuration loader using Pydantic Settings.
Reads all values from environment variables / .env file.
"""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Bot ──────────────────────────────────────────────────────────────────
    bot_token: str
    bot_username: str = "your_bot"
    admin_ids: List[int] = []

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str
    postgres_user: str = "botadmin"
    postgres_password: str = "password"
    postgres_db: str = "telegram_bot"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""

    # ── Web ──────────────────────────────────────────────────────────────────
    secret_key: str
    domain: str = "localhost"
    web_port: int = 8000
    telegram_login_bot_token: str = ""

    # ── App ──────────────────────────────────────────────────────────────────
    debug: bool = False
    log_level: str = "INFO"
    timezone: str = "UTC"
    certbot_email: str = "admin@example.com"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        """Allow comma-separated string or list for ADMIN_IDS."""
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()


# Convenience alias
settings = get_settings()
