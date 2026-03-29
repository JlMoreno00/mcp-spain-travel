from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from src.cache.manager import FileTTLCache
from src.config import get_settings
from src.models.train import Station, TrainResult

logger = logging.getLogger(__name__)

_STATIONS_CSV_URL = "https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv"
_GTFS_ZIP_URL = "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip"

_CACHE_KEY_STATIONS = "renfe_stations_v1"
_CACHE_KEY_GTFS = "renfe_gtfs_v1"


class RenfeCKANProvider:
    """Renfe open-data provider.

    Implements both StationProvider and TrainProvider protocols using Renfe's
    public CKAN portal data:
    - Station catalog from estaciones.csv (no CKAN datastore; direct file download)
    - Train schedules from GTFS ZIP (AV/LD/MD services only, no pricing)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._cache: FileTTLCache = FileTTLCache(
            cache_dir=settings.cache_dir / "renfe",
            default_ttl_seconds=settings.stations_ttl,
        )

    async def list_stations(
        self,
        city: str | None = None,
        station_type: str = "all",
    ) -> list[Station]:
        stations = await self._load_stations()
        if city:
            city_lower = city.lower()
            stations = [
                s for s in stations if city_lower in s.city.lower() or city_lower in s.name.lower()
            ]
        if station_type != "all":
            type_lower = station_type.lower()
            stations = [
                s for s in stations if any(type_lower in t.lower() for t in s.station_types)
            ]
        return stations

    async def search_trains(
        self,
        origin: str,
        destination: str,
        date: str,
        passengers: int = 1,
    ) -> list[TrainResult]:
        gtfs = await self._load_gtfs()
        if gtfs is None:
            logger.warning("GTFS data unavailable — returning empty train results")
            return []

        travel_date = datetime.strptime(date, "%Y-%m-%d").date()
        return _query_gtfs(gtfs, origin, destination, travel_date)

    async def _load_stations(self) -> list[Station]:
        cached = self._cache.get(_CACHE_KEY_STATIONS)
        if cached is not None:
            return [Station(**s) for s in cached]

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(_STATIONS_CSV_URL)
            response.raise_for_status()
            raw = response.content.decode("latin-1")

        stations = _parse_stations_csv(raw)
        self._cache.set(
            _CACHE_KEY_STATIONS,
            [s.model_dump() for s in stations],
        )
        logger.info("Loaded %d Renfe stations from CSV", len(stations))
        return stations

    async def _load_gtfs(self) -> dict[str, Any] | None:
        cached = self._cache.get(_CACHE_KEY_GTFS)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(_GTFS_ZIP_URL)
                response.raise_for_status()
                gtfs = _parse_gtfs_zip(response.content)
            self._cache.set(_CACHE_KEY_GTFS, gtfs)
            logger.info(
                "Loaded Renfe GTFS: %d stops, %d trips, %d stop_times",
                len(gtfs["stops"]),
                len(gtfs["trips"]),
                len(gtfs["stop_times"]),
            )
            return gtfs
        except Exception as exc:
            logger.error("Failed to load Renfe GTFS: %s", exc)
            return None


def _parse_stations_csv(raw: str) -> list[Station]:
    reader = csv.DictReader(io.StringIO(raw), delimiter=";", quotechar='"')
    stations: list[Station] = []
    for row in reader:
        code = _clean(row.get("CODIGO", ""))
        name = _clean(row.get("DESCRIPCION", ""))
        city = _clean(row.get("POBLACION", ""))
        province = _clean(row.get("PROVINCIA", ""))
        if not code or not name:
            continue
        types: list[str] = []
        if _clean(row.get("CERCANIAS", "")).upper() == "SI":
            types.append("cercanias")
        if _clean(row.get("FEVE", "")).upper() == "SI":
            types.append("feve")
        if not types:
            types.append("ld")
        lat_str = _clean(row.get("LATITUD", ""))
        lon_str = _clean(row.get("LONGITUD", ""))
        stations.append(
            Station(
                code=code,
                name=name,
                city=city,
                province=province,
                station_types=types,
                latitude=float(lat_str) if lat_str else None,
                longitude=float(lon_str) if lon_str else None,
            )
        )
    return stations


def _clean(value: str) -> str:
    return value.strip().strip('"').strip()


def _parse_gtfs_zip(content: bytes) -> dict[str, Any]:
    zf = zipfile.ZipFile(io.BytesIO(content))

    def _read_csv(name: str) -> list[dict[str, str]]:
        with zf.open(name) as f:
            text = f.read().decode("utf-8")
        reader = csv.DictReader(text.splitlines())
        return [{k.strip(): v.strip() for k, v in row.items()} for row in reader]

    stops = {row["stop_id"]: row for row in _read_csv("stops.txt")}
    routes = {row["route_id"]: row for row in _read_csv("routes.txt")}
    trips = _read_csv("trips.txt")
    calendar = {row["service_id"]: row for row in _read_csv("calendar.txt")}
    calendar_dates = _read_csv("calendar_dates.txt")

    stop_times_raw = _read_csv("stop_times.txt")
    stop_times: dict[str, list[dict[str, str]]] = {}
    for entry in stop_times_raw:
        tid = entry["trip_id"]
        stop_times.setdefault(tid, []).append(entry)
    for entries in stop_times.values():
        entries.sort(key=lambda e: int(e.get("stop_sequence", "0")))

    return {
        "stops": stops,
        "routes": routes,
        "trips": trips,
        "calendar": calendar,
        "calendar_dates": calendar_dates,
        "stop_times": stop_times,
    }


def _service_active_on(
    service_id: str,
    travel_date: date,
    calendar: dict[str, Any],
    calendar_dates: list[dict[str, str]],
) -> bool:
    date_str = travel_date.strftime("%Y%m%d")
    for cd in calendar_dates:
        if cd["service_id"] == service_id and cd["date"] == date_str:
            return cd["exception_type"] == "1"

    cal = calendar.get(service_id)
    if cal is None:
        return False
    start = datetime.strptime(cal["start_date"], "%Y%m%d").date()
    end = datetime.strptime(cal["end_date"], "%Y%m%d").date()
    if not (start <= travel_date <= end):
        return False
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return cal.get(day_names[travel_date.weekday()], "0") == "1"


def _resolve_stop_ids(query: str, stops: dict[str, Any]) -> list[str]:
    q = query.lower()
    return [stop_id for stop_id, info in stops.items() if q in info.get("stop_name", "").lower()]


def _parse_time(time_str: str, base_date: date) -> datetime:
    parts = time_str.split(":")
    hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
    extra_days = hours // 24
    hours = hours % 24
    return datetime(
        base_date.year,
        base_date.month,
        base_date.day,
        hours,
        minutes,
        seconds,
    ) + timedelta(days=extra_days)


def _query_gtfs(
    gtfs: dict[str, Any],
    origin: str,
    destination: str,
    travel_date: date,
) -> list[TrainResult]:
    origin_ids = set(_resolve_stop_ids(origin, gtfs["stops"]))
    dest_ids = set(_resolve_stop_ids(destination, gtfs["stops"]))

    if not origin_ids or not dest_ids:
        logger.debug("No GTFS stops found for origin=%s dest=%s", origin, destination)
        return []

    results: list[TrainResult] = []

    for trip in gtfs["trips"]:
        trip_id = trip["trip_id"]
        service_id = trip["service_id"]
        if not _service_active_on(
            service_id, travel_date, gtfs["calendar"], gtfs["calendar_dates"]
        ):
            continue

        entries = gtfs["stop_times"].get(trip_id, [])
        origin_entry: dict[str, str] | None = None
        dest_entry: dict[str, str] | None = None

        for entry in entries:
            sid = entry["stop_id"]
            if origin_entry is None and sid in origin_ids:
                origin_entry = entry
            elif origin_entry is not None and sid in dest_ids:
                dest_entry = entry
                break

        if origin_entry is None or dest_entry is None:
            continue

        dep = _parse_time(origin_entry["departure_time"], travel_date)
        arr = _parse_time(dest_entry["arrival_time"], travel_date)
        duration = int((arr - dep).total_seconds() / 60)

        route = gtfs["routes"].get(trip.get("route_id", ""), {})
        operator_name = route.get("route_short_name", "Renfe")

        origin_stop = gtfs["stops"].get(origin_entry["stop_id"], {})
        dest_stop = gtfs["stops"].get(dest_entry["stop_id"], {})

        results.append(
            TrainResult(
                operator=operator_name,
                train_number=trip.get("trip_short_name") or None,
                origin_code=origin_entry["stop_id"],
                destination_code=dest_entry["stop_id"],
                departure_time=dep,
                arrival_time=arr,
                duration_minutes=duration,
                price_eur=None,
                booking_url="https://www.renfe.com/es/es/viajeros/billetes-y-ofertas/compra-tu-billete",
            )
        )

    results.sort(key=lambda r: r.departure_time)
    logger.info(
        "GTFS found %d trains for %s→%s on %s",
        len(results),
        origin,
        destination,
        travel_date,
    )
    return results
