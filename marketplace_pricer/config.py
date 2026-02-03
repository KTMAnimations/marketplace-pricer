from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("MP_DATA_DIR", "data"))
    sqlite_path: Path = Path(os.getenv("MP_SQLITE_PATH", "data/mp.db"))

    # IMAP (Craigslist saved search alerts)
    imap_host: str | None = os.getenv("MP_IMAP_HOST")
    imap_username: str | None = os.getenv("MP_IMAP_USERNAME")
    imap_password: str | None = os.getenv("MP_IMAP_PASSWORD")
    imap_folder: str = os.getenv("MP_IMAP_FOLDER", "INBOX")

    # Alerts
    discord_webhook_url: str | None = os.getenv("MP_DISCORD_WEBHOOK_URL")
    telegram_bot_token: str | None = os.getenv("MP_TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = os.getenv("MP_TELEGRAM_CHAT_ID")

    # Facebook scraping (Playwright)
    facebook_storage_state_path: Path = Path(
        os.getenv("MP_FACEBOOK_STORAGE_STATE_PATH", "data/facebook_storage_state.json")
    )
    facebook_headless: bool = _env_bool("MP_FACEBOOK_HEADLESS", True)

    # eBay API (for comps; requires your own keys)
    ebay_client_id: str | None = os.getenv("MP_EBAY_CLIENT_ID")
    ebay_client_secret: str | None = os.getenv("MP_EBAY_CLIENT_SECRET")

    # Nextdoor API (requires access/token)
    nextdoor_access_token: str | None = os.getenv("MP_NEXTDOOR_ACCESS_TOKEN")
