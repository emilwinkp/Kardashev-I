"""Kardashev-I — Motor TMY (datos meteorológicos reales, PVGIS).

Fuente de irradiancia ALTERNATIVA al cielo claro de ``motor_2``. Descarga un Año
Meteorológico Típico (TMY) de PVGIS — gratis, sin API key, cobertura global
incluido México — que SÍ incorpora nubosidad, y lo convierte a generación
fotovoltaica con la misma física de transposición + conversión que el motor base.

``motor_2.py`` permanece intocable: este módulo es paralelo y se selecciona desde
la UI con un toggle "Cielo claro / TMY real".

Características de robustez:
 - **Caché en memoria** por coordenada (redondeada) para no repetir la descarga.
 - **Fallback explícito**: si la red/PVGIS falla, lanza ``TMYUnavailable`` para
   que el llamador (app) degrade con gracia al modelo de cielo claro.
 - Resolución horaria de PVGIS **resampleada a 15 min** para encajar con el resto
   del modelo (índice 15-min de todo el año).

El TMY de PVGIS también trae temperatura ambiente real (``temp_air``), que se
expone para alimentar el modelo térmico (NOCT) en el futuro.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib
from pvlib import iotools

_BLOQUE_H = 0.25  # 15 min en horas

# Caché en memoria: {(lat_r, lon_r): DataFrame meteorológico horario UTC}
_CACHE_TMY: dict[tuple[float, float], pd.DataFrame] = {}


class TMYUnavailable(Exception):
    """Se lanza cuando no se pudo obtener el TMY (sin red, timeout, error API)."""


def _fetch_tmy(lat, lon, timeout=20):
    """Descarga (o recupera de caché) el TMY horario de PVGIS en UTC.

    Devuelve un DataFrame con al menos ``ghi``, ``dni``, ``dhi`` y ``temp_air``,
    índice horario tz-aware (UTC), 8760 filas. Lanza ``TMYUnavailable`` si falla.
    """
    key = (round(float(lat), 3), round(float(lon), 3))
    if key in _CACHE_TMY:
        return _CACHE_TMY[key]
    try:
        res = iotools.get_pvgis_tmy(lat, lon, map_variables=True, timeout=timeout)
        data = res[0]  # pvlib 0.15: (data, metadata)
    except Exception as exc:  # red, timeout, parseo, cobertura…
        raise TMYUnavailable(f"PVGIS no disponible: {exc}") from exc
    if data is None or data.empty or not {"ghi", "dni", "dhi"} <= set(data.columns):
        raise TMYUnavailable("PVGIS devolvió datos incompletos.")
    if data.index.tz is None:
        data = data.tz_localize("UTC")
    _CACHE_TMY[key] = data
    return data


def preparar_tmy(lat, lon, alt, year=2026, timeout=20):
    """Precalcula lo necesario para barrer ángulos sobre el TMY (optimización).

    Devuelve un dict con la geometría solar horaria (zenit/azimut) y la
    irradiancia real del TMY (dni/ghi/dhi), todo alineado, para que la búsqueda
    de tilt/azimut óptimos solo tenga que repetir la **transposición** (barata)
    por cada candidato, sin volver a descargar ni recomputar la posición solar.

    Reutiliza la caché del TMY. Lanza ``TMYUnavailable`` si no hay datos.
    """
    weather = _fetch_tmy(lat, lon, timeout=timeout)
    n = len(weather)
    idx_utc = pd.date_range(start=f"{year}-01-01 00:00", periods=n,
                            freq="h", tz="UTC")
    pressure = pvlib.atmosphere.alt2pres(alt)
    sol = pvlib.solarposition.get_solarposition(idx_utc, lat, lon, alt,
                                                pressure=pressure)
    return {
        "zenith": sol["apparent_zenith"].values,
        "sol_az": sol["azimuth"].values,
        "dni": weather["dni"].values,
        "ghi": weather["ghi"].values,
        "dhi": weather["dhi"].values,
    }


def poa_anual(prep, tilt, azimuth):
    """Suma anual de POA (W/m²) para un tilt/azimut, usando datos de ``preparar_tmy``.

    Proxy de energía para optimizar la orientación (área/η/PR son constantes).
    """
    irr = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt, surface_azimuth=azimuth,
        solar_zenith=prep["zenith"], solar_azimuth=prep["sol_az"],
        dni=prep["dni"], ghi=prep["ghi"], dhi=prep["dhi"],
    )
    return float(np.nan_to_num(irr["poa_global"]).sum())


def calculate_tmy(lat, lon, alt, tz, tilt, azimuth, area, efficiency, PR,
                  year=2026, timeout=20):
    """Genera la producción FV usando datos meteorológicos reales (TMY/PVGIS).

    La firma y el contrato de salida imitan a ``motor_2.calculate`` para que la
    app pueda intercambiar la fuente sin cambiar el resto del flujo.

    Returns
    -------
    DataFrame
        Índice 15-min tz-aware (``tz``) para ``year`` con columnas:
        ``ghi``, ``dni``, ``dhi``, ``poa_global``, ``solar_elevation``,
        ``temp_air``, ``potencia_generada`` (W) y ``energia_generada_kWh``.

    Raises
    ------
    TMYUnavailable
        Si no se pudo obtener el TMY (el llamador debe hacer fallback).
    """
    weather = _fetch_tmy(lat, lon, timeout=timeout)

    # ── Remapear el año del TMY al año objetivo manteniendo los instantes UTC ──
    # PVGIS entrega 8760 horas de un único año (no bisiesto); year objetivo (2026)
    # tampoco es bisiesto, así que el remapeo hora a hora es exacto.
    n = len(weather)
    idx_utc = pd.date_range(start=f"{year}-01-01 00:00", periods=n,
                            freq="h", tz="UTC")
    w = weather.copy()
    w.index = idx_utc

    # ── Geometría solar en los instantes UTC reales ──
    pressure = pvlib.atmosphere.alt2pres(alt)
    sol = pvlib.solarposition.get_solarposition(w.index, lat, lon, alt,
                                                 pressure=pressure)
    zenith = sol["apparent_zenith"].values
    sol_az = sol["azimuth"].values

    # ── Transposición al plano del panel con la irradiancia REAL del TMY ──
    irr = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt, surface_azimuth=azimuth,
        solar_zenith=zenith, solar_azimuth=sol_az,
        dni=w["dni"].values, ghi=w["ghi"].values, dhi=w["dhi"].values,
    )

    df_h = pd.DataFrame(index=w.index)
    df_h["ghi"] = w["ghi"].values
    df_h["dni"] = w["dni"].values
    df_h["dhi"] = w["dhi"].values
    df_h["poa_global"] = np.nan_to_num(irr["poa_global"])
    df_h["solar_elevation"] = 90.0 - zenith
    df_h["temp_air"] = (w["temp_air"].values if "temp_air" in w.columns
                        else np.nan)
    df_h["potencia_generada"] = (df_h["poa_global"] * float(area)
                                 * float(efficiency) * float(PR))

    # ── Pasar a la zona local y normalizar al calendario del año objetivo ──
    df_h = df_h.tz_convert(tz)
    df_h.index = pd.DatetimeIndex(
        [t.replace(year=year) for t in df_h.index], tz=df_h.index.tz)
    df_h = df_h[~df_h.index.duplicated(keep="first")].sort_index()

    # Rejilla horaria local limpia del año completo + interpolación de huecos.
    full_h = pd.date_range(start=f"{year}-01-01 00:00",
                           end=f"{year}-12-31 23:00", freq="h", tz=tz)
    df_h = df_h.reindex(full_h).interpolate(limit_direction="both")

    # ── Resamplear a 15 min (interpolación) y derivar la energía por bloque ──
    full_15 = pd.date_range(start=f"{year}-01-01 00:00",
                            end=f"{year}-12-31 23:45", freq="15min", tz=tz)
    df = df_h.reindex(df_h.index.union(full_15)).interpolate(
        limit_direction="both").reindex(full_15)
    df["potencia_generada"] = df["potencia_generada"].clip(lower=0)
    df["energia_generada_kWh"] = df["potencia_generada"] * _BLOQUE_H / 1000.0
    return df
