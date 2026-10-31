# config/settings.py
"""Global configuration loader.
Loads environment variables from .env and campaign parameters from campaign.json.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Read an env var, treating template placeholders like YOUR_..._KEY as unset."""
    value = os.getenv(name, default).strip()
    return "" if value.upper().startswith("YOUR_") else value


class Settings:
    BASE_DIR: Path = BASE_DIR
    OPENAI_API_KEY: str = _env("OPENAI_API_KEY")
    OPENAI_MODEL: str = _env("OPENAI_MODEL", "gpt-4o-mini")
    SENDING_MODE: str = _env("SENDING_MODE", "simulation")  # 'simulation' or 'real'
    SMTP_HOST: str = _env("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(_env("SMTP_PORT", "587") or 587)
    SMTP_USER: str = _env("SMTP_USER")
    SMTP_PASSWORD: str = _env("SMTP_PASSWORD")
    # When set, real-mode emails go to this address instead of the creator (safe demo).
    TEST_RECIPIENT_OVERRIDE: str = _env("TEST_RECIPIENT_OVERRIDE")
    DATABASE_PATH: Path = BASE_DIR / "database" / "outreach.db"
    DATA_ROOT: Path = BASE_DIR / "data"
    CONFIG_PATH: Path = BASE_DIR / "config" / "campaign.json"
    PROMPT_PATH: Path = BASE_DIR / "prompts" / "outreach_prompt.txt"
    LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")

    @property
    def CACHE_DIR(self) -> Path:
        return self.DATA_ROOT / "raw" / "cache"

    def ensure_directories(self) -> None:
        """Ensure all required project runtime directories exist."""
        Path(self.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        for sub in ("raw", "processed", "exports"):
            (self.DATA_ROOT / sub).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()


DEFAULT_CAMPAIGN: Dict[str, Any] = {
    "campaign_id": "DEFAULT_CAMPAIGN",
    "campaign_name": "Influencer Outreach",
    "brand": {
        "name": "DevFlow AI",
        "product": "an AI coding assistant for developers",
        "product_short": "an AI coding assistant",
        "sender_name": "The DevFlow AI team",
        "sender_title": "Creator Partnerships",
    },
    "platform": "YouTube",
    "target_niche": "Technology",
    "target_sub_niches": ["Software Development", "AI & Machine Learning"],
    "min_followers": 5000,
    "max_followers": 100000,
    "min_engagement_rate": 1.0,
    "max_days_since_last_upload": 90,
    "search_queries": ["python tutorial"],
    "search_modes": ["relevance"],
    "results_per_query": 20,
    "max_channels": 120,
    "recent_videos_per_channel": 3,
    "collection_workers": 4,
    "request_interval_seconds": 0.5,
    "cache_ttl_days": 7,
    "auto_approve_valid_messages": True,
    "sending_mode": "simulation",
}


def load_campaign_config() -> Dict[str, Any]:
    """Load campaign.json merged over defaults, so missing keys never crash a stage."""
    config = json.loads(json.dumps(DEFAULT_CAMPAIGN))
    if settings.CONFIG_PATH.exists():
        with open(settings.CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        brand = {**config["brand"], **loaded.get("brand", {})}
        config.update(loaded)
        config["brand"] = brand
    return config
