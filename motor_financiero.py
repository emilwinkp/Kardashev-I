"""Kardashev-I — Motor financiero / operativo.

Versión limpia e importable de la lógica de `simulacion_1.py`:
 - sin `input()` ni `print()` (no es interactivo)
 - recibe la generación solar y la demanda ya en memoria (DataFrames)
 - devuelve resultados estructurados para la UI (KPIs, recibos, recomendaciones)

`simulacion_1.py` se conserva intacto como script de consola de referencia.
"""
import random

import numpy as np
import pandas as pd

# ───────────────────────── Constantes económicas FIJAS ─────────────────────────
# Tarifa CFE GDMTH (MXN). Estructura de periodos y precios fijos por decisión de diseño.
PRECIO_BASE = 1.10
PRECIO_INTERMEDIO = 1.50
PRECIO_PUNTA = 3.20
CARGO_CAPACIDAD = 350.00      # MXN por kW de demanda en punta
CARGO_DISTRIBUCION = 100.00   # MXN por kW de demanda máxima

# Parámetros financieros fijos (modelo de simulacion_1.py)
# Factor de valor presente de los ahorros a lo largo del horizonte del proyecto.
HORIZONTE_ANIOS = 7
_FACTOR_VP_AHORROS = (
    HORIZONTE_ANIOS * ((1 + 0.0426) ** 6 / (1 + 0.007) ** 6) / (1 + 0.0411) ** 7
)

# Eficiencias y degradación de baterías
EFICIENCIA_CARGA = 0.95
EFICIENCIA_DESCARGA = 0.95
DEGRADACION_DIARIA = 0.0001

CAP_PILA_KWH = 100            # capacidad por pila (kWh) para dimensionar el banco diario

SEED_APAGONES = 42            # reproducibilidad de los apagones simulados


def asignar_tarifa_gdmth(fecha):
    """Clasifica un timestamp en periodo CFE (Base / Intermedio / Punta)."""
    hora = fecha.hour
    dia_semana = fecha.weekday()

    if dia_semana < 5:  # Lunes a Viernes
        if 18 <= hora < 22:
            return 'Punta'
        elif 0 <= hora < 6:
            return 'Base'
        else:
            return 'Intermedio'
    else:  # Fines de semana
        if 0 <= hora < 7:
            return 'Base'
        else:
            return 'Intermedio'


def _factor_potencia_efecto(fp):
    """Porcentaje de penalización/bonificación CFE según el factor de potencia."""
    if fp < 0.90:
        return (3 / 7) * ((0.90 / fp) - 1)
    return -(1 / 4) * (1 - (0.90 / fp))


