"""Kardashev-I — Generador de perfiles de demanda sintéticos.

Para el Modo Simple: en lugar de pedir un CSV de demanda, el usuario indica
un consumo diario (kWh/día) y aquí construimos una serie de 15 minutos para
todo 2026 con una forma de carga realista (residencial o PyME).

El resultado tiene exactamente el formato que consume `motor_financiero` y el
store de demanda de la app: índice 15-min tz-naive con columnas
``Energia_kWh`` y ``Energia_kVArh``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Factor de potencia supuesto para derivar la energía reactiva del perfil
# sintético (cos φ = 0.95 → tan φ ≈ 0.3287).
_FP_SUPUESTO = 0.95
_TAN_PHI = np.tan(np.arccos(_FP_SUPUESTO))

# Número de bloques de 15 min en un día.
_BLOQUES_DIA = 96


def _forma_residencial():
    """Pesos normalizados (suman 1) de un día residencial típico.

    Valle nocturno, repunte matutino (6–9 h), meseta baja al mediodía y pico
    vespertino marcado (18–22 h).
    """
    horas = np.arange(_BLOQUES_DIA) / 4.0  # 0.00, 0.25, … 23.75
    base = np.full(_BLOQUES_DIA, 0.30)
    # Picos gaussianos: (centro_h, ancho_h, amplitud)
    picos = [(7.5, 1.6, 0.9), (19.5, 2.2, 1.6)]
    perfil = base.copy()
    for centro, ancho, amp in picos:
        perfil += amp * np.exp(-0.5 * ((horas - centro) / ancho) ** 2)
    return perfil / perfil.sum()


def _forma_pyme():
    """Pesos normalizados de un día comercial/PyME típico.

    Arranque hacia las 8 h, meseta alta en horario laboral (9–18 h) y caída
    por la noche.
    """
    horas = np.arange(_BLOQUES_DIA) / 4.0
    perfil = np.full(_BLOQUES_DIA, 0.15)
    laboral = (horas >= 8) & (horas <= 18)
    perfil[laboral] += 1.0
    # Suavizar bordes de entrada/salida.
    perfil += 0.4 * np.exp(-0.5 * ((horas - 8) / 1.0) ** 2)
    perfil += 0.4 * np.exp(-0.5 * ((horas - 18) / 1.2) ** 2)
    return perfil / perfil.sum()


_FORMAS = {
    "residencial": _forma_residencial,
    "pyme": _forma_pyme,
}


def generar_perfil(kwh_dia, shape="residencial", year=2026):
    """Genera un perfil de demanda 15-min para todo el año.

    Parameters
    ----------
    kwh_dia : float
        Consumo objetivo por día (kWh). Se reparte según la forma de carga.
    shape : {"residencial", "pyme"}
        Forma del perfil diario.
    year : int
        Año del índice (debe coincidir con el de la generación solar, 2026).

    Returns
    -------
    DataFrame
        Índice 15-min tz-naive con columnas ``Energia_kWh`` y ``Energia_kVArh``.
    """
    if kwh_dia is None or kwh_dia <= 0:
        raise ValueError("El consumo diario (kWh/día) debe ser mayor que 0.")

    forma = _FORMAS.get(shape, _forma_residencial)()
    perfil_dia = forma * float(kwh_dia)  # kWh por bloque, suma = kwh_dia

    idx = pd.date_range(start=f"{year}-01-01 00:00",
                        end=f"{year}-12-31 23:45", freq="15min")
    n_dias = len(idx) // _BLOQUES_DIA
    energia = np.tile(perfil_dia, n_dias)
    # Cubrir cualquier remanente (años con bloques extra) recortando al índice.
    energia = np.resize(energia, len(idx))

    df = pd.DataFrame(index=idx)
    df["Energia_kWh"] = energia
    df["Energia_kVArh"] = energia * _TAN_PHI
    return df


def consumo_anual_kwh(df):
    """Consumo anual total (kWh) de un perfil generado."""
    return float(df["Energia_kWh"].sum())
