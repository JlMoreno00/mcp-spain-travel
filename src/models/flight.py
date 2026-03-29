from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Airport(BaseModel):
    iata_code: str
    name: str
    city: str


class FlightResult(BaseModel):
    airline: str
    flight_number: str
    origin_airport: Airport
    destination_airport: Airport
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    price_eur: float
    currency: str = "EUR"
    stops: int = 0
    cabin_class: str = "ECONOMY"
    booking_url: str | None = None
