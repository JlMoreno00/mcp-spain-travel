"""Application configuration via Pydantic Settings.

All settings are read from environment variables with the prefix ``SPAIN_TRAVEL_``.
Use :func:`get_settings` to obtain the singleton instance.

Example env vars::

    SPAIN_TRAVEL_SERPAPI_API_KEY=your_serpapi_key
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

    # --- SerpApi credentials (required for flights via Google Flights) ---
    serpapi_api_key: str = ""

    # --- FlixBus / RapidAPI credentials ---
    flixbus_api_key: str = ""

    # --- Feature flags ---
    ouigo_enabled: bool = True

    # --- Cache configuration (in seconds) ---
    stations_ttl: int = 86_400  # 24h — station catalog changes rarely
    ouigo_ttl: int = 1_800  # 30min — prices are volatile
    flights_ttl: int = 3_600  # 1h — flight offers

    # --- Storage ---
    cache_dir: Path = Path(".cache")

    # --- Server transport ---
    transport: str = "stdio"  # "stdio", "streamable-http", "sse"
    host: str = "127.0.0.1"
    port: int = 8321

    # --- Logging ---
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    return settings
