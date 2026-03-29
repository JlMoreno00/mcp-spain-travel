from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from functools import lru_cache

from src.cache.manager import TTLCache
from src.config import get_settings
from src.models.train import TrainResult

logger = logging.getLogger(__name__)


class OUIGOProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._cache: TTLCache[list[TrainResult]] = TTLCache(default_ttl_seconds=settings.ouigo_ttl)

    async def search_trains(
        self,
        origin: str,
        destination: str,
        date: str,
        passengers: int = 1,
    ) -> list[TrainResult]:
        if not get_settings().ouigo_enabled:
            return []

        cache_key = f"ouigo:{origin}:{destination}:{date}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                _blocking_search,
                origin,
                destination,
                date,
            )
        except Exception as exc:
            logger.warning(
                "OUIGO provider failed (origin=%s, dest=%s): %s", origin, destination, exc
            )
            return []

        self._cache.set(cache_key, results)
        return results


def _blocking_search(origin: str, destination: str, date: str) -> list[TrainResult]:
    try:
        from ouigo.ouigo import Ouigo  # type: ignore[import-untyped]
    except Exception as exc:
        logger.warning("OUIGO package import failed: %s", exc)
        return []

    try:
        client = Ouigo("ES")
        trips = client.journal_search(
            origin=origin,
            destination=destination,
            outbound_date=date,
        )
        if not trips:
            return []
        return [_map_trip(trip, origin, destination) for trip in trips]
    except Exception as exc:
        logger.warning("OUIGO search failed: %s", exc)
        return []


def _map_trip(trip: object, origin: str, destination: str) -> TrainResult:
    dep: datetime = getattr(trip, "departure_timestamp")
    price: float = getattr(trip, "price", 0.0)
    station_code: str = getattr(trip, "_u_i_c_station_code", "")
    train_name: str = getattr(trip, "name", "")
    date_str: str = getattr(trip, "outbound", dep.strftime("%Y-%m-%d"))

    return TrainResult(
        operator="OUIGO",
        train_number=train_name or None,
        origin_code=station_code,
        destination_code=destination,
        departure_time=dep,
        arrival_time=dep,
        duration_minutes=0,
        price_eur=float(price),
        booking_url="https://www.ouigo.com/es/",
    )
