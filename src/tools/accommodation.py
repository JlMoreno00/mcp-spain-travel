from __future__ import annotations

import logging
from datetime import date as _Date
from typing import Any

from src.providers.google_hotels import GoogleHotelsProvider, RateLimitError

logger = logging.getLogger(__name__)


async def search_accommodation(
    destination: str,
    check_in_date: str,
    check_out_date: str,
    adults: int = 2,
    max_price: float | None = None,
) -> dict[str, Any]:
    try:
        check_in = _Date.fromisoformat(check_in_date)
    except ValueError:
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": f"Invalid check_in_date format: {check_in_date!r}. Use YYYY-MM-DD.",
            }
        }

    try:
        check_out = _Date.fromisoformat(check_out_date)
    except ValueError:
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": f"Invalid check_out_date format: {check_out_date!r}. Use YYYY-MM-DD.",
            }
        }

    if check_in < _Date.today():
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": "check_in_date must be today or in the future.",
            }
        }

    if check_out <= check_in:
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": "check_out_date must be after check_in_date.",
            }
        }

    nights = (check_out - check_in).days

    provider = GoogleHotelsProvider()
    try:
        results = await provider.search_hotels(
            destination=destination,
            check_in=check_in_date,
            check_out=check_out_date,
            adults=adults,
        )
    except RateLimitError:
        return {
            "error": {
                "code": "RATE_LIMIT",
                "message": "SerpApi quota exceeded (250/month free tier), retry later.",
            }
        }
    except Exception as exc:
        logger.error("GoogleHotels search failed (destination=%s): %s", destination, exc)
        return {
            "error": {
                "code": "PROVIDER_ERROR",
                "message": f"Accommodation search failed: {exc}",
            }
        }

    if max_price is not None:
        results = [
            r
            for r in results
            if r.price_per_night_eur is not None and r.price_per_night_eur <= max_price
        ]

    results.sort(key=lambda r: (r.price_per_night_eur is None, r.price_per_night_eur or 0.0))

    return {
        "results": [r.model_dump(mode="json") for r in results],
        "count": len(results),
        "nights": nights,
    }
