from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TrainLeg(BaseModel):
    operator: str
    train_number: str | None = None
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    price_eur: float | None = None


class MultiLegResult(BaseModel):
    legs: list[TrainLeg]
    total_duration_minutes: int
    total_price_eur: float | None
    connection_station: str
    connection_wait_minutes: int
    booking_urls: list[str | None] = []
