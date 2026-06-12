"""Kardashev-I — Utilidades geográficas.

`fetch_altitude(lat, lon)` consulta la altitud (msnm) en la API pública
Open-Elevation. Es una dependencia de red opcional: si la llamada falla
(sin internet, timeout, respuesta inesperada) devuelve ``None`` y el llamador
conserva el valor previo del campo de altitud.
"""
from __future__ import annotations

from functools import lru_cache

import requests

_OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
# Timeout corto: la API pública es lenta/intermitente y no debe trabar la UI.
# El campo de altitud es editable a mano y solo afecta la física avanzada.
_TIMEOUT_S = 2.5


def fetch_altitude(lat, lon, timeout=_TIMEOUT_S):
    """Devuelve la altitud en metros para (lat, lon) o ``None`` si falla.

    Nunca lanza excepción: cualquier error de red o de parseo se traduce en
    ``None`` para que la UI degrade con gracia (el campo de altitud queda
    editable manualmente). El resultado se cachea por coordenada redondeada
    para no repetir la llamada de red al volver a un punto cercano.
    """
    if lat is None or lon is None:
        return None
    return _fetch_altitude_cached(round(float(lat), 3), round(float(lon), 3),
                                  timeout)


@lru_cache(maxsize=512)
def _fetch_altitude_cached(lat, lon, timeout):
    try:
        resp = requests.get(
            _OPEN_ELEVATION_URL,
            params={"locations": f"{float(lat)},{float(lon)}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        elev = data["results"][0]["elevation"]
        if elev is None:
            return None
        return round(float(elev))
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None
