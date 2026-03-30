from __future__ import annotations

from pydantic import BaseModel


class AccommodationResult(BaseModel):
    name: str
    hotel_class: str | None = None
    rating: float | None = None
    price_per_night_eur: float | None = None
    total_price_eur: float | None = None
    accommodation_type: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    link: str | None = None
    amenities: list[str] = []
