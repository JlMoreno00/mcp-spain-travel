from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, model_validator

if TYPE_CHECKING:
    from src.models.bus import BusResult
    from src.models.flight import FlightResult
    from src.models.train import TrainResult


class TravelMode(str, Enum):
    TRAIN = "train"
    FLIGHT = "flight"
    BUS = "bus"


class TravelOption(BaseModel):
    mode: TravelMode
    operator: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    price_eur: float | None = None
    co2_kg: float | None = None
    booking_url: str | None = None

    @classmethod
    def from_train_result(cls, result: TrainResult) -> TravelOption:
        return cls(
            mode=TravelMode.TRAIN,
            operator=result.operator,
            departure_time=result.departure_time,
            arrival_time=result.arrival_time,
            duration_minutes=result.duration_minutes,
            price_eur=result.price_eur,
            booking_url=result.booking_url,
        )

    @classmethod
    def from_flight_result(cls, result: FlightResult) -> TravelOption:
        return cls(
            mode=TravelMode.FLIGHT,
            operator=result.airline,
            departure_time=result.departure_time,
            arrival_time=result.arrival_time,
            duration_minutes=result.duration_minutes,
            price_eur=result.price_eur,
            booking_url=result.booking_url,
        )

    @classmethod
    def from_bus_result(cls, result: BusResult) -> TravelOption:
        return cls(
            mode=TravelMode.BUS,
            operator=result.operator,
            departure_time=result.departure_time,
            arrival_time=result.arrival_time,
            duration_minutes=result.duration_minutes,
            price_eur=result.price_eur,
            booking_url=result.booking_url,
        )


class TravelComparison(BaseModel):
    origin: str
    destination: str
    date: str
    options: list[TravelOption] = []
    cheapest: TravelOption | None = None
    fastest: TravelOption | None = None
    greenest: TravelOption | None = None
    partial: bool = False
    missing_modes: list[str] = []

    @model_validator(mode="after")
    def compute_highlights(self) -> TravelComparison:
        priced = [o for o in self.options if o.price_eur is not None]
        if priced and self.cheapest is None:
            self.cheapest = min(priced, key=lambda o: o.price_eur)  # type: ignore[arg-type]
        if self.options and self.fastest is None:
            self.fastest = min(self.options, key=lambda o: o.duration_minutes)
        co2_options = [o for o in self.options if o.co2_kg is not None]
        if co2_options and self.greenest is None:
            self.greenest = min(co2_options, key=lambda o: o.co2_kg)  # type: ignore[arg-type]
        return self
