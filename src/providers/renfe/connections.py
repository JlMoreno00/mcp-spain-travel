from __future__ import annotations

import asyncio
import logging

from src.models.connection import MultiLegResult, TrainLeg
from src.providers.renfe.scraper import search_with_prices

logger = logging.getLogger(__name__)

HUB_STATIONS = [
    {"name": "MADRID (TODAS)", "code": "MADRI", "city": "Madrid"},
    {"name": "BARCELONA (TODAS)", "code": "BARCE", "city": "Barcelona"},
    {"name": "ZARAGOZA DELICIAS", "code": "71801", "city": "Zaragoza"},
    {"name": "CORDOBA", "code": "CORDO", "city": "Córdoba"},
    {"name": "VALLADOLID CAMPO GRANDE", "code": "35400", "city": "Valladolid"},
]


class ConnectionFinder:
    async def find_connections(
        self,
        origin: str,
        destination: str,
        date: str,
        min_connection_minutes: int = 45,
        max_connection_minutes: int = 180,
    ) -> list[MultiLegResult]:
        eligible_hubs = [
            hub
            for hub in HUB_STATIONS
            if not self._matches_city(origin, hub["city"])
            and not self._matches_city(destination, hub["city"])
        ]

        tasks = [
            self._search_via_hub(
                hub, origin, destination, date, min_connection_minutes, max_connection_minutes
            )
            for hub in eligible_hubs
        ]
        hub_results = await asyncio.gather(*tasks)

        all_connections: list[MultiLegResult] = []
        for result in hub_results:
            all_connections.extend(result)

        all_connections.sort(key=lambda r: r.total_duration_minutes)
        return all_connections[:10]

    def _matches_city(self, station_input: str, hub_city: str) -> bool:
        s = station_input.lower()
        c = hub_city.lower()
        return c in s or s in c

    async def _search_via_hub(
        self,
        hub: dict,
        origin: str,
        destination: str,
        date: str,
        min_conn: int,
        max_conn: int,
    ) -> list[MultiLegResult]:
        try:
            leg1_trains, leg2_trains = await asyncio.gather(
                search_with_prices(origin, hub["name"], date),
                search_with_prices(hub["name"], destination, date),
            )
        except Exception as exc:
            logger.debug("Hub %s search failed: %s", hub["city"], exc)
            return []

        connections = []
        for leg1 in leg1_trains:
            for leg2 in leg2_trains:
                wait_minutes = int((leg2.departure_time - leg1.arrival_time).total_seconds() / 60)
                if not (min_conn <= wait_minutes <= max_conn):
                    continue

                if leg1.price_eur is not None and leg2.price_eur is not None:
                    total_price: float | None = leg1.price_eur + leg2.price_eur
                else:
                    total_price = None

                connections.append(
                    MultiLegResult(
                        legs=[
                            TrainLeg(
                                operator=leg1.operator,
                                train_number=leg1.train_number,
                                origin=origin,
                                destination=hub["name"],
                                departure_time=leg1.departure_time,
                                arrival_time=leg1.arrival_time,
                                duration_minutes=leg1.duration_minutes,
                                price_eur=leg1.price_eur,
                            ),
                            TrainLeg(
                                operator=leg2.operator,
                                train_number=leg2.train_number,
                                origin=hub["name"],
                                destination=destination,
                                departure_time=leg2.departure_time,
                                arrival_time=leg2.arrival_time,
                                duration_minutes=leg2.duration_minutes,
                                price_eur=leg2.price_eur,
                            ),
                        ],
                        total_duration_minutes=(
                            leg1.duration_minutes + wait_minutes + leg2.duration_minutes
                        ),
                        total_price_eur=total_price,
                        connection_station=hub["name"],
                        connection_wait_minutes=wait_minutes,
                        booking_urls=[leg1.booking_url, leg2.booking_url],
                    )
                )

        return connections
