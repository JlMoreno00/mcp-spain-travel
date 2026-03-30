from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BusStation(BaseModel):
    name: str
    city_id: str
    station_id: str
    city: str
    latitude: float | None = None
    longitude: float | None = None


class BusResult(BaseModel):
    operator: str
    departure_station: str
    arrival_station: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    price_eur: float | None = None
    currency: str = "EUR"
    changeovers: int = 0
    booking_url: str | None = None
