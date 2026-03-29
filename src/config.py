"""Application configuration via Pydantic Settings.

All settings are read from environment variables with the prefix ``SPAIN_TRAVEL_``.
Use :func:`get_settings` to obtain the singleton instance.

Example env vars::

    SPAIN_TRAVEL_AMADEUS_CLIENT_ID=your_id
    SPAIN_TRAVEL_AMADEUS_CLIENT_SECRET=your_secret
    SPAIN_TRAVEL_OUIGO_ENABLED=true
    SPAIN_TRAVEL_LOG_LEVEL=DEBUG
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the MCP Spain Travel server."""

    model_config = SettingsConfigDict(
        env_prefix="SPAIN_TRAVEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Amadeus API credentials (required for flights) ---
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""

    # --- Feature flags ---
    ouigo_enabled: bool = True

    # --- Cache configuration (in seconds) ---
    stations_ttl: int = 86_400  # 24h — station catalog changes rarely
    ouigo_ttl: int = 1_800  # 30min — prices are volatile
    amadeus_ttl: int = 3_600  # 1h — flight offers

    # --- Storage ---
    cache_dir: Path = Path(".cache")

    # --- Logging ---
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    return settings
