"""Kardashev-I — Motor de diagnóstico rápido (día típico).

Cálculo LIGERO de un único día representativo (96 pasos de 15 min) para el panel
de "consulta rápida" siempre visible: expone GHI/DNI/DHI/POA y la potencia de un
solo panel en condiciones de cielo claro.

A diferencia de ``motor_2``/``motor_fisica_avanzada`` (que recorren todo el año,
~35 040 pasos), aquí solo se calcula un día → respuesta en decenas de
milisegundos, apta para reaccionar en vivo al mover los deslizadores de
inclinación y azimut.

Decisión de diseño: se usa una **turbidez de Linke fija** (por defecto 3.0) en
vez de ``lookup_linke_turbidity`` para evitar la carga del archivo H5 global en
cada arrastre del slider. La vista ANUAL sigue usando la turbidez real por sitio
(``motor_2``). ``motor_2.py`` permanece intocable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

# Día representativo por defecto: equinoccio de marzo (balance anual razonable).
DIA_TIPICO_DEFAULT = "2026-03-21"
TURBIDEZ_DEFAULT = 3.0
_BLOQUES_DIA = 96  # 24 h × 4 (15 min)


def dia_tipico(lat, lon, alt, tz, tilt, azimuth, area, eff,
               dia=DIA_TIPICO_DEFAULT, turbidity=TURBIDEZ_DEFAULT):
    """Calcula un día representativo de irradiancia y potencia de un panel.

    Parameters
    ----------
    lat, lon, alt : float
        Ubicación (grados, grados, metros sobre el nivel del mar).
    tz : str
        Zona horaria (idealmente ya resuelta a offset fijo Etc/GMT±X).
    tilt, azimuth : float
        Inclinación y azimut del panel (grados).
    area, eff : float
        Área de UN panel (m²) y eficiencia (0–1) para la potencia de muestra.
    dia : str
        Fecha del día representativo (``YYYY-MM-DD``).
    turbidity : float
        Turbidez de Linke fija (cielo claro). 3.0 ≈ atmósfera media.

    Returns
    -------
    DataFrame
        Índice 15-min (un día) con columnas: ``ghi``, ``dni``, ``dhi``,
        ``poa_global``, ``solar_elevation`` y ``potencia_panel_W``.
    """
    index = pd.date_range(start=f"{dia} 00:00", end=f"{dia} 23:45",
                          freq="15min", tz=tz)

    pressure = pvlib.atmosphere.alt2pres(alt)
    sol = pvlib.solarposition.get_solarposition(index, lat, lon, alt,
                                                 pressure=pressure)
    zenith = sol["apparent_zenith"].values
    sol_az = sol["azimuth"].values
    airmass_rel = pvlib.atmosphere.get_relative_airmass(zenith)
    airmass_abs = pvlib.atmosphere.get_absolute_airmass(airmass_rel, pressure)

    cs = pvlib.clearsky.ineichen(zenith, airmass_absolute=airmass_abs,
                                 linke_turbidity=turbidity, altitude=alt)
    irr = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt, surface_azimuth=azimuth,
        solar_zenith=zenith, solar_azimuth=sol_az,
        dni=cs["dni"], ghi=cs["ghi"], dhi=cs["dhi"],
    )

    out = pd.DataFrame(index=index)
    out["ghi"] = np.asarray(cs["ghi"])
    out["dni"] = np.asarray(cs["dni"])
    out["dhi"] = np.asarray(cs["dhi"])
    out["poa_global"] = np.asarray(irr["poa_global"])
    out["solar_elevation"] = 90.0 - zenith
    # Potencia de UN panel en cielo claro (W): POA × área × eficiencia.
    out["potencia_panel_W"] = out["poa_global"] * float(area) * float(eff)
    return out
