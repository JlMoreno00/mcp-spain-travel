from __future__ import annotations

import random
import string
import urllib.parse
from datetime import datetime
from typing import Iterator, Optional


def get_batch_id_generator() -> Iterator[int]:
    num = 0
    while True:
        yield num
        num += 1


def create_search_id() -> str:
    return "_" + "".join(random.choices(string.ascii_letters + string.digits, k=4))


def tokenify(number: int) -> str:
    tokenbuf: list[str] = []
    charmap = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ*$"
    remainder = number
    while remainder > 0:
        tokenbuf.append(charmap[remainder & 0x3F])
        remainder //= 64
    return "".join(tokenbuf)


def create_session_script_id(dwr_token: str) -> str:
    date_token = tokenify(int(datetime.now().timestamp() * 1000))
    random_token = tokenify(int(random.random() * 1e16))
    return f"{dwr_token}/{date_token}-{random_token}"


def build_generate_id_payload(batch_id: int, search_id: Optional[str] = None) -> str:
    if search_id is None:
        page = "page=%2Fvol%2FbuscarTrenEnlaces.do\n"
    else:
        page = f"page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D{search_id}\n"

    return (
        "callCount=1\n"
        "c0-scriptName=__System\n"
        "c0-methodName=generateId\n"
        "c0-id=0\n"
        f"batchId={batch_id}\n"
        "instanceId=0\n"
        f"{page}"
        "scriptSessionId=\n"
        "windowName=\n"
    )


def build_update_session_payload(
    batch_id: int,
    search_id: str,
    script_session_id: str,
) -> str:
    return (
        "callCount=1\n"
        "windowName=\n"
        "c0-scriptName=buyEnlacesManager\n"
        "c0-methodName=actualizaObjetosSesion\n"
        "c0-id=0\n"
        f"c0-e1=string:{search_id}\n"
        "c0-e2=string:\n"
        "c0-param0=array:[reference:c0-e1,reference:c0-e2]\n"
        f"batchId={batch_id}\n"
        "instanceId=0\n"
        f"page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D{search_id}\n"
        f"scriptSessionId={script_session_id}\n"
    )


def build_train_list_payload(
    batch_id: int,
    search_id: str,
    script_session_id: str,
    departure_date: str,  # DD/MM/YYYY
    return_date: Optional[str] = None,  # DD/MM/YYYY or None for one-way
) -> str:
    return_date_str = "" if return_date is None else return_date
    trayecto = "I" if return_date is None else "IV"  # I=Ida (one-way), IV=Ida-Vuelta (round-trip)

    return (
        "callCount=1\n"
        "windowName=\n"
        "c0-scriptName=trainEnlacesManager\n"
        "c0-methodName=getTrainsList\n"
        "c0-id=0\n"
        "c0-e1=string:false\n"
        "c0-e2=string:false\n"
        "c0-e3=string:false\n"
        "c0-e4=string:\n"
        "c0-e5=string:\n"
        "c0-e6=string:\n"
        "c0-e7=string:\n"
        f"c0-e8=string:{urllib.parse.quote_plus(departure_date)}\n"
        f"c0-e9=string:{urllib.parse.quote_plus(return_date_str)}\n"
        "c0-e10=string:1\n"
        "c0-e11=string:0\n"
        "c0-e12=string:0\n"
        f"c0-e13=string:{trayecto}\n"
        "c0-e14=string:\n"
        "c0-param0=Object_Object:{atendo:reference:c0-e1, sinEnlace:reference:c0-e2, "
        "plazaH:reference:c0-e3, tipoFranjaI:reference:c0-e4, tipoFranjaV:reference:c0-e5, "
        "horaFranjaIda:reference:c0-e6, horaFranjaVuelta:reference:c0-e7, fechaSalida:reference"
        ":c0-e8, fechaVuelta:reference:c0-e9, adultos:reference:c0-e10, ninos:reference:c0-e11,"
        " ninosMenores:reference:c0-e12, trayecto:reference:c0-e13, idaVuelta:reference:c0-e14}"
        "\n"
        f"batchId={batch_id}\n"
        "instanceId=0\n"
        f"page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D{search_id}\n"
        f"scriptSessionId={script_session_id}\n"
    )
