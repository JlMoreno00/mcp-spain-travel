from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx
import json5

from src.models.train import TrainResult
from src.providers.renfe import dwr

logger = logging.getLogger(__name__)

_STATIONS_FILE = Path(__file__).parent.parent.parent / "data" / "renfe_stations.json"
_SEARCH_URL = "https://venta.renfe.com/vol/buscarTren.do?Idioma=es&Pais=ES"
_DWR_BASE = "https://venta.renfe.com/vol/dwr/call/plaincall/"
_SYSTEM_ID_URL = f"{_DWR_BASE}__System.generateId.dwr"
_UPDATE_SESSION_URL = f"{_DWR_BASE}buyEnlacesManager.actualizaObjetosSesion.dwr"
_TRAIN_LIST_URL = f"{_DWR_BASE}trainEnlacesManager.getTrainsList.dwr"

_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SpainTravelMCP/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

_stations_cache: dict | None = None


def _load_stations() -> dict:
    global _stations_cache
    if _stations_cache is None:
        with open(_STATIONS_FILE, encoding="utf-8") as f:
            _stations_cache = json.load(f)
    return _stations_cache


def find_station_code(name: str) -> tuple[str, str] | None:
    stations = _load_stations()
    name_upper = name.upper()

    for station_name, data in stations.items():
        if station_name.upper() == name_upper:
            return station_name, data["cdgoEstacion"]

    for station_name, data in stations.items():
        if name_upper in station_name.upper():
            return station_name, data["cdgoEstacion"]

    return None


def _extract_dwr_token(text: str) -> str:
    match = re.search(r'r\.handleCallback\("[^"]+","[^"]+","([^"]+)"\)', text)
    if not match:
        raise ValueError(f"DWR token not found in response ({len(text)} chars)")
    return match.group(1)


def _extract_train_list(text: str) -> dict:
    match = re.search(r"r\.handleCallback\([^,]+,\s*[^,]+,\s*(\{.*\})\);", text, re.DOTALL)
    if not match:
        raise ValueError(f"Train list JSON not found in response ({len(text)} chars)")
    return json5.loads(match.group(1))


def _run_dwr_flow(
    origin_name: str,
    origin_code: str,
    dest_name: str,
    dest_code: str,
    departure_dt: datetime,
) -> list[dict]:
    batch_id = dwr.get_batch_id_generator()
    search_id = dwr.create_search_id()
    date_str = departure_dt.strftime("%d/%m/%Y")

    with httpx.Client(
        verify=True,
        follow_redirects=True,
        max_redirects=3,
        timeout=_HTTP_TIMEOUT,
        headers=_HTTP_HEADERS,
    ) as client:
        cookie_json = json.dumps(
            {
                "origen": {"code": origin_code, "name": origin_name},
                "destino": {"code": dest_code, "name": dest_name},
                "pasajerosAdultos": 1,
                "pasajerosNinos": 0,
                "pasajerosSpChild": 0,
            },
            ensure_ascii=False,
        )
        client.cookies.set("Search", quote(cookie_json, safe=""), domain=".renfe.com", path="/")

        client.post(
            _SEARCH_URL,
            data={
                "tipoBusqueda": "autocomplete",
                "cdgoOrigen": origin_code,
                "cdgoDestino": dest_code,
                "desOrigen": origin_name,
                "desDestino": dest_name,
                "FechaIdaSel": date_str,
                "_fechaIdaVisual": date_str,
                "adultos_": "1",
                "ninos_": "0",
                "ninosMenores": "0",
                "Idioma": "es",
                "Pais": "ES",
                "currenLocation": "menuBusqueda",
                "vengoderenfecom": "SI",
                "idiomaBusqueda": "ES",
                "FechaVueltaSel": "",
                "_fechaVueltaVisual": "",
                "codPromocional": "",
                "plazaH": "false",
                "sinEnlace": "false",
                "asistencia": "false",
                "franjaHoraI": "",
                "franjaHoraV": "",
            },
        ).raise_for_status()

        client.post(
            _SYSTEM_ID_URL,
            content=dwr.build_generate_id_payload(next(batch_id), None),
        ).raise_for_status()

        r2 = client.post(
            _SYSTEM_ID_URL,
            content=dwr.build_generate_id_payload(next(batch_id), search_id),
        )
        r2.raise_for_status()

        token = _extract_dwr_token(r2.text)
        client.cookies.set("DWRSESSIONID", token, path="/vol", domain="venta.renfe.com")
        script_session_id = dwr.create_session_script_id(token)

        client.post(
            _UPDATE_SESSION_URL,
            content=dwr.build_update_session_payload(next(batch_id), search_id, script_session_id),
        ).raise_for_status()

        r4 = client.post(
            _TRAIN_LIST_URL,
            content=dwr.build_train_list_payload(
                next(batch_id), search_id, script_session_id, date_str
            ),
        )
        r4.raise_for_status()

        return _parse_trains_from_data(
            _extract_train_list(r4.text),
            origin_code,
            dest_code,
            departure_dt,
        )


def _parse_trains_from_data(
    data: dict,
    origin_code: str,
    dest_code: str,
    departure_dt: datetime,
) -> list[dict]:
    trains = []
    direction_list = data.get("listadoTrenes", [])
    if not direction_list:
        return trains

    for train_data in direction_list[0].get("listviajeViewEnlaceBean", []):
        try:
            price_str = train_data.get("tarifaMinima") or "0"
            price = float(str(price_str).replace(",", "."))

            dep_h, dep_m = map(int, train_data["horaSalida"].split(":"))
            arr_h, arr_m = map(int, train_data["horaLlegada"].split(":"))
            dep_dt = departure_dt.replace(hour=dep_h, minute=dep_m, second=0, microsecond=0)
            arr_dt = departure_dt.replace(hour=arr_h, minute=arr_m, second=0, microsecond=0)

            available = (
                not train_data.get("completo", True)
                and train_data.get("razonNoDisponible", "") in ("", "8")
                and train_data.get("tarifaMinima") is not None
                and not train_data.get("soloPlazaH", True)
            )
            if not available:
                continue

            trains.append(
                {
                    "operator": train_data.get("tipoTrenUno", "Renfe"),
                    "train_number": train_data.get("numeroTren") or None,
                    "origin_code": origin_code,
                    "destination_code": dest_code,
                    "departure_time": dep_dt,
                    "arrival_time": arr_dt,
                    "duration_minutes": int(train_data.get("duracionViajeTotalEnMinutos", 0)),
                    "price_eur": price if price > 0 else None,
                    "booking_url": "https://www.renfe.com/es/es/viajeros/billetes-y-ofertas/compra-tu-billete",
                }
            )
        except Exception:
            continue

    return trains


async def search_with_prices(
    origin_name: str,
    destination_name: str,
    date: str,  # YYYY-MM-DD
) -> list[TrainResult]:
    origin = find_station_code(origin_name)
    if origin is None:
        logger.warning("DWR scraper: origin station not found: %s", origin_name)
        return []

    destination = find_station_code(destination_name)
    if destination is None:
        logger.warning("DWR scraper: destination station not found: %s", destination_name)
        return []

    o_name, o_code = origin
    d_name, d_code = destination
    departure_dt = datetime.strptime(date, "%Y-%m-%d")

    loop = asyncio.get_event_loop()
    trains_data = await loop.run_in_executor(
        None,
        partial(_run_dwr_flow, o_name, o_code, d_name, d_code, departure_dt),
    )

    return [TrainResult(**t) for t in trains_data]