def simular_financiero(df_solar, df_demanda, num_paneles, area,
                       costo_panel_m2, costo_pila,
                       cap_respaldo_max_kwh=500, num_apagones=30,
                       duracion_horas_apagon=1.5):
    """Simula la operación del sistema FV+baterías y evalúa el proyecto.

    Parameters
    ----------
    df_solar : DataFrame
        Índice 15-min tz-naive. Requiere la columna ``potencia_generada`` (W).
    df_demanda : DataFrame
        Índice 15-min tz-naive. Requiere ``Energia_kWh`` y ``Energia_kVArh``.
    num_paneles, area : int, float
        Para el costo de paneles (área total = num_paneles * area).
    costo_panel_m2, costo_pila : float
        Supuestos económicos editables (MXN).

    Returns
    -------
    dict con KPIs, DataFrames de recibos, resumen mensual y recomendaciones.
    """
    # ── Combinar solar + demanda sobre el índice común (15 min, año completo) ──
    df = df_solar.copy()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df.join(df_demanda, how='inner')

    if len(df) == 0:
        raise ValueError(
            "El cruce solar↔demanda quedó vacío. Verifica que el CSV use el "
            "año 2026 con resolución de 15 minutos.")

    n_total = len(df)
    n_esperado = len(df_solar)
    if n_total < 0.9 * n_esperado:
        # Cruce parcial: avisamos pero seguimos (se reporta en recomendaciones).
        cobertura = n_total / n_esperado * 100
    else:
        cobertura = 100.0

    # ── Apagones reproducibles ──
    periodos_por_apagon = max(1, int(duracion_horas_apagon * 4))
    df['apagon'] = False
    rng = random.Random(SEED_APAGONES)
    if n_total - periodos_por_apagon > 0:
        n_ap = min(num_apagones, n_total - periodos_por_apagon)
        inicios = rng.sample(range(0, n_total - periodos_por_apagon), n_ap)
        col_apagon = df.columns.get_loc('apagon')
        for inicio in inicios:
            df.iloc[inicio:inicio + periodos_por_apagon, col_apagon] = True

    df['periodo_cfe'] = df.index.map(asignar_tarifa_gdmth)

    # ── Dimensionar el banco diario por el peor día de consumo en Punta ──
    df_punta = df[df['periodo_cfe'] == 'Punta']
    consumo_punta_por_dia = df_punta.groupby(df_punta.index.date)['Energia_kWh'].sum()
    if len(consumo_punta_por_dia) > 0:
        sizing_diario_requerido = consumo_punta_por_dia.max()
    else:
        sizing_diario_requerido = 1000
    cap_diaria_virtual_max = sizing_diario_requerido

    # ── Estado inicial de baterías ──
    soc_respaldo = cap_respaldo_max_kwh
    soc_diario = 0
    cap_respaldo = cap_respaldo_max_kwh  # se degrada día a día

    compra_kwh_red_lista = []
    potencia_kw_red_lista = []
    reactive_kvarh_lista = []
    energia_desperdiciada_lista = []

    pot = df['potencia_generada'].values
    kvarh = df['Energia_kVArh'].values
    dem = df['Energia_kWh'].values
    periodos = df['periodo_cfe'].values
    apagones = df['apagon'].values

    # ── Bucle de operación quinceminutal (estrategia autoconsumo puro) ──
    for i in range(n_total):
        if i > 0 and i % 96 == 0:
            cap_respaldo *= (1 - DEGRADACION_DIARIA)
            soc_diario = 0  # reinicio de medianoche

        solar_kw = pot[i] / 1000
        reactive_kvarh = kvarh[i]
        tarifa = periodos[i]
        apagon = apagones[i]

        solar_kwh = solar_kw * 0.25
        demanda_kwh = dem[i]
        compra_red_kwh = 0
        desperdicio_bloque_kwh = 0

        if apagon:
            if solar_kwh >= demanda_kwh:
                sobrante = solar_kwh - demanda_kwh
                espacio_respaldo = max(0, cap_respaldo - soc_respaldo)
                carga_real = min(sobrante * EFICIENCIA_CARGA, espacio_respaldo)
                soc_respaldo += carga_real
                sobrante_neto = sobrante - (carga_real / EFICIENCIA_CARGA)
                desperdicio_bloque_kwh = max(0, sobrante_neto)
            else:
                deficit = demanda_kwh - solar_kwh
                descarga = deficit / EFICIENCIA_DESCARGA
                soc_respaldo = max(0, soc_respaldo - descarga)
            compra_red_kwh = 0
            reactive_kvarh = 0
        else:
            # P1: autoconsumo instantáneo
            energia_faltante_planta = max(0, demanda_kwh - solar_kwh)
            solar_sobrante = max(0, solar_kwh - demanda_kwh)

            if solar_sobrante > 0:
                # P2: rellenar respaldo de apagones
                if soc_respaldo < cap_respaldo:
                    espacio_respaldo = cap_respaldo - soc_respaldo
                    carga_respaldo = min(solar_sobrante * EFICIENCIA_CARGA, espacio_respaldo)
                    soc_respaldo += carga_respaldo
                    solar_sobrante -= (carga_respaldo / EFICIENCIA_CARGA)

                # P3: rellenar banco diario
                if solar_sobrante > 0:
                    espacio_diario = max(0, cap_diaria_virtual_max - soc_diario)
                    carga_diaria_real = min(solar_sobrante * EFICIENCIA_CARGA, espacio_diario)
                    soc_diario += carga_diaria_real
                    solar_sobrante -= (carga_diaria_real / EFICIENCIA_CARGA)

                # P4: curtailment
                desperdicio_bloque_kwh = max(0, solar_sobrante)

            compra_red_kwh = energia_faltante_planta

            # Descarga del banco diario en tarifa Punta
            if tarifa == 'Punta' and compra_red_kwh > 0:
                descarga_real = min(compra_red_kwh, soc_diario * EFICIENCIA_DESCARGA)
                soc_diario -= (descarga_real / EFICIENCIA_DESCARGA)
                compra_red_kwh -= descarga_real

        compra_kwh_red_lista.append(compra_red_kwh)
        potencia_kw_red_lista.append(compra_red_kwh / 0.25)
        reactive_kvarh_lista.append(reactive_kvarh)
        energia_desperdiciada_lista.append(desperdicio_bloque_kwh)

    df['compra_red_kwh'] = compra_kwh_red_lista
    df['potencia_red_kw'] = potencia_kw_red_lista
    df['reactive_red_kvarh'] = reactive_kvarh_lista
    df['energia_desperdiciada_kwh'] = energia_desperdiciada_lista
    df['potencia_original_kw'] = df['Energia_kWh'] / 0.25

    # ── Recibos mensuales: con sistema vs base ──
    recibo_sis = []
    recibo_base = []
    energia_mensual = []

    for mes, df_mes in df.groupby(df.index.month):
        # --- Con sistema FV ---
        e_base = df_mes[df_mes['periodo_cfe'] == 'Base']['compra_red_kwh'].sum()
        e_int = df_mes[df_mes['periodo_cfe'] == 'Intermedio']['compra_red_kwh'].sum()
        e_punta = df_mes[df_mes['periodo_cfe'] == 'Punta']['compra_red_kwh'].sum()

        dem_max = df_mes['potencia_red_kw'].max()
        dem_punta = df_mes[df_mes['periodo_cfe'] == 'Punta']['potencia_red_kw'].max()
        if pd.isna(dem_punta):
            dem_punta = 0

        costo_energia = (e_base * PRECIO_BASE + e_int * PRECIO_INTERMEDIO
                         + e_punta * PRECIO_PUNTA)
        subtotal = (costo_energia + dem_punta * CARGO_CAPACIDAD
                    + dem_max * CARGO_DISTRIBUCION)

        kwh_mes = df_mes['compra_red_kwh'].sum()
        kvarh_mes = df_mes['reactive_red_kvarh'].sum()
        fp = (kwh_mes / np.sqrt(kwh_mes ** 2 + kvarh_mes ** 2)
              if kwh_mes > 0 else 1.0)
        efecto_fp = subtotal * _factor_potencia_efecto(fp)
        desperdicio_mes = df_mes['energia_desperdiciada_kwh'].sum()

        recibo_sis.append({
            'Mes': mes,
            'Demanda_Punta_kW': round(dem_punta, 1),
            'Demanda_Max_kW': round(dem_max, 1),
            'FP_Mensual': round(fp, 3),
            'Efecto_FP_MXN': round(efecto_fp, 2),
            'Total_CFE_MXN': round(subtotal + efecto_fp, 2),
            'Solar_Desechada_kWh': round(desperdicio_mes, 1),
        })

        # --- Base (sin sistema) ---
        eb = df_mes[df_mes['periodo_cfe'] == 'Base']['Energia_kWh'].sum()
        ei = df_mes[df_mes['periodo_cfe'] == 'Intermedio']['Energia_kWh'].sum()
        ep = df_mes[df_mes['periodo_cfe'] == 'Punta']['Energia_kWh'].sum()

        dem_max_b = df_mes['potencia_original_kw'].max()
        dem_punta_b = df_mes[df_mes['periodo_cfe'] == 'Punta']['potencia_original_kw'].max()
        if pd.isna(dem_punta_b):
            dem_punta_b = 0

        costo_energia_b = (eb * PRECIO_BASE + ei * PRECIO_INTERMEDIO
                           + ep * PRECIO_PUNTA)
        subtotal_b = (costo_energia_b + dem_punta_b * CARGO_CAPACIDAD
                      + dem_max_b * CARGO_DISTRIBUCION)

        kwh_b = df_mes['Energia_kWh'].sum()
        kvarh_b = df_mes['Energia_kVArh'].sum()
        fp_b = (kwh_b / np.sqrt(kwh_b ** 2 + kvarh_b ** 2) if kwh_b > 0 else 1.0)
        efecto_fp_b = subtotal_b * _factor_potencia_efecto(fp_b)

        recibo_base.append({
            'Mes': mes,
            'Demanda_Punta_kW': round(dem_punta_b, 1),
            'Demanda_Max_kW': round(dem_max_b, 1),
            'FP_Mensual': round(fp_b, 3),
            'Efecto_FP_MXN': round(efecto_fp_b, 2),
            'Total_CFE_MXN': round(subtotal_b + efecto_fp_b, 2),
        })

        # --- Energía mensual (para gráficas) ---
        energia_mensual.append({
            'Mes': mes,
            'Demanda_kWh': round(df_mes['Energia_kWh'].sum(), 1),
            'Solar_Generada_kWh': round(df_mes['potencia_generada'].sum() * 0.25 / 1000, 1),
            'Compra_Red_kWh': round(df_mes['compra_red_kwh'].sum(), 1),
            'Desperdicio_kWh': round(df_mes['energia_desperdiciada_kwh'].sum(), 1),
        })

    df_recibo_sis = pd.DataFrame(recibo_sis)
    df_recibo_base = pd.DataFrame(recibo_base)
    df_energia_mensual = pd.DataFrame(energia_mensual)

    # ── Evaluación económica ──
    cant_pilas = max(1, int(np.ceil(sizing_diario_requerido / CAP_PILA_KWH)))

    ahorro_anual = (df_recibo_base['Total_CFE_MXN'].sum()
                    - df_recibo_sis['Total_CFE_MXN'].sum())

    area_total = num_paneles * area
    costo_total_paneles = area_total * costo_panel_m2
    costo_total_pilas = cant_pilas * costo_pila
    capex = costo_total_paneles + costo_total_pilas

    # VPN = valor presente de los ahorros − inversión (positivo = conviene)
    vp_ahorros = ahorro_anual * _FACTOR_VP_AHORROS
    npv = vp_ahorros - capex
    # J = función objetiva de costo de simulacion_1 (negativa = conviene)
    j_objetivo = capex - vp_ahorros

    payback_anios = (capex / ahorro_anual) if ahorro_anual > 0 else float('inf')
    roi_pct = (npv / capex * 100) if capex > 0 else 0.0

    # Curtailment
    total_desperdiciada = df['energia_desperdiciada_kwh'].sum()
    total_generada = df['potencia_generada'].sum() * 0.25 / 1000
    pct_desperdicio = (total_desperdiciada / total_generada * 100
                       if total_generada > 0 else 0)
    dinero_tirado = total_desperdiciada * PRECIO_INTERMEDIO

    recomendaciones = _generar_recomendaciones(
        payback_anios=payback_anios, npv=npv, roi_pct=roi_pct,
        pct_desperdicio=pct_desperdicio, ahorro_anual=ahorro_anual,
        fp_sis=df_recibo_sis['FP_Mensual'].min(),
        sizing=sizing_diario_requerido, cant_pilas=cant_pilas,
        cobertura=cobertura,
    )

    return {
        'df_recibo_sis': df_recibo_sis,
        'df_recibo_base': df_recibo_base,
        'df_energia_mensual': df_energia_mensual,
        'sizing_diario_requerido': sizing_diario_requerido,
        'cant_pilas': cant_pilas,
        'ahorro_anual': ahorro_anual,
        'costo_total_paneles': costo_total_paneles,
        'costo_total_pilas': costo_total_pilas,
        'capex': capex,
        'npv': npv,
        'j_objetivo': j_objetivo,
        'payback_anios': payback_anios,
        'roi_pct': roi_pct,
        'total_desperdiciada': total_desperdiciada,
        'total_generada': total_generada,
        'pct_desperdicio': pct_desperdicio,
        'dinero_tirado': dinero_tirado,
        'cobertura': cobertura,
        'recomendaciones': recomendaciones,
    }


