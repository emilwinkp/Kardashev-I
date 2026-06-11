"""Kardashev-I — Tarifas CFE (estimador ligero para Modo Simple).

Define las estructuras tarifarias domésticas/comerciales de CFE y un estimador
de recibo mensual *solo de energía* a partir de un perfil de demanda de 15 min.

Familias soportadas:
 - **Doméstica subsidiada** (1, 1A, 1B, 1C, 1D, 1E, 1F): bloques mensuales
   (básico / intermedio / [intermedio alto] / excedente), **sin horarios**.
   Las clases 1A–1F distinguen **temporada de verano** con límites de bloque
   más altos según la temperatura media de la región. La clase 1 (ordinaria,
   templada) no tiene temporada. Todas llevan el cargo fijo obligatorio 2026.
 - **DAC**: doméstica de alto consumo, precio plano (sin subsidio) + cargo fijo.
 - **GDMTO**: gran demanda media tensión *ordinaria* (< 100 kW): cargo de
   energía plano (sin horarios) + cargo fijo de suministro.
 - **HM**: media tensión horaria (Base / Intermedio / Punta), estimador ligero.
 - **GDMTH**: gran demanda MT *horaria* (≥ 100 kW); se delega al motor
   financiero completo (batería + apagones + ROI).

Los precios y los límites son DE REFERENCIA (CFE jun-2026, análisis de tarifas)
y editables: cada tarifa lleva una fecha ``actualizado`` que la UI muestra para
recordar revisarlos contra las tablas vigentes de CFE (que se actualizan
mensualmente). Los límites de bloque por clase y la ventana de verano varían
por localidad: aquí se usa una aproximación regional única.

Periodos horarios (Base/Intermedio/Punta) se reutilizan de
``motor_financiero.asignar_tarifa_gdmth`` para no duplicar la lógica.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from motor_financiero import asignar_tarifa_gdmth

# Fecha de referencia de los precios cargados. Actualizar con las tablas CFE.
ACTUALIZADO = "Referencia CFE jun-2026 · editable"

# Meses de verano (aprox. regional) para las tarifas domésticas estacionales.
# CFE define la temporada por localidad; aquí se usa mayo–octubre como referencia.
MESES_VERANO = [5, 6, 7, 8, 9, 10]

# Precios de referencia de la doméstica subsidiada (MXN/kWh), editables.
# Valores de la Tarifa 1 ordinaria vigentes para junio de 2026.
_P_BASICO = 0.793
_P_INTERMEDIO = 0.956
# El "intermedio alto" (clases cálidas 1C–1F en verano) no lo publica el PDF de
# forma desagregada; se usa un valor de referencia entre intermedio y excedente.
_P_INTERMEDIO_ALTO = 1.602
_P_EXCEDENTE = 2.802

# Cargo fijo mensual obligatorio doméstico (reforma CFE 2026): se cobra a TODOS
# los usuarios domésticos exista o no consumo. Varía por división de
# distribución, de 19.78 (Noroeste) a 70.34 (Valle de México Norte) MXN; aquí se
# usa un valor de referencia editable.
CARGO_FIJO_DOMESTICO = 40.0

# Cargo fijo mensual de la DAC (independiente del consumo), MXN.
CARGO_FIJO_DAC = 142.41

# Cargo fijo de suministro (SSB) en media tensión GDMTO/GDMTH, MXN/mes.
CARGO_FIJO_MT = 414.90


def _bloques_invierno():
    """Bloques de temporada fuera de verano: comunes a las clases 1–1F."""
    return [(75, _P_BASICO), (140, _P_INTERMEDIO), (None, _P_EXCEDENTE)]


# ── Definición de tarifas ───────────────────────────────────────────────────
# tipo:
#   "flat"   → precio_kwh
#   "tiered" → bloques [(limite_kwh_mensual | None, precio), ...] acumulativos.
#              Si tiene "bloques_verano"/"bloques_invierno", se elige por mes.
#   "tou"    → precios {Base, Intermedio, Punta}
#   "gdmth"  → delegado al motor financiero
# familia: "domestica" | "comercial"  (para agrupar el selector de la UI)
TARIFAS = {
    "1": {
        "nombre": "1 — Doméstica ordinaria (templado < 25 °C)",
        "tipo": "tiered", "familia": "domestica",
        "bloques": [(75, _P_BASICO), (140, _P_INTERMEDIO), (None, _P_EXCEDENTE)],
        "cargo_fijo": CARGO_FIJO_DOMESTICO, "limite_dac": 250,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Doméstica ordinaria subsidiada para localidades con temperatura "
            "media de verano menor a 25 °C, sin temporada. Se factura por "
            "bloques mensuales (básico ≤ 75, intermedio 76–140, excedente) sin "
            "horarios, más el cargo fijo. Pasa a DAC sobre 250 kWh/mes promedio."
        ),
    },
    "1A": {
        "nombre": "1A — Doméstica (≥ 25 °C)",
        "tipo": "tiered", "familia": "domestica",
        "bloques_verano": [(100, _P_BASICO), (150, _P_INTERMEDIO),
                           (None, _P_EXCEDENTE)],
        "bloques_invierno": _bloques_invierno(),
        "meses_verano": MESES_VERANO,
        "cargo_fijo": CARGO_FIJO_DOMESTICO, "limite_dac": 300,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Doméstica subsidiada para regiones con verano ≥ 25 °C. En verano "
            "el bloque básico llega a 100 kWh. Pasa a DAC sobre 300 kWh/mes."
        ),
    },
    "1B": {
        "nombre": "1B — Doméstica (≥ 28 °C)",
        "tipo": "tiered", "familia": "domestica",
        "bloques_verano": [(125, _P_BASICO), (225, _P_INTERMEDIO),
                           (None, _P_EXCEDENTE)],
        "bloques_invierno": _bloques_invierno(),
        "meses_verano": MESES_VERANO,
        "cargo_fijo": CARGO_FIJO_DOMESTICO, "limite_dac": 400,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Doméstica subsidiada para regiones con verano ≥ 28 °C; básico de "
            "verano hasta 125 kWh. Pasa a DAC sobre 400 kWh/mes."
        ),
    },
    "1C": {
        "nombre": "1C — Doméstica (≥ 30 °C)",
        "tipo": "tiered", "familia": "domestica",
        "bloques_verano": [(150, _P_BASICO), (300, _P_INTERMEDIO),
                           (450, _P_INTERMEDIO_ALTO), (None, _P_EXCEDENTE)],
        "bloques_invierno": _bloques_invierno(),
        "meses_verano": MESES_VERANO,
        "cargo_fijo": CARGO_FIJO_DOMESTICO, "limite_dac": 850,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Doméstica subsidiada para regiones con verano ≥ 30 °C; básico de "
            "verano hasta 150 kWh. Pasa a DAC sobre 850 kWh/mes."
        ),
    },
    "1D": {
        "nombre": "1D — Doméstica (≥ 31 °C)",
        "tipo": "tiered", "familia": "domestica",
        "bloques_verano": [(175, _P_BASICO), (400, _P_INTERMEDIO),
                           (600, _P_INTERMEDIO_ALTO), (None, _P_EXCEDENTE)],
        "bloques_invierno": _bloques_invierno(),
        "meses_verano": MESES_VERANO,
        "cargo_fijo": CARGO_FIJO_DOMESTICO, "limite_dac": 1000,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Doméstica subsidiada para regiones con verano ≥ 31 °C; básico de "
            "verano hasta 175 kWh. Pasa a DAC sobre 1,000 kWh/mes."
        ),
    },
    "1E": {
        "nombre": "1E — Doméstica (≥ 32 °C)",
        "tipo": "tiered", "familia": "domestica",
        "bloques_verano": [(200, _P_BASICO), (750, _P_INTERMEDIO),
                           (1200, _P_INTERMEDIO_ALTO), (None, _P_EXCEDENTE)],
        "bloques_invierno": _bloques_invierno(),
        "meses_verano": MESES_VERANO,
        "cargo_fijo": CARGO_FIJO_DOMESTICO, "limite_dac": 2000,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Doméstica subsidiada para regiones muy cálidas (verano ≥ 32 °C); "
            "básico de verano hasta 200 kWh. Pasa a DAC sobre 2,000 kWh/mes."
        ),
    },
    "1F": {
        "nombre": "1F — Doméstica (≥ 33 °C)",
        "tipo": "tiered", "familia": "domestica",
        "bloques_verano": [(250, _P_BASICO), (1200, _P_INTERMEDIO),
                           (2500, _P_INTERMEDIO_ALTO), (None, _P_EXCEDENTE)],
        "bloques_invierno": _bloques_invierno(),
        "meses_verano": MESES_VERANO,
        "cargo_fijo": CARGO_FIJO_DOMESTICO, "limite_dac": 2500,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Doméstica subsidiada para regiones de calor extremo (verano "
            "≥ 33 °C); básico de verano hasta 250 kWh. Pasa a DAC sobre 2,500 "
            "kWh/mes."
        ),
    },
    "DAC": {
        "nombre": "DAC — Doméstica de Alto Consumo",
        "tipo": "flat", "familia": "domestica",
        "precio_kwh": 5.844, "cargo_fijo": CARGO_FIJO_DAC,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Tarifa residencial sin subsidio que aplica al superar el límite de "
            "alto consumo de tu región (promedio móvil de 12 meses). Precio "
            "plano por kWh, sin horarios (≈5.33–6.19 según región; ref. Centro "
            "5.844) más un cargo fijo de 142.41 MXN/mes."
        ),
    },
    "GDMTO": {
        "nombre": "GDMTO — Gran Demanda MT Ordinaria",
        "tipo": "flat", "familia": "comercial",
        "precio_kwh": 1.107, "cargo_fijo": CARGO_FIJO_MT,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Media tensión ordinaria para demanda < 100 kW: cargo de energía "
            "PLANO (mismo precio a cualquier hora), sin penalización horaria, "
            "más cargos por demanda (kW) y el cargo fijo de suministro. Energía "
            "integrada de referencia 1.107 MXN/kWh (Monterrey 2026)."
        ),
    },
    "HM": {
        "nombre": "HM — Horaria Media Tensión",
        "tipo": "tou", "familia": "comercial",
        "precios": {"Base": 0.8969, "Intermedio": 1.3806, "Punta": 1.4964},
        "cargo_fijo": CARGO_FIJO_MT,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Media tensión con precio por horario: base (madrugada), "
            "intermedio (día) y punta (tarde-noche), más caro en punta. "
            "Estimador ligero; equivale a la energía integrada de GDMTH."
        ),
    },
    "GDMTH": {
        "nombre": "GDMTH — Gran Demanda MT Horaria",
        "tipo": "gdmth", "familia": "comercial",
        "delegado": True, "cargo_fijo": CARGO_FIJO_MT,
        "actualizado": ACTUALIZADO,
        "descripcion": (
            "Gran demanda en media tensión (≥ 100 kW) con horarios "
            "(base/intermedio/punta) y cargo por demanda (kW). Usa el análisis "
            "financiero completo con batería y apagones."
        ),
    },
}

# Subtarifas que se muestran al elegir la familia "doméstica" en la UI.
_SUBTARIFAS_DOMESTICAS = ["1", "1A", "1B", "1C", "1D", "1E", "1F", "DAC"]

_MESES_ES_SHORT = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                   "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _bloques_para_mes(tarifa, mes):
    """Lista de bloques aplicable a ``mes`` (1–12) para una tarifa tiered.

    Si la tarifa define ``bloques_verano``/``bloques_invierno``, elige según
    ``meses_verano``; si solo tiene ``bloques``, los devuelve tal cual.
    """
    if "bloques_verano" in tarifa:
        meses_v = tarifa.get("meses_verano", MESES_VERANO)
        return (tarifa["bloques_verano"] if mes in meses_v
                else tarifa["bloques_invierno"])
    return tarifa["bloques"]


def _bloques_representativos(tarifa):
    """Bloques de referencia para promedios anuales (usa invierno si es estacional)."""
    if "bloques_verano" in tarifa:
        return tarifa["bloques_invierno"]
    return tarifa["bloques"]


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


def _kwh_desde_costo_bloques(costo, bloques):
    """Inverso de :func:`_costo_bloques`: kWh que producen ``costo`` (MXN)."""
    restante_costo = float(costo)
    kwh = 0.0
    limite_previo = 0.0
    for limite, precio in bloques:
        if limite is None:
            kwh += restante_costo / precio
            restante_costo = 0.0
            break
        ancho = limite - limite_previo
        costo_bloque = ancho * precio
        if restante_costo <= costo_bloque:
            kwh += restante_costo / precio
            restante_costo = 0.0
            break
        kwh += ancho
        restante_costo -= costo_bloque
        limite_previo = limite
    return kwh


def estimar_recibo(perfil_15min, tarifa_id):
    """Estima el recibo mensual *de energía* para un perfil de demanda.

    Parameters
    ----------
    perfil_15min : DataFrame
        Índice 15-min tz-naive con columna ``Energia_kWh``.
    tarifa_id : str
        Clave en :data:`TARIFAS` (doméstica/DAC/HM). Para GDMTH usar el motor
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

    cargo_fijo = tarifa.get("cargo_fijo", 0.0)
    filas = []
    if tarifa["tipo"] == "tou":
        periodos = df.index.map(asignar_tarifa_gdmth)
        df = df.assign(_periodo=periodos)
        for mes, dmes in df.groupby(df.index.month):
            costo = cargo_fijo
            for periodo, precio in tarifa["precios"].items():
                kwh_p = dmes[dmes["_periodo"] == periodo]["Energia_kWh"].sum()
                costo += kwh_p * precio
            kwh_mes = dmes["Energia_kWh"].sum()
            filas.append({"Mes": mes, "kWh": kwh_mes, "Costo": costo})
    else:
        for mes, dmes in df.groupby(df.index.month):
            kwh_mes = dmes["Energia_kWh"].sum()
            if tarifa["tipo"] == "flat":
                costo = kwh_mes * tarifa["precio_kwh"] + cargo_fijo
            else:  # tiered (con o sin temporada)
                costo = (_costo_bloques(kwh_mes, _bloques_para_mes(tarifa, mes))
                         + cargo_fijo)
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
        bloques = _bloques_representativos(tarifa)
        return _costo_bloques(kwh_ref, bloques) / kwh_ref
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
    return kwh_mes_desde_costo(recibo_mensual_mxn, tarifa_id) / 30.4


