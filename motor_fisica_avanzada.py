"""Kardashev-I — Motor de física avanzada (Modo Avanzado).

Envoltorio sobre ``motor_2.calculate`` (que permanece INTOCABLE). Aporta el
realismo físico que el motor base no modela:

 - Descomposición de irradiancia expuesta: DNI, DHI, POA directa/difusa y
   elevación solar (el motor base las calcula internamente pero las descarta).
 - Temperatura de celda (NOCT) y corrección de eficiencia por temperatura.
 - Pérdidas por suciedad (soiling), cableado, inversor y degradación anual.
 - IAM (modificador por ángulo de incidencia) opcional.
 - Diccionario de atribución de pérdidas para el gráfico de cascada.

El cálculo de generación base proviene de ``motor_2`` (fuente de verdad); aquí
recomputamos la geometría/cielo claro solo para *exponer* componentes y derivar
la temperatura, y aplicamos los factores de pérdida sobre la POA del motor base.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from motor_2 import calculate as _calculate_base

# Valores por defecto razonables para módulos c-Si modernos.
GAMMA_PMAX_DEFAULT = -0.0040   # 1/°C  (≈ -0.40 %/°C)
NOCT_DEFAULT = 45.0            # °C
TAMB_DEFAULT = 25.0           # °C (anual, si no se dan 12 valores)
SOILING_DEFAULT = 0.03        # 3 %
WIRING_LOSS_DEFAULT = 0.02    # 2 % (DC+AC)
ETA_INV_DEFAULT = 0.97        # eficiencia del inversor
DEGRADACION_ANUAL_DEFAULT = 0.005  # 0.5 %/año

_BLOQUE_H = 0.25  # 15 min en horas


def _serie_tamb(tamb, index):
    """Construye una serie de Tamb por timestep desde un escalar o 12 valores."""
    if tamb is None:
        tamb = TAMB_DEFAULT
    if np.isscalar(tamb):
        return np.full(len(index), float(tamb))
    tamb = list(tamb)
    if len(tamb) == 12:
        meses = index.month.values
        return np.array([float(tamb[m - 1]) for m in meses])
    if len(tamb) == 1:
        return np.full(len(index), float(tamb[0]))
    raise ValueError("Tamb debe ser un escalar o una lista de 12 valores mensuales.")


def _componentes_irradiancia(lat, lon, alt, tz, tilt, azimuth, index):
    """Recalcula cielo claro + transposición y devuelve componentes + AOI + elev."""
    pressure = pvlib.atmosphere.alt2pres(alt)
    turbidity = pvlib.clearsky.lookup_linke_turbidity(index, lat, lon)
    sol = pvlib.solarposition.get_solarposition(index, lat, lon, alt, pressure=pressure)
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
    aoi = pvlib.irradiance.aoi(tilt, azimuth, zenith, sol_az)
    elev = 90.0 - zenith
    out = pd.DataFrame(index=index)
    out["dni"] = np.asarray(cs["dni"])
    out["dhi"] = np.asarray(cs["dhi"])
    out["poa_direct"] = np.asarray(irr["poa_direct"])
    out["poa_diffuse"] = np.asarray(irr["poa_diffuse"])
    out["solar_elevation"] = elev
    out["aoi"] = aoi
    return out


def calculate_advanced(lat, lon, alt, tz, tilt, azimuth, area, efficiency, PR,
                       tamb=TAMB_DEFAULT, gamma_pmax=GAMMA_PMAX_DEFAULT,
                       noct=NOCT_DEFAULT, soiling=SOILING_DEFAULT,
                       wiring_loss=WIRING_LOSS_DEFAULT, eta_inv=ETA_INV_DEFAULT,
                       degradation=DEGRADACION_ANUAL_DEFAULT, year_index=0,
                       use_iam=False):
    """Calcula generación con realismo físico y atribución de pérdidas.

    Devuelve ``(df, perdidas)`` donde:
      - ``df`` tiene índice 15-min tz-aware con columnas:
        ghi, poa_global, dni, dhi, poa_direct, poa_diffuse, solar_elevation,
        tcell, potencia_generada (W, neta) y energia_generada_kWh (neta).
      - ``perdidas`` es un dict con la cascada anual en kWh:
        nominal, temperatura, suciedad, iam, cableado, inversor, otras_pr,
        degradacion y neto. Cada entrada (salvo nominal/neto) es la energía
        PERDIDA en esa etapa (valor positivo).
    """
    # 1) Generación base (fuente de verdad, motor intocable).
    df = _calculate_base(lat, lon, alt, tz, tilt, azimuth, area, efficiency, PR)
    index = df.index
    poa = df["poa_global"].values

    # 2) Componentes de irradiancia + geometría (para exponer y para Tcell/IAM).
    comp = _componentes_irradiancia(lat, lon, alt, tz, tilt, azimuth, index)
    for c in ["dni", "dhi", "poa_direct", "poa_diffuse", "solar_elevation"]:
        df[c] = comp[c].values

    # 3) Temperatura de celda (modelo NOCT) y factor de eficiencia por temp.
    tamb_arr = _serie_tamb(tamb, index)
    tcell = tamb_arr + (noct - 20.0) * (poa / 800.0)
    df["tcell"] = tcell
    factor_temp = 1.0 + gamma_pmax * (tcell - 25.0)

    # 4) Cascada de energía (kWh por bloque) aplicada por timestep.
    a_kwh = area * efficiency * _BLOQUE_H / 1000.0  # POA[W/m²] → kWh nominal/bloque
    e_nominal = poa * a_kwh
    e_temp = e_nominal * factor_temp
    e_soil = e_temp * (1.0 - soiling)
    if use_iam:
        iam = pvlib.iam.martin_ruiz(comp["aoi"].values)
        iam = np.nan_to_num(iam, nan=0.0)
        e_iam = e_soil * iam
    else:
        e_iam = e_soil
    e_wire = e_iam * (1.0 - wiring_loss)
    e_inv = e_wire * eta_inv
    # En Modo Avanzado las pérdidas se modelan EXPLÍCITAMENTE (temperatura,
    # suciedad, IAM, cableado, inversor y degradación). NO se aplica el PR global
    # del motor base: hacerlo descontaría dos veces esas mismas pérdidas (el PR
    # ya las agrupa). El parámetro PR se mantiene en la firma por compatibilidad,
    # pero no interviene en la cascada avanzada.
    factor_degr = (1.0 - degradation) ** max(0, int(year_index))
    e_net = e_inv * factor_degr

    df["energia_generada_kWh"] = e_net
    df["potencia_generada"] = e_net / _BLOQUE_H * 1000.0  # kWh/bloque → W

    # 5) Atribución de pérdidas anuales (kWh) para la cascada.
    s = lambda arr: float(np.nansum(arr))
    perdidas = {
        "nominal": s(e_nominal),
        "temperatura": s(e_nominal) - s(e_temp),
        "suciedad": s(e_temp) - s(e_soil),
        "iam": s(e_soil) - s(e_iam),
        "cableado": s(e_iam) - s(e_wire),
        "inversor": s(e_wire) - s(e_inv),
        "degradacion": s(e_inv) - s(e_net),
        "neto": s(e_net),
    }
    return df, perdidas


def apply_advanced_losses(df_tmy, area, efficiency,
                          gamma_pmax=GAMMA_PMAX_DEFAULT,
                          noct=NOCT_DEFAULT,
                          soiling=SOILING_DEFAULT,
                          wiring_loss=WIRING_LOSS_DEFAULT,
                          eta_inv=ETA_INV_DEFAULT,
                          degradation=DEGRADACION_ANUAL_DEFAULT,
                          year_index=0,
                          use_iam=False):
    """Aplica la cascada de pérdidas avanzada sobre un DataFrame TMY existente.

    Equivale a calculate_advanced pero acepta el DataFrame ya calculado por
    calculate_tmy (con poa_global y temp_air reales) en lugar de recomputar
    el cielo claro. Usa temp_air del TMY para el modelo NOCT, lo que es más
    realista que un escalar fijo.

    Returns
    -------
    (df, perdidas) con el mismo formato que calculate_advanced.
    """
    df = df_tmy.copy()
    poa = df["poa_global"].values
    index = df.index

    # Temperatura ambiente: usar la real del TMY cuando está disponible.
    if "temp_air" in df.columns and not df["temp_air"].isna().all():
        tamb_arr = df["temp_air"].fillna(TAMB_DEFAULT).values
    else:
        tamb_arr = np.full(len(index), TAMB_DEFAULT)

    # Temperatura de celda (modelo NOCT) y factor de eficiencia por temp.
    tcell = tamb_arr + (noct - 20.0) * (poa / 800.0)
    df["tcell"] = tcell
    factor_temp = 1.0 + gamma_pmax * (tcell - 25.0)

    # Cascada de energía (kWh por bloque).
    a_kwh = area * efficiency * _BLOQUE_H / 1000.0
    e_nominal = poa * a_kwh
    e_temp = e_nominal * factor_temp
    e_soil = e_temp * (1.0 - soiling)
    # IAM requiere AOI que no está en el DataFrame TMY; se omite (cero pérdida).
    e_iam = e_soil
    e_wire = e_iam * (1.0 - wiring_loss)
    e_inv = e_wire * eta_inv
    factor_degr = (1.0 - degradation) ** max(0, int(year_index))
    e_net = e_inv * factor_degr

    df["energia_generada_kWh"] = e_net
    df["potencia_generada"] = e_net / _BLOQUE_H * 1000.0

    s = lambda arr: float(np.nansum(arr))
    perdidas = {
        "nominal": s(e_nominal),
        "temperatura": s(e_nominal) - s(e_temp),
        "suciedad": s(e_temp) - s(e_soil),
        "iam": 0.0,  # no computable sin AOI en TMY
        "cableado": s(e_iam) - s(e_wire),
        "inversor": s(e_wire) - s(e_inv),
        "degradacion": s(e_inv) - s(e_net),
        "neto": s(e_net),
    }
    return df, perdidas