def _generar_recomendaciones(payback_anios, npv, roi_pct, pct_desperdicio,
                             ahorro_anual, fp_sis, sizing, cant_pilas, cobertura):
    """Genera recomendaciones de inversión basadas en reglas sobre los KPIs."""
    recs = []

    if cobertura < 99:
        recs.append({
            'tipo': 'alerta',
            'texto': (f"El CSV de demanda solo cubre {cobertura:.0f}% del año 2026. "
                      "Los resultados son parciales; sube una serie completa a 15 min "
                      "para una evaluación confiable."),
        })

    # Rentabilidad global
    if npv > 0 and payback_anios < HORIZONTE_ANIOS:
        recs.append({
            'tipo': 'positivo',
            'texto': (f"Proyecto rentable: VPN positivo (${npv:,.0f}) y recuperación de "
                      f"inversión en {payback_anios:.1f} años, dentro del horizonte de "
                      f"{HORIZONTE_ANIOS} años."),
        })
    elif npv > 0:
        recs.append({
            'tipo': 'neutro',
            'texto': (f"VPN positivo (${npv:,.0f}) pero el payback de {payback_anios:.1f} "
                      "años es largo. Revisa supuestos de costo o tamaño del arreglo."),
        })
    else:
        recs.append({
            'tipo': 'alerta',
            'texto': (f"VPN negativo (${npv:,.0f}): con los costos actuales el proyecto no "
                      "se paga en el horizonte. Reduce CapEx o reconsidera el "
                      "dimensionamiento."),
        })

    # Curtailment
    if pct_desperdicio > 25:
        recs.append({
            'tipo': 'alerta',
            'texto': (f"Curtailment alto ({pct_desperdicio:.1f}% de la generación). El "
                      "arreglo está sobredimensionado frente a la demanda y el "
                      "almacenamiento: considera menos paneles o más capacidad de batería."),
        })
    elif pct_desperdicio > 10:
        recs.append({
            'tipo': 'neutro',
            'texto': (f"Curtailment moderado ({pct_desperdicio:.1f}%). Hay margen para "
                      "aprovechar excedente solar con más almacenamiento diario."),
        })
    else:
        recs.append({
            'tipo': 'positivo',
            'texto': (f"Curtailment bajo ({pct_desperdicio:.1f}%): el arreglo está bien "
                      "ajustado al perfil de consumo."),
        })

    # Factor de potencia
    if fp_sis is not None and fp_sis < 0.90:
        recs.append({
            'tipo': 'alerta',
            'texto': (f"El factor de potencia cae a {fp_sis:.2f} en algún mes (penalización "
                      "CFE). Instalar un banco de capacitores reduciría el recibo."),
        })

    # Banco diario
    recs.append({
        'tipo': 'info',
        'texto': (f"El banco diario requiere {sizing:,.0f} kWh ({cant_pilas} pila(s) de "
                  f"{CAP_PILA_KWH} kWh) para cubrir el peor día de consumo en horario punta."),
    })

    return recs