def kwh_mes_desde_costo(costo_mxn, tarifa_id, mes=1):
    """Estima los kWh de un mes a partir de su costo (MXN), invirtiendo la tarifa.

    Para tarifas estacionales (1A–1F) usa los bloques del ``mes`` indicado.
    GDMTH se aproxima con la estructura horaria HM.
    """
    if costo_mxn is None or costo_mxn <= 0:
        raise ValueError("El costo mensual debe ser mayor que 0.")
    tarifa = TARIFAS[tarifa_id]
    # El recibo incluye el cargo fijo mensual: se descuenta antes de invertir la
    # parte de energía (lo que de verdad escala con los kWh consumidos).
    costo_energia = max(0.0, float(costo_mxn) - tarifa.get("cargo_fijo", 0.0))
    if costo_energia <= 0:
        return 0.0
    if tarifa["tipo"] == "flat":
        return costo_energia / tarifa["precio_kwh"]
    if tarifa["tipo"] == "tiered":
        return _kwh_desde_costo_bloques(costo_energia, _bloques_para_mes(tarifa, mes))
    # tou / gdmth: precio efectivo aproximado.
    tid = "HM" if tarifa["tipo"] == "gdmth" else tarifa_id
    return costo_energia / rate_efectiva(tid)


# ── Helpers para el selector de la UI (familia → subtarifa) ──────────────────

