"""Kardashev-I — Especificaciones de baterías (vida útil por ciclos).

Define químicas de batería con sus parámetros estándar de industria para
estimar **ciclos equivalentes por año** y **vida útil** a partir del throughput
de descarga que reporta el motor financiero.

Los valores son DE REFERENCIA y editables (igual que ``tarifas_cfe``): cada
química lleva el valor puntual usado en el cálculo y un ``rango`` informativo que
la UI muestra en un globo de texto. Revísalos contra la hoja de datos del
fabricante del banco cotizado.

Campos por química:
 - ``ciclos_eol``      : ciclos hasta fin de vida (capacidad ~80 %).
 - ``dod``            : profundidad de descarga típica (fracción 0–1).
 - ``vida_calendario``: años de vida por calendario (tope independiente de ciclos).
 - ``round_trip``     : eficiencia de ida y vuelta (fracción 0–1).
"""
from __future__ import annotations

import math

# Fecha de referencia de los valores cargados. Actualizar con hojas de datos.
ACTUALIZADO = "Referencia 2024 · editable"

BATERIAS = {
    "lfp": {
        "nombre": "LiFePO4 (LFP)",
        "ciclos_eol": 5000,
        "dod": 0.90,
        "vida_calendario": 12,
        "round_trip": 0.90,
        "rango": "4 000–6 000 ciclos · DoD 80–90 % · 10–15 años · ~90 % round-trip",
    },
    "nmc": {
        "nombre": "NMC (Li-ion)",
        "ciclos_eol": 3000,
        "dod": 0.85,
        "vida_calendario": 10,
        "round_trip": 0.92,
        "rango": "2 000–3 500 ciclos · DoD 80–90 % · 8–12 años · ~92 % round-trip",
    },
    "agm": {
        "nombre": "Plomo-ácido AGM",
        "ciclos_eol": 800,
        "dod": 0.50,
        "vida_calendario": 5,
        "round_trip": 0.80,
        "rango": "500–1 200 ciclos · DoD ~50 % · 3–6 años · ~80 % round-trip",
    },
}

BATERIA_DEFAULT = "lfp"


def opciones_dropdown():
    """Opciones {label, value} para un dcc.Dropdown de tipo de batería."""
    return [{"label": b["nombre"], "value": bid} for bid, b in BATERIAS.items()]


def spec(bateria_id):
    """Devuelve el dict de la química (o la default si no existe)."""
    return BATERIAS.get(bateria_id, BATERIAS[BATERIA_DEFAULT])


def tooltip_text():
    """Texto para el globo de información: valores estándar por química."""
    lineas = ["Valores estándar de industria (referencia, editables):"]
    for b in BATERIAS.values():
        lineas.append(f"• {b['nombre']}: {b['rango']}")
    return "\n".join(lineas)


def estimar_vida(bateria_id, capacidad_kwh, descarga_anual_kwh, horizonte_anios):
    """Estima ciclos/año, vida útil y reemplazos para una química y throughput.

    Parameters
    ----------
    bateria_id : str
        Clave en :data:`BATERIAS`.
    capacidad_kwh : float
        Capacidad nominal del banco (kWh).
    descarga_anual_kwh : float
        Energía descargada del banco en un año (throughput, del motor).
    horizonte_anios : int
        Horizonte del análisis financiero.

    Returns
    -------
    dict con ``ciclos_por_anio``, ``vida_anios`` (limitada por ciclos o
    calendario), ``limita`` ("ciclos" | "calendario") y ``reemplazos``.
    """
    b = spec(bateria_id)
    capacidad_util = max(1e-9, float(capacidad_kwh) * b["dod"])
    ciclos_por_anio = float(descarga_anual_kwh) / capacidad_util

    if ciclos_por_anio > 0:
        vida_ciclos = b["ciclos_eol"] / ciclos_por_anio
    else:
        vida_ciclos = float("inf")
    vida_calendario = float(b["vida_calendario"])

    if vida_ciclos < vida_calendario:
        vida_anios, limita = vida_ciclos, "ciclos"
    else:
        vida_anios, limita = vida_calendario, "calendario"

    if vida_anios > 0 and not math.isinf(vida_anios):
        reemplazos = max(0, math.ceil(horizonte_anios / vida_anios) - 1)
    else:
        reemplazos = 0

    return {
        "nombre": b["nombre"],
        "ciclos_por_anio": ciclos_por_anio,
        "vida_anios": vida_anios,
        "limita": limita,
        "reemplazos": reemplazos,
        "dod": b["dod"],
        "round_trip": b["round_trip"],
    }
