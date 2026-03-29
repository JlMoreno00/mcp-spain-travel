from __future__ import annotations

import logging
import re
from datetime import date as _Date
from typing import Any

from src.providers.duffel import DuffelProvider, RateLimitError

logger = logging.getLogger(__name__)

_IATA_RE = re.compile(r"^[A-Z]{3}$")


async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    adults: int = 1,
    cabin_class: str = "ECONOMY",
) -> dict[str, Any]:
    """Search flight offers via Amadeus GDS for a Spanish airport pair.

    Returns:
        {"results": [...], "count": int}
        or {"error": {"code": "INVALID_IATA|INVALID_DATE|RATE_LIMIT|PROVIDER_ERROR", "message": "..."}}
    """
    origin_code = origin.upper().strip()
    dest_code = destination.upper().strip()

    if not _IATA_RE.match(origin_code):
        return {
            "error": {
                "code": "INVALID_IATA",
                "message": (
                    f"Invalid IATA code: {origin!r}. Must be 3 letters (e.g. MAD, BCN, SVQ)."
                ),
            }
        }
    if not _IATA_RE.match(dest_code):
        return {
            "error": {
                "code": "INVALID_IATA",
                "message": (
                    f"Invalid IATA code: {destination!r}. Must be 3 letters (e.g. MAD, BCN, SVQ)."
                ),
            }
        }

    try:
        dep_date = _Date.fromisoformat(departure_date)
    except ValueError:
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": f"Invalid date format: {departure_date!r}. Use YYYY-MM-DD.",
            }
        }

    if dep_date < _Date.today():
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": "Departure date must be today or in the future.",
            }
        }

    duffel = DuffelProvider()
    try:
        results = await duffel.search_flights(
            origin=origin_code,
            destination=dest_code,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
            cabin_class=cabin_class,
        )
    except RateLimitError:
        return {
            "error": {
                "code": "RATE_LIMIT",
                "message": "Duffel quota exceeded, retry later.",
            }
        }
    except Exception as exc:
        logger.error("Duffel search failed (origin=%s, dest=%s): %s", origin_code, dest_code, exc)
        return {
            "error": {
                "code": "PROVIDER_ERROR",
                "message": f"Flight search failed: {exc}",
            }
        }

    return {
        "results": [r.model_dump(mode="json") for r in results],
        "count": len(results),
    }
