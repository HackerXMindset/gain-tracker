from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load env from repo root .env first (main app), then local .env
REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
LOCAL_ENV = Path(__file__).resolve().parents[1] / ".env"
if REPO_ROOT_ENV.exists():
    load_dotenv(dotenv_path=REPO_ROOT_ENV)
if LOCAL_ENV.exists():
    load_dotenv(dotenv_path=LOCAL_ENV)


class Settings(BaseSettings):
    # Telegram
    api_id: int = Field(..., env="API_ID")
    api_hash: str = Field(..., env="API_HASH")
    mgmt_bot_token: Optional[str] = Field(default=None, env="MGMT_BOT_TOKEN")
    admin_telegram_ids: str = Field(default="", env="ADMIN_TELEGRAM_IDS")

    # Database
    db_url: str = Field(default_factory=lambda: os.getenv("SUPABASE_POOLER_URL", ""), env="SUPABASE_POOLER_URL")
    db_pool_min: int = Field(default=2, env="DB_POOL_MIN")
    db_pool_max: int = Field(default=10, env="DB_POOL_MAX")

    # Runtime
    timezone: str = Field(default="UTC", env="TIMEZONE")
    sessions_dir: str = Field(default="gain_alert_sessions", env="SESSIONS_DIR")

    # Market data
    dex_timeout: int = Field(default=10, env="DEX_TIMEOUT")
    dex_max_retries: int = Field(default=3, env="DEX_MAX_RETRIES")

    # Address patterns
    solana_pattern: str = Field(default=r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", env="SOLANA_PATTERN")
    bnb_pattern: str = Field(default=r"0x[a-fA-F0-9]{40}\b", env="BNB_PATTERN")

    model_config = {
        "env_file": (str(REPO_ROOT_ENV), str(LOCAL_ENV)),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @field_validator("admin_telegram_ids")
    @classmethod
    def validate_admin_ids(cls, value: str) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("Admin IDs must be a string")

        if not value.strip():
            return ""

        ids = [int(id_str.strip()) for id_str in value.split(",") if id_str.strip()]
        for admin_id in ids:
            if admin_id <= 0:
                raise ValueError(f"Invalid admin Telegram ID: {admin_id}")
        return value

    @property
    def admin_telegram_ids_list(self) -> List[int]:
        if not self.admin_telegram_ids:
            return []
        return [int(id_str.strip()) for id_str in self.admin_telegram_ids.split(",") if id_str.strip()]


settings = Settings()