def familias_dropdown():
    """Opciones del selector de familia tarifaria."""
    return [
        {"label": "Doméstica (CFE 1/1A…1F/DAC)", "value": "domestica"},
        {"label": "GDMTO — Gran Demanda MT Ordinaria (plana)", "value": "GDMTO"},
        {"label": "HM — Horaria Media Tensión", "value": "HM"},
        {"label": "GDMTH — Gran Demanda MT Horaria", "value": "GDMTH"},
    ]


def subtarifas_dropdown(familia="domestica"):
    """Opciones de subtarifa para una familia (solo doméstica las tiene)."""
    if familia != "domestica":
        return []
    return [{"label": TARIFAS[t]["nombre"], "value": t}
            for t in _SUBTARIFAS_DOMESTICAS]


def tarifa_efectiva(familia, subtarifa=None):
    """Resuelve el id de tarifa concreto a partir de familia + subtarifa.

    Doméstica → la subtarifa elegida (default ``1C``); comercial → la propia
    familia (HM / GDMTH).
    """
    if familia == "domestica":
        return subtarifa if subtarifa in TARIFAS else "1C"
    return familia if familia in TARIFAS else "HM"


def opciones_dropdown():
    """(Compat.) Lista de opciones {label, value} de todas las tarifas."""
    return [{"label": t["nombre"], "value": tid} for tid, t in TARIFAS.items()]
