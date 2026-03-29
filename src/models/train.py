from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Station(BaseModel):
    name: str
    code: str
    city: str
    province: str = ""
    station_types: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None


class TrainResult(BaseModel):
    operator: str
    train_number: str | None = None
    origin_code: str
    destination_code: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    price_eur: float | None = None
    currency: str = "EUR"
    booking_url: str | None = None
