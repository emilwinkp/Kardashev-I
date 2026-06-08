"""Kardashev-I — Tarifas CFE (estimador ligero para Modo Simple).

Define las estructuras tarifarias domésticas/comerciales de CFE y un estimador
de recibo mensual *solo de energía* a partir de un perfil de demanda de 15 min.

Alcance (por decisión de diseño):
 - DAC  : tarifa plana (MXN/kWh).
 - 1F   : doméstica por bloques mensuales (básico / intermedio / excedente).
 - HM   : media tensión horaria (Base / Intermedio / Punta).
 - GDMTH: se delega al motor financiero completo (batería + apagones + ROI).

Los precios son DE REFERENCIA y editables: cada tarifa lleva una fecha
``actualizado`` que la UI debe mostrar para recordar revisarlos contra las
tablas vigentes de CFE.

Periodos horarios (Base/Intermedio/Punta) se reutilizan de
``motor_financiero.asignar_tarifa_gdmth`` para no duplicar la lógica.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from motor_financiero import asignar_tarifa_gdmth

# Fecha de referencia de los precios cargados. Actualizar con las tablas CFE.
ACTUALIZADO = "Referencia 2024 · editable"

# ── Definición de tarifas ───────────────────────────────────────────────────
# tipo:
#   "flat"   → precio_kwh
#   "tiered" → bloques [(limite_kwh_mensual | None, precio), ...] acumulativos
#   "tou"    → precios {Base, Intermedio, Punta}
#   "gdmth"  → delegado al motor financiero
TARIFAS = {
    "DAC": {
        "nombre": "DAC — Doméstica de Alto Consumo",
        "tipo": "flat",
        "precio_kwh": 6.50,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Tarifa residencial sin subsidio que aplica al superar el límite "
            "de alto consumo de tu región. Precio plano por kWh, sin horarios."
        ),
    },
    "1F": {
        "nombre": "1F — Doméstica (bloques)",
        "tipo": "tiered",
        # (límite superior del bloque en kWh/mes, precio MXN/kWh)
        "bloques": [(150, 1.052), (300, 1.274), (None, 3.738)],
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Tarifa doméstica subsidiada por bloques mensuales: básico, "
            "intermedio y excedente. El precio sube conforme consumes más."
        ),
    },
    "HM": {
        "nombre": "HM — Horaria Media Tensión",
        "tipo": "tou",
        "precios": {"Base": 1.10, "Intermedio": 1.50, "Punta": 3.20},
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Media tensión con precio por horario: base (madrugada), "
            "intermedio (día) y punta (tarde-noche), más caro en punta."
        ),
    },
    "GDMTH": {
        "nombre": "GDMTH — Gran Demanda MT Horaria",
        "tipo": "gdmth",
        "delegado": True,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Gran demanda en media tensión con horarios y cargo por demanda "
            "(kW). Usa el análisis financiero completo con batería y apagones."
        ),
    },
}

_MESES_ES_SHORT = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                   "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _costo_bloques(kwh_mes, bloques):
    """Costo de ``kwh_mes`` aplicando bloques acumulativos."""
    restante = kwh_mes
    costo = 0.0
    limite_previo = 0.0
    for limite, precio in bloques:
        if limite is None:
            costo += restante * precio
            restante = 0.0
            break
        ancho = limite - limite_previo
        en_bloque = min(restante, ancho)
        costo += en_bloque * precio
        restante -= en_bloque
        limite_previo = limite
        if restante <= 0:
            break
    return costo


def estimar_recibo(perfil_15min, tarifa_id):
    """Estima el recibo mensual *de energía* para un perfil de demanda.

    Parameters
    ----------
    perfil_15min : DataFrame
        Índice 15-min tz-naive con columna ``Energia_kWh``.
    tarifa_id : str
        Clave en :data:`TARIFAS` (DAC / 1F / HM). Para GDMTH usar el motor
        financiero completo.

    Returns
    -------
    dict con ``df_mensual`` (DataFrame Mes/kWh/Costo), ``total_anual`` (MXN)
    y ``promedio_mensual`` (MXN).
    """
    if tarifa_id not in TARIFAS:
        raise ValueError(f"Tarifa desconocida: {tarifa_id}")
    tarifa = TARIFAS[tarifa_id]
    if tarifa["tipo"] == "gdmth":
        raise ValueError("GDMTH se evalúa con el motor financiero, no aquí.")

    df = perfil_15min.copy()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    filas = []
    if tarifa["tipo"] == "tou":
        periodos = df.index.map(asignar_tarifa_gdmth)
        df = df.assign(_periodo=periodos)
        for mes, dmes in df.groupby(df.index.month):
            costo = 0.0
            for periodo, precio in tarifa["precios"].items():
                kwh_p = dmes[dmes["_periodo"] == periodo]["Energia_kWh"].sum()
                costo += kwh_p * precio
            kwh_mes = dmes["Energia_kWh"].sum()
            filas.append({"Mes": mes, "kWh": kwh_mes, "Costo": costo})
    else:
        for mes, dmes in df.groupby(df.index.month):
            kwh_mes = dmes["Energia_kWh"].sum()
            if tarifa["tipo"] == "flat":
                costo = kwh_mes * tarifa["precio_kwh"]
            else:  # tiered
                costo = _costo_bloques(kwh_mes, tarifa["bloques"])
            filas.append({"Mes": mes, "kWh": kwh_mes, "Costo": costo})

    df_mensual = pd.DataFrame(filas)
    df_mensual["MesNombre"] = df_mensual["Mes"].map(
        lambda m: _MESES_ES_SHORT[m - 1])
    total = float(df_mensual["Costo"].sum())
    return {
        "df_mensual": df_mensual,
        "total_anual": total,
        "promedio_mensual": total / max(1, len(df_mensual)),
    }


def rate_efectiva(tarifa_id):
    """Precio MXN/kWh aproximado de una tarifa, para invertir recibo→kWh.

    Para bloques usa un consumo típico de 250 kWh/mes; para horarios mezcla
    los periodos con pesos representativos de un perfil residencial.
    """
    tarifa = TARIFAS[tarifa_id]
    if tarifa["tipo"] == "flat":
        return tarifa["precio_kwh"]
    if tarifa["tipo"] == "tiered":
        kwh_ref = 250.0
        return _costo_bloques(kwh_ref, tarifa["bloques"]) / kwh_ref
    if tarifa["tipo"] == "tou":
        # Pesos representativos residenciales: base 0.25, intermedio 0.55, punta 0.20.
        p = tarifa["precios"]
        return 0.25 * p["Base"] + 0.55 * p["Intermedio"] + 0.20 * p["Punta"]
    # GDMTH: aproximación con precio intermedio.
    return 1.50


def kwh_dia_desde_recibo(recibo_mensual_mxn, tarifa_id):
    """Estima el consumo diario (kWh/día) a partir de un recibo mensual (MXN)."""
    if recibo_mensual_mxn is None or recibo_mensual_mxn <= 0:
        raise ValueError("El recibo mensual debe ser mayor que 0.")
    rate = rate_efectiva(tarifa_id)
    kwh_mes = float(recibo_mensual_mxn) / rate
    return kwh_mes / 30.4


def opciones_dropdown():
    """Lista de opciones {label, value} para un dcc.Dropdown de tarifas."""
    return [{"label": t["nombre"], "value": tid} for tid, t in TARIFAS.items()]
