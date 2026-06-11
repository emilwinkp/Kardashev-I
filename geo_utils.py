"""Kardashev-I — Utilidades geográficas.

`fetch_altitude(lat, lon)` consulta la altitud (msnm) en la API pública
Open-Elevation. Es una dependencia de red opcional: si la llamada falla
(sin internet, timeout, respuesta inesperada) devuelve ``None`` y el llamador
conserva el valor previo del campo de altitud.
"""
from __future__ import annotations

import requests

_OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
_TIMEOUT_S = 6


def fetch_altitude(lat, lon, timeout=_TIMEOUT_S):
    """Devuelve la altitud en metros para (lat, lon) o ``None`` si falla.

    Nunca lanza excepción: cualquier error de red o de parseo se traduce en
    ``None`` para que la UI degrade con gracia (el campo de altitud queda
    editable manualmente).
    """
    if lat is None or lon is None:
        return None
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
