"""Kardashev-I — Simulador Solar Fotovoltaico (Dash)

Replica visualmente design.html sobre la lógica de Dash + motor_2.py.
NOTA: motor_2.py es intocable.
"""
import base64
import datetime
import json
from io import StringIO
from zoneinfo import ZoneInfo

import dash
from dash import (ALL, Input, Output, State, callback, clientside_callback,
                  ctx, dash_table, dcc, html, no_update)
import dash_leaflet as dl
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from timezonefinder import TimezoneFinder

from motor_2 import calculate
from motor_fisica_avanzada import calculate_advanced, apply_advanced_losses
from motor_financiero import (HORIZONTE_ANIOS, TASA_DESCUENTO_DEFAULT,
                              TASA_INFLACION_DEFAULT, _generar_recomendaciones,
                              factor_vp_ahorros, simular_financiero)
from motor_diagnostico import dia_tipico, preparar_dia, DIA_TIPICO_DEFAULT
from motor_tmy import calculate_tmy, TMYUnavailable, preparar_tmy, poa_anual
import perfil_demanda
import tarifas_cfe
import bateria_specs
from geo_utils import fetch_altitude

_tf = TimezoneFinder()


def _tz_para_motor(iana_name: str) -> str:
    """Si el timezone tiene DST, convierte a offset fijo Etc/GMT±X para evitar
    errores de timestamps ambiguos/inexistentes en pd.date_range + pvlib."""
    try:
        tz = ZoneInfo(iana_name)
        summer = datetime.datetime(2026, 7, 15, tzinfo=tz).utcoffset()
        winter = datetime.datetime(2026, 1, 15, tzinfo=tz).utcoffset()
        if summer == winter:
            return iana_name  # Sin DST, se usa directo
        offset_h = round(winter.total_seconds() / 3600)
        if offset_h == 0:
            return "UTC"
        return f"Etc/GMT{-offset_h:+d}"  # Etc/GMT invierte el signo (POSIX)
    except Exception:
        return iana_name


# ───────────────────────── Constantes ──────────────────────────────────────────
ACCENT = "#fbbf24"
ACCENT_FILL = "rgba(251,191,36,0.20)"
ACCENT_FILL_SOFT = "rgba(251,191,36,0.55)"
INFO = "#60a5fa"
INFO_CMP = "#818cf8"
ACCENT_CMP = "#fb923c"
ACCENT_CMP_FILL = "rgba(251,146,60,0.15)"
DANGER = "#f43f5e"

PAPER_BG = "rgba(0,0,0,0)"
PLOT_BG = "rgba(0,0,0,0)"
GRID = "#141414"
TICK = "#666"
TEXT = "#a1a1a1"
TOOLTIP_BG = "#0a0a0a"
TOOLTIP_BD = "#262626"
FONT_FAMILY = "Inter, system-ui, sans-serif"

# Constantes default para el caso de Monterrey, Mexico
LAT_DEFAULT = 25.7
LON_DEFAULT = -100.3
ALT_DEFAULT = 540 

TZ_DEFAULT = "America/Mexico_City"
TILT_DEFAULT = 22
AZ_DEFAULT = 0   # Convención de UI: 0° = Sur (se convierte a geográfica para pvlib)
# Panel estándar de la industria (módulo monocristalino moderno):
# 440 Wp en STC = 2.0 m² × 22 % de eficiencia (número nominal redondo).
AREA_DEFAULT = 2.0      # m² por panel (estándar de la industria)
N_PANELS_DEFAULT = 100  # preset demo: 100 paneles → 200 m² (≈44 kWp)
EFF_DEFAULT = 0.22      # η módulo monocristalino moderno (~22 %)
PNOM_DEFAULT = 440      # Wp nominal STC/panel = AREA_DEFAULT · EFF_DEFAULT · 1000
PR_DEFAULT = 0.82

# Defaults de física avanzada (Modo Avanzado). En UI se usan unidades amables
# (%/°C, %, ...) y se convierten a fracción 1/°C al llamar al motor.
TAMB_DEFAULT = 25       # °C ambiente (anual)
GAMMA_DEFAULT = -0.40   # %/°C (coef. de temperatura γ_Pmax)
NOCT_DEFAULT = 45       # °C
SOILING_DEFAULT = 3     # % pérdidas por suciedad
WIRING_DEFAULT = 2      # % pérdidas en cableado (DC+AC)
ETA_INV_DEFAULT = 97    # % eficiencia del inversor
DEGR_DEFAULT = 0.5      # %/año degradación

# Consumo (Modo Simple)
KWH_MES_DEFAULT = 450   # kWh/mes (≈ 15 kWh/día, dato del recibo)
RECIBO_MES_DEFAULT = 10000  # MXN/mes (preset demo)
FAMILIA_DEFAULT = "GDMTO"  # preset demo (gran demanda MT plana, < 100 kW)
SUBTARIFA_DEFAULT = "1C"
MESES_ES_SHORT = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                  "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# Defaults financieros (editables en la página de análisis)
COSTO_PANEL_M2_DEFAULT = 1100     # MXN / m²
COSTO_PILA_DEFAULT = 400000       # MXN / pila (100 kWh)
NUM_APAGONES_DEFAULT = 10       # preset demo
DUR_APAGON_DEFAULT = 2.5       # horas (preset demo: justifica los 100 kWh)
CAP_RESPALDO_DEFAULT = 100      # kWh (preset demo = 1 pila)

# Cotización realista (capa opcional dentro del análisis)
COSTO_KWH_BESS_DEFAULT = 12000    # MXN/kWh instalado (LiFePO4 llave en mano)
BOS_PCT_DEFAULT = 30              # % BOS sobre equipo (inversores, montaje, instalación, trámites)
COSTO_TOTAL_DEFAULT = 1000000   # MXN — costo total del proyecto (preset demo)
# Pérdidas evitadas por interrupciones: reutilizan el nº de apagones y la
# duración del Modo Avanzado; solo se captura el costo por hora de inactividad.
COT_COSTO_HORA_DEFAULT = 6000     # MXN/hora de inactividad (preset demo)

# Tarifa GDMTH manual (Modo Avanzado, finanzas) — defaults = constantes del motor
# (energía integrada y cargos por demanda de referencia CFE 2026, Golfo Norte).
PRECIO_BASE_DEFAULT = 0.8969      # MXN/kWh
PRECIO_INT_DEFAULT = 1.3806       # MXN/kWh
PRECIO_PUNTA_DEFAULT = 1.4964     # MXN/kWh
CARGO_CAP_DEFAULT = 358.41        # MXN/kW (capacidad/punta)
CARGO_DIST_DEFAULT = 90.01        # MXN/kW (distribución)
INFLACION_DEFAULT = 4.26          # %/año (crecimiento del ahorro)
DESCUENTO_DEFAULT = 4.11          # %/año (tasa de descuento)

SUCCESS = "#22c55e"

MESES_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
MESES_ES_SHORT = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                  "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ───────────────────────── App init ────────────────────────────────────────────
app = dash.Dash(
    __name__,
    title="Kardashev-I — Simulador Solar Fotovoltaico",
    suppress_callback_exceptions=True,
    update_title=None,
)
server = app.server

app.index_string = """<!DOCTYPE html>
<html lang="es">
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
</footer>
</body>
</html>
"""


# ───────────────────────── Helpers ─────────────────────────────────────────────
def svg_img(svg_str, width=16, height=16, className=""):
    """Render an inline SVG as a data-URI <img>, preserving flex layout."""
    b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
    return html.Img(
        src=f"data:image/svg+xml;base64,{b64}",
        width=width, height=height, className=className,
    )


def empty_fig(msg="Ejecuta el cálculo para ver resultados"):
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor=PAPER_BG, plot_bgcolor=PLOT_BG,
        font=dict(family=FONT_FAMILY, color=TEXT, size=11),
        annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                          font=dict(size=12, color="#525252"),
                          xref="paper", yref="paper")],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


def _axes(yticksuffix=""):
    return dict(
        xaxis=dict(showgrid=False, linecolor="#1a1a1a", tickcolor=TICK,
                   zeroline=False),
        yaxis=dict(gridcolor=GRID, showgrid=True, linecolor="#1a1a1a",
                   tickcolor=TICK, ticksuffix=yticksuffix, zeroline=False),
    )


def _base_layout(margin_l=50, margin_b=30):
    return dict(
        paper_bgcolor=PAPER_BG, plot_bgcolor=PLOT_BG,
        font=dict(family=FONT_FAMILY, color=TEXT, size=11),
        margin=dict(l=margin_l, r=10, t=10, b=margin_b),
        hoverlabel=dict(bgcolor=TOOLTIP_BG, bordercolor=TOOLTIP_BD,
                        font=dict(family=FONT_FAMILY, color="#ededed")),
        showlegend=False,
    )


def build_daily_fig(daily):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily.values, mode="lines",
        line=dict(color=ACCENT, width=1.4),
        fill="tozeroy", fillcolor=ACCENT_FILL,
        hovertemplate="<b>%{x|%d %b}</b><br>%{y:.1f} kWh<extra></extra>",
    ))
    fig.update_layout(**_base_layout())
    fig.update_layout(**_axes(" kWh"))
    fig.update_xaxes(type="date", tickformat="%b", dtick="M1")
    return fig


def build_monthly_fig(df_monthly, peak_idx):
    values = df_monthly.values
    colors = [ACCENT if i == peak_idx else ACCENT_FILL_SOFT
              for i in range(len(values))]
    fig = go.Figure(go.Bar(
        x=MESES_ES_SHORT, y=values,
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0)")),
        hovertemplate="<b>%{x}</b><br>%{y:.0f} kWh<extra></extra>",
        width=0.55,
    ))
    fig.update_layout(**_base_layout(margin_l=45))
    fig.update_layout(**_axes(" kWh"))
    fig.update_layout(bargap=0.3)
    return fig


def build_irradiance_fig(sample, sample2=None):
    # Normalize both ranges to start at the same reference point so curves
    # overlay directly. Hover shows the actual original date for each trace.
    ref_start = sample.index[0].normalize()

    def _shift(s):
        delta = s.index[0].normalize() - ref_start
        shifted = s.copy()
        shifted.index = s.index - delta
        return shifted

    s1 = _shift(sample)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=s1.index, y=s1["ghi"], name="GHI ①", mode="lines",
        line=dict(color=INFO, width=1.2),
        hovertemplate="<b>%{x|%d %b %H:%M}</b><br>GHI: %{y:.0f} W/m²<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=s1.index, y=s1["poa_global"], name="POA ①", mode="lines",
        line=dict(color=ACCENT, width=1.4),
        fill="tozeroy", fillcolor=ACCENT_FILL,
        hovertemplate="<b>%{x|%d %b %H:%M}</b><br>POA: %{y:.0f} W/m²<extra></extra>",
    ))

    has_cmp = sample2 is not None and not sample2.empty
    if has_cmp:
        s2 = _shift(sample2)
        rng2_label = (f"{sample2.index[0].strftime('%d %b')} → "
                      f"{sample2.index[-1].strftime('%d %b')}")
        dates2 = sample2.index.strftime("%d %b %H:%M")
        fig.add_trace(go.Scatter(
            x=s2.index, y=s2["ghi"], name="GHI ②", mode="lines",
            line=dict(color=INFO_CMP, width=1.2, dash="dot"),
            customdata=dates2,
            hovertemplate=(
                f"<span style='color:{INFO_CMP};font-size:10px'>"
                f"② {rng2_label}</span><br>"
                "<b>%{customdata}</b><br>"
                "GHI: %{y:.0f} W/m²<extra></extra>"
            ),
        ))
        fig.add_trace(go.Scatter(
            x=s2.index, y=s2["poa_global"], name="POA ②", mode="lines",
            line=dict(color=ACCENT_CMP, width=1.4, dash="dot"),
            fill="tozeroy", fillcolor=ACCENT_CMP_FILL,
            customdata=dates2,
            hovertemplate=(
                f"<span style='color:{ACCENT_CMP};font-size:10px'>"
                f"② {rng2_label}</span><br>"
                "<b>%{customdata}</b><br>"
                "POA: %{y:.0f} W/m²<extra></extra>"
            ),
        ))

    r1 = (f"{sample.index[0].strftime('%d %b')} – "
          f"{sample.index[-1].strftime('%d %b')}")
    ann_text = f"─── {r1}"
    if has_cmp:
        r2 = (f"{sample2.index[0].strftime('%d %b')} – "
              f"{sample2.index[-1].strftime('%d %b')}")
        ann_text += f"&nbsp;&nbsp;&nbsp;╌╌╌ {r2}"

    fig.update_layout(**_base_layout())
    fig.update_layout(
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            font=dict(size=10, color=TEXT, family=FONT_FAMILY),
            bgcolor="rgba(0,0,0,0)",
            itemclick="toggle", itemdoubleclick="toggleothers",
        ),
        margin=dict(l=50, r=10, t=34, b=30),
    )
    fig.update_layout(**_axes(" W/m²"))
    fig.update_layout(hovermode="x unified")
    fig.add_annotation(
        text=ann_text,
        xref="paper", yref="paper",
        x=1, y=1,
        xanchor="right", yanchor="bottom",
        showarrow=False,
        font=dict(size=9, color="#525252", family=FONT_FAMILY),
    )
    fig.update_xaxes(type="date")
    return fig


def build_energy_15min_fig(sample):
    """Energía activa por intervalo de 15 min (kWh), forma escalonada."""
    e = (sample["potencia_generada"] * (15.0 / 60.0) / 1000.0)
    # cumulative within each day as secondary trace
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=sample.index, y=e.values,
        mode="lines",
        line=dict(color=ACCENT, width=1.4, shape="hv"),
        fill="tozeroy", fillcolor=ACCENT_FILL,
        hovertemplate="<b>%{x|%d %b %H:%M}</b><br>%{y:.4f} kWh<extra></extra>",
        name="Energía 15 min",
    ))
    fig.update_layout(**_base_layout())
    fig.update_layout(**_axes(" kWh"))
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(type="date")
    return fig


# ───────────────────────── Diagnóstico rápido (día típico) ─────────────────────
def build_dia_tipico_irr_fig(df):
    """Irradiancia de un día típico: GHI/DNI/DHI + POA (W/m²) vs hora del día."""
    x = df.index
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=df["poa_global"], name="POA", mode="lines",
        line=dict(color=ACCENT, width=1.8), fill="tozeroy", fillcolor=ACCENT_FILL,
        hovertemplate="%{x|%H:%M}<br>POA %{y:.0f} W/m²<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=x, y=df["ghi"], name="GHI", mode="lines",
        line=dict(color=INFO, width=1.3),
        hovertemplate="%{x|%H:%M}<br>GHI %{y:.0f} W/m²<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=x, y=df["dni"], name="DNI", mode="lines",
        line=dict(color=ACCENT_CMP, width=1.2, dash="dot"),
        hovertemplate="%{x|%H:%M}<br>DNI %{y:.0f} W/m²<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=x, y=df["dhi"], name="DHI", mode="lines",
        line=dict(color=INFO_CMP, width=1.2, dash="dot"),
        hovertemplate="%{x|%H:%M}<br>DHI %{y:.0f} W/m²<extra></extra>"))
    fig.update_layout(**_base_layout(margin_b=30))
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left",
                    x=0, font=dict(size=10, color=TEXT, family=FONT_FAMILY),
                    bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=50, r=10, t=30, b=30),
    )
    fig.update_layout(**_axes(" W/m²"))
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(type="date", tickformat="%H:%M", dtick=3 * 3600 * 1000)
    return fig


def build_dia_tipico_pot_fig(df):
    """Potencia de un solo panel (W) a lo largo del día típico."""
    x = df.index
    pico = df["potencia_panel_W"].max()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=df["potencia_panel_W"], mode="lines",
        line=dict(color=SUCCESS, width=1.8), fill="tozeroy",
        fillcolor="rgba(34,197,94,0.18)",
        hovertemplate="%{x|%H:%M}<br>%{y:.0f} W<extra></extra>", name="1 panel"))
    fig.update_layout(**_base_layout())
    fig.update_layout(**_axes(" W"))
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(type="date", tickformat="%H:%M", dtick=3 * 3600 * 1000)
    if pico and pico > 0:
        fig.add_hline(y=pico, line=dict(color=TICK, width=1, dash="dot"),
                      annotation_text=f"pico {pico:.0f} W",
                      annotation_position="top left",
                      annotation_font=dict(size=10, color="#525252"))
    return fig


# ───────────────────────── Advanced figures ────────────────────────────────────
def build_decomp_fig(sample):
    """4 paneles GHI/DNI/DHI/POA (W/m²) + elevación solar sobre GHI."""
    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"secondary_y": True}, {}], [{}, {}]],
        subplot_titles=("GHI + elevación solar", "DNI (haz directo)",
                        "DHI (difusa)", "POA / Gtot (plano del panel)"),
        horizontal_spacing=0.10, vertical_spacing=0.28,
    )
    x = sample.index
    # GHI + elevación solar (eje secundario)
    fig.add_trace(go.Scatter(x=x, y=sample["ghi"], mode="lines", name="GHI",
                             line=dict(color=ACCENT, width=1.3),
                             hovertemplate="GHI %{y:.0f} W/m²<extra></extra>"),
                  row=1, col=1, secondary_y=False)
    if "solar_elevation" in sample.columns:
        elev = sample["solar_elevation"].clip(lower=0)
        fig.add_trace(go.Scatter(x=x, y=elev, mode="lines", name="Elev. solar",
                                 line=dict(color=INFO, width=1, dash="dot"),
                                 hovertemplate="Elev %{y:.0f}°<extra></extra>"),
                      row=1, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=x, y=sample["dni"], mode="lines", name="DNI",
                             line=dict(color=ACCENT_CMP, width=1.3),
                             hovertemplate="DNI %{y:.0f} W/m²<extra></extra>"),
                  row=1, col=2)
    fig.add_trace(go.Scatter(x=x, y=sample["dhi"], mode="lines", name="DHI",
                             line=dict(color=INFO_CMP, width=1.3),
                             hovertemplate="DHI %{y:.0f} W/m²<extra></extra>"),
                  row=2, col=1)
    fig.add_trace(go.Scatter(x=x, y=sample["poa_global"], mode="lines", name="POA",
                             line=dict(color=SUCCESS, width=1.3),
                             hovertemplate="POA %{y:.0f} W/m²<extra></extra>"),
                  row=2, col=2)
    fig.update_layout(**_base_layout(margin_l=45, margin_b=30))
    fig.update_layout(showlegend=False, margin=dict(l=45, r=10, t=28, b=30))
    fig.update_xaxes(showgrid=False, linecolor="#1a1a1a", tickcolor=TICK,
                     zeroline=False, type="date")
    fig.update_yaxes(gridcolor=GRID, showgrid=True, linecolor="#1a1a1a",
                     tickcolor=TICK, zeroline=False)

    # Headroom (~15%) para que los picos no se solapen con el título del subplot.
    def _hr(col):
        if col not in sample.columns:
            return None
        m = float(np.nanmax(sample[col].values)) if len(sample) else 0.0
        return [0, m * 1.15] if m > 0 else None
    for col, (r, c) in {"ghi": (1, 1), "dni": (1, 2),
                        "dhi": (2, 1), "poa_global": (2, 2)}.items():
        rng = _hr(col)
        if rng is not None:
            fig.update_yaxes(range=rng, row=r, col=c, secondary_y=False)

    fig.update_yaxes(title_text="W/m²", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="°", row=1, col=1, secondary_y=True,
                     showgrid=False, range=[0, 90])
    fig.for_each_annotation(lambda a: a.update(font=dict(size=12, color=TEXT)))
    return fig


def build_waterfall_fig(p):
    """Cascada de pérdidas: nominal → pérdidas → energía neta (kWh/año)."""
    etapas = [
        ("Nominal (STC)", "relative", p.get("nominal", 0)),
        ("Temperatura", "relative", -p.get("temperatura", 0)),
        ("Suciedad", "relative", -p.get("suciedad", 0)),
        ("IAM", "relative", -p.get("iam", 0)),
        ("Cableado", "relative", -p.get("cableado", 0)),
        ("Inversor", "relative", -p.get("inversor", 0)),
        ("Degradación", "relative", -p.get("degradacion", 0)),
        ("Neto", "total", 0),
    ]
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=[e[1] for e in etapas],
        x=[e[0] for e in etapas],
        y=[e[2] for e in etapas],
        connector=dict(line=dict(color="#333", width=1)),
        increasing=dict(marker=dict(color=ACCENT)),
        decreasing=dict(marker=dict(color=DANGER)),
        totals=dict(marker=dict(color=SUCCESS)),
        hovertemplate="%{x}<br>%{y:,.0f} kWh<extra></extra>",
    ))
    fig.update_layout(**_base_layout(margin_l=55, margin_b=70))
    fig.update_layout(**_axes(" kWh"))
    fig.update_xaxes(tickangle=-40)
    return fig


def build_payback_fig(df_flujo):
    """Flujo de caja descontado acumulado año a año (VPN al cierre).

    Barras rojas mientras la inversión no se recupera, verdes una vez que el
    acumulado cruza a positivo. La línea sigue el valor presente neto acumulado.
    """
    anios = df_flujo["Anio"].tolist()
    acum = df_flujo["Acumulado_MXN"].tolist()
    x = [f"Año {a}" for a in anios]
    colors = [SUCCESS if v >= 0 else DANGER for v in acum]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=acum, marker=dict(color=colors),
        hovertemplate="<b>%{x}</b><br>Acumulado: $%{y:,.0f}<extra></extra>",
        name="VPN acumulado",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=acum, mode="lines+markers",
        line=dict(color=ACCENT, width=1.6),
        marker=dict(size=5, color=ACCENT),
        hoverinfo="skip", name="Tendencia",
    ))
    fig.add_hline(y=0, line=dict(color=TICK, width=1, dash="dot"))
    fig.update_layout(**_base_layout(margin_l=60, margin_b=40))
    fig.update_layout(**_axes())
    fig.update_yaxes(tickprefix="$")
    return fig


# ───────────────────────── Finance figures ─────────────────────────────────────
def build_bill_compare_fig(df_sis, df_base):
    """Recibo CFE mensual: base (sin sistema) vs con sistema FV."""
    meses = [MESES_ES_SHORT[m - 1] for m in df_base["Mes"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=meses, y=df_base["Total_CFE_MXN"], name="Sin sistema",
        marker=dict(color=ACCENT_FILL_SOFT),
        hovertemplate="<b>%{x}</b><br>Base: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=meses, y=df_sis["Total_CFE_MXN"], name="Con sistema",
        marker=dict(color=ACCENT),
        hovertemplate="<b>%{x}</b><br>Sistema: $%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(margin_l=55))
    fig.update_layout(**_axes())
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.1)
    fig.update_yaxes(tickprefix="$")
    return fig


def build_energy_month_fig(df_e):
    """Energía mensual: demanda vs compra a la red vs generación solar."""
    meses = [MESES_ES_SHORT[m - 1] for m in df_e["Mes"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=meses, y=df_e["Demanda_kWh"], name="Demanda",
        marker=dict(color=INFO),
        hovertemplate="<b>%{x}</b><br>Demanda: %{y:,.0f} kWh<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=meses, y=df_e["Compra_Red_kWh"], name="Compra red",
        marker=dict(color=DANGER),
        hovertemplate="<b>%{x}</b><br>Red: %{y:,.0f} kWh<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=meses, y=df_e["Solar_Generada_kWh"], name="Solar generada",
        mode="lines+markers", line=dict(color=ACCENT, width=2),
        hovertemplate="<b>%{x}</b><br>Solar: %{y:,.0f} kWh<extra></extra>",
    ))
    fig.update_layout(**_base_layout(margin_l=55))
    fig.update_layout(**_axes(" kWh"))
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.1)
    return fig


def build_curtail_fig(df_e):
    """Energía solar desperdiciada (curtailment) por mes."""
    meses = [MESES_ES_SHORT[m - 1] for m in df_e["Mes"]]
    fig = go.Figure(go.Bar(
        x=meses, y=df_e["Desperdicio_kWh"],
        marker=dict(color=ACCENT_CMP),
        hovertemplate="<b>%{x}</b><br>%{y:,.0f} kWh desperdiciados<extra></extra>",
        width=0.55,
    ))
    fig.update_layout(**_base_layout(margin_l=55))
    fig.update_layout(**_axes(" kWh"))
    fig.update_layout(bargap=0.3)
    return fig


def build_recibo_table(df):
    """Render a DataFrame as a styled HTML table."""
    header = html.Thead(html.Tr([html.Th(c) for c in df.columns]))
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if isinstance(v, float):
                txt = f"{v:,.2f}" if c != "FP_Mensual" else f"{v:.3f}"
            else:
                txt = str(v)
            cells.append(html.Td(txt))
        rows.append(html.Tr(cells))
    return html.Table(className="fin-table", children=[header, html.Tbody(rows)])


def chart_dl_btn(gid):
    """Botón pequeño para exportar a Excel los datos de la gráfica ``gid``."""
    return html.Button(
        "⬇ Excel", id={"type": "dl-graph", "index": gid},
        className="chart-dl-btn", n_clicks=0, title="Exportar datos a Excel")


def build_recommendations(recs):
    items = []
    for r in recs:
        items.append(html.Div(className=f"rec rec-{r['tipo']}", children=[
            html.Span(className="rec-dot"),
            html.Span(r["texto"], className="rec-text"),
        ]))
    return items


# ───────────────────────── SVG icons (inline) ──────────────────────────────────
ICON_FG = "#a1a1a1"
ICON_BTN = "#000000"

_ICON_ENERGY = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/></svg>'
_ICON_PEAK = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>'
_ICON_CF = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
_ICON_SUN = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/></svg>'
_ICON_ARROW = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_BTN}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
_ICON_BOLT = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_BTN}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/></svg>'
_ICON_ALERT = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{DANGER}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>'
_ICON_MONEY = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>'
_ICON_CLOCK = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
_ICON_TREND = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 6l-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/></svg>'
_ICON_PIGGY = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 5c-1.5 0-2.8 1.4-3 2-3.5-1.5-11-.3-11 5 0 1.8 0 3 2 4.5V20h4v-2h3v2h4v-4c1-.5 1.7-1 2-2h2v-4h-2c0-1-.5-1.5-1-2V5z"/><path d="M9 8h4"/></svg>'
_ICON_WASTE = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{ICON_FG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m5 0V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2"/></svg>'


# ───────────────────────── Landing ─────────────────────────────────────────────
landing = html.Div(id="landing", children=[
    html.Div(className="land-inner", children=[
        html.Div(className="land-eyebrow", children=[
            html.Span(className="dot"),
            "v0.1 · Simulación fotovoltaica",
        ]),
        html.H1(className="land-title", children=[
            "Kardashev",
            html.Span("—", className="dash"),
            "I",
        ]),
        html.P(
            "Un simulador de generación solar fotovoltaica de precisión. "
            "Modela tu instalación con datos geoespaciales reales, geometría "
            "solar e irradiancia POA.",
            className="land-sub",
        ),
        html.Button(
            id="enter-app", n_clicks=0, className="land-cta",
            children=[
                "Entrar al simulador",
                svg_img(_ICON_ARROW, 16, 16),
            ],
        ),
    ]),
    html.Div(className="land-meta", children=[
        html.Span("EST. 2026 · OBSERVATORIO ENERGÉTICO"),
        html.Span(id="land-meta-coords",
                  children=f"LAT {LAT_DEFAULT:.4f} · LON {LON_DEFAULT:.4f} · {TZ_DEFAULT}"),
    ]),
])


# ───────────────────────── Topbar ──────────────────────────────────────────────
topbar = html.Header(className="topbar", children=[
    html.Div(className="brand", children=[
        html.Div(className="brand-mark"),
        html.Div(className="brand-name", children=[
            "Kardashev-I ",
            html.Span("/"),
            " Simulador FV",
        ]),
    ]),
    html.Nav(className="topnav", children=[
        dcc.Link("Simulador FV", href="/sim", id="nav-sim",
                 className="nav-link active"),
        dcc.Link("Análisis ROI", href="/finanzas", id="nav-fin",
                 className="nav-link"),
    ]),
    html.Div(className="topbar-right", children=[
        html.Div(className="pill", children=[
            html.Span(className="dot"),
            "JENSEN · ACTIVO",
        ]),
        html.Button(id="btn-mode", className="mode-btn", n_clicks=0, children=[
            html.Span("⚙", className="mode-gear"),
            html.Span("Modo Avanzado", id="mode-label"),
            html.Span("", id="mode-badge", className="mode-badge hidden"),
        ]),
    ]),
])


# ───────────────────────── Sidebar ─────────────────────────────────────────────
sidebar = html.Aside(className="sidebar", children=[
    html.Div(className="sb-head", children=[
        html.Div("Configuración", className="sb-kicker"),
        html.H2("Parámetros del sistema", className="sb-title"),
        html.P(
            "Define la ubicación, la geometría del arreglo y las pérdidas. "
            "Los resultados se calcularán con el modelo de Jensen.",
            className="sb-desc",
        ),
    ]),

    # 1 — Ubicación
    html.Div(className="section", children=[
        html.Div(className="section-head", children=[
            html.H3("Ubicación"),
            html.Span("01", className="num"),
        ]),
        dl.Map(
            id="map",
            center=[LAT_DEFAULT, LON_DEFAULT],
            zoom=4,
            zoomControl=True,
            attributionControl=False,
            children=[
                dl.TileLayer(),
                dl.CircleMarker(
                    id="map-marker",
                    center=[LAT_DEFAULT, LON_DEFAULT],
                    radius=7,
                    fillColor=ACCENT, fillOpacity=1,
                    color="#000", weight=2, opacity=1,
                ),
            ],
        ),
        html.Div(className="field-row", style={"marginTop": "12px"}, children=[
            html.Div(className="field", children=[
                html.Label(["Latitud ", html.Span("°N", className="hint")]),
                dcc.Input(id="inp-lat", type="number", value=LAT_DEFAULT,
                          step=0.0001, className="input", debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Longitud ", html.Span("°E", className="hint")]),
                dcc.Input(id="inp-lon", type="number", value=LON_DEFAULT,
                          step=0.0001, className="input", debounce=True),
            ]),
        ]),
        html.Div(className="field", children=[
            html.Label(["Zona horaria ", html.Span("auto", className="hint")]),
            dcc.Input(id="inp-tz", type="text", value=TZ_DEFAULT,
                      className="input", readOnly=True,
                      style={"opacity": "0.6", "cursor": "default"}),
        ]),
        html.Div(className="field adv-only", children=[
            html.Label(["Altitud ", html.Span("msnm · auto", className="hint")]),
            dcc.Input(id="inp-alt", type="number", value=ALT_DEFAULT,
                      step=1, min=0, max=8848, className="input", debounce=True),
        ]),
    ]),

    # 2 — Orientación
    html.Div(className="section", children=[
        html.Div(className="section-head", children=[
            html.H3("Orientación"),
            html.Span("02", className="num"),
        ]),

        # Tilt
        html.Div(className="field", children=[
            html.Div(className="slider-wrap", children=[
                html.Div(className="slider-top", children=[
                    html.Label("Inclinación (tilt)", style={"margin": 0}),
                    html.Div(className="slider-value", children=[
                        dcc.Input(
                            id="inp-tilt-num", type="number",
                            min=0, max=90, step=1, value=TILT_DEFAULT,
                            className="slider-value-input",
                        ),
                        html.Span("°", className="u"),
                    ]),
                ]),
                dcc.Input(id="sld-tilt", type="range",
                          min=0, max=90, step=1, value=TILT_DEFAULT),
                html.Div(className="ticks", children=[
                    html.Span("0°"), html.Span("30°"),
                    html.Span("60°"), html.Span("90°"),
                ]),
            ]),
        ]),

        # Azimut
        html.Div(className="field", style={"marginTop": "18px"}, children=[
            html.Label("Azimut (0° = Sur)", style={"marginBottom": "8px"}),
            html.Div(className="compass-wrap", children=[
                html.Div(className="compass", id="compass", children=[
                    html.Div(className="ring"),
                    html.Div("N", className="lbl n"),
                    html.Div("E", className="lbl e"),
                    html.Div("S", className="lbl s"),
                    html.Div("O", className="lbl w"),
                    html.Div(className="needle", id="needle"),
                    html.Div(className="center"),
                ]),
                html.Div(className="compass-info", children=[
                    html.Div(className="val", children=[
                        dcc.Input(
                            id="inp-az-num", type="number",
                            min=0, max=360, step=1, value=AZ_DEFAULT,
                            className="slider-value-input compass-val-input",
                        ),
                        html.Span("°"),
                    ]),
                    html.Div("SUR · óptimo en hemisferio N",
                             className="dir", id="val-azdir"),
                    dcc.Input(id="sld-azimuth", type="range",
                              min=0, max=360, step=1, value=AZ_DEFAULT,
                              style={"marginTop": "2px"}),
                ]),
            ]),
        ]),
    ]),

    # 3 — Sistema
    html.Div(className="section", children=[
        html.Div(className="section-head", children=[
            html.H3("Sistema"),
            html.Span("03", className="num"),
        ]),
        html.Div(className="field", children=[
            html.Label(["Núm. paneles ",
                        html.Span("uds", className="hint")]),
            dcc.Input(id="inp-n-panels", type="number",
                      value=N_PANELS_DEFAULT, step=1, min=1,
                      className="input", debounce=True),
        ]),
        # Área y potencia nominal por panel: solo Modo Avanzado (personalización).
        # En Modo Simple se usa el panel estándar de la industria (ver abajo).
        html.Div(className="field-row adv-only", children=[
            html.Div(className="field", children=[
                html.Label(["Área/panel ",
                            html.Span("m²", className="hint")]),
                dcc.Input(id="inp-area", type="number", value=AREA_DEFAULT,
                          step=0.1, min=0.1, className="input", debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Potencia nominal ",
                            html.Span("Wp · STC", className="hint")]),
                dcc.Input(id="inp-pnom", type="number", value=PNOM_DEFAULT,
                          step="any", min=1, className="input", debounce=True),
            ]),
        ]),
        html.Div(id="total-area-display", className="total-area-display",
                 children=f"Área total: {N_PANELS_DEFAULT * AREA_DEFAULT:.1f} m²"),
        html.Div(id="stc-power-display", className="total-area-display",
                 children=(f"Panel estándar: {PNOM_DEFAULT:.0f} Wp · "
                           f"{AREA_DEFAULT:.1f} m² · η {EFF_DEFAULT * 100:.0f}% · "
                           f"{N_PANELS_DEFAULT * AREA_DEFAULT * EFF_DEFAULT:.2f} kWp")),
        html.Div(className="field adv-only", children=[
            html.Label(["Eficiencia η (Realistic ~ 0.15-0.22) ",
                        html.Span("0–1", className="hint")]),
            dcc.Input(id="inp-eff", type="number", value=EFF_DEFAULT,
                      step="any", min=0.01, max=1, className="input",
                      debounce=True),
        ]),
        # PR retirado de la UI: el Modo Simple usa el valor estándar fijo
        # (PR_DEFAULT = 0.82) y el Modo Avanzado calcula las pérdidas en detalle
        # (cascada), donde el PR no interviene. Se conserva como input oculto para
        # alimentar al motor base sin romper los callbacks que lo leen.
        html.Div(style={"display": "none"}, children=[
            dcc.Input(id="inp-pr", type="number", value=PR_DEFAULT),
        ]),
        html.Div(className="field adv-only", children=[
            html.Label(["Factor de potencia ",
                        html.Span("cos φ", className="hint")]),
            dcc.Input(id="inp-fp", type="number", value=1.0,
                      step=0.01, min=0.01, max=1.0, className="input",
                      debounce=True),
        ]),
    ]),

    # 4 — Física avanzada (solo Modo Avanzado)
    html.Div(className="section adv-only", children=[
        html.Div(className="section-head", children=[
            html.H3("Física avanzada"),
            html.Span("04", className="num"),
        ]),
        html.Div(className="info-box", children=[
            html.P([
                html.Strong("¿Qué hace este modo? "),
                "Sustituye el factor de pérdidas global (PR) por un modelo de "
                "pérdidas físicas explícito y trazable, paso a paso:",
            ]),
            html.Ul(className="info-list", children=[
                html.Li([html.B("Temperatura: "),
                         "estima la temperatura de celda con el modelo NOCT "
                         "(Tcell = Tamb + (NOCT−20)·POA/800) y corrige la "
                         "eficiencia con el coeficiente γ_Pmax. Un panel caliente "
                         "genera menos."]),
                html.Li([html.B("Suciedad: "),
                         "polvo y mugre sobre el vidrio (2–5% típico)."]),
                html.Li([html.B("IAM: "),
                         "pérdidas por reflexión al incidir la luz en ángulo "
                         "(modelo Martin-Ruiz, opcional)."]),
                html.Li([html.B("Cableado e inversor: "),
                         "pérdidas óhmicas DC+AC y la eficiencia del inversor."]),
                html.Li([html.B("Degradación: "),
                         "envejecimiento del módulo (%/año) según el año que "
                         "proyectes."]),
            ]),
            html.P([
                html.Strong("¿Por qué? "),
                "El PR único oculta de dónde vienen las pérdidas. Al separarlas "
                "obtienes una estimación más realista y la cascada de pérdidas "
                "te dice exactamente cuánta energía pierde cada efecto.",
            ], className="info-foot"),
        ]),
        html.Div(className="field-row", children=[
            html.Div(className="field", children=[
                html.Label(["Temp. ambiente ",
                            html.Span("°C", className="hint")]),
                dcc.Input(id="inp-tamb", type="number", value=TAMB_DEFAULT,
                          step=1, className="input", debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Coef. γ_Pmax ",
                            html.Span("%/°C", className="hint")]),
                dcc.Input(id="inp-gamma", type="number", value=GAMMA_DEFAULT,
                          step="any", className="input", debounce=True),
            ]),
        ]),
        html.Div(className="field-row", children=[
            html.Div(className="field", children=[
                html.Label(["NOCT ", html.Span("°C", className="hint")]),
                dcc.Input(id="inp-noct", type="number", value=NOCT_DEFAULT,
                          step=1, className="input", debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Suciedad ", html.Span("%", className="hint")]),
                dcc.Input(id="inp-soiling", type="number", value=SOILING_DEFAULT,
                          step="any", min=0, max=30, className="input",
                          debounce=True),
            ]),
        ]),
        html.Div(className="field-row", children=[
            html.Div(className="field", children=[
                html.Label(["Cableado ", html.Span("%", className="hint")]),
                dcc.Input(id="inp-wiring", type="number", value=WIRING_DEFAULT,
                          step="any", min=0, max=15, className="input",
                          debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Eficiencia inversor ",
                            html.Span("%", className="hint")]),
                dcc.Input(id="inp-eta-inv", type="number", value=ETA_INV_DEFAULT,
                          step="any", min=50, max=100, className="input",
                          debounce=True),
            ]),
        ]),
        html.Div(className="field-row", children=[
            html.Div(className="field", children=[
                html.Label(["Degradación ", html.Span("%/año", className="hint")]),
                dcc.Input(id="inp-degr", type="number", value=DEGR_DEFAULT,
                          step="any", min=0, max=5, className="input",
                          debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Año proyección ", html.Span("0–25", className="hint")]),
                dcc.Input(id="inp-year-idx", type="number", value=0,
                          step=1, min=0, max=25, className="input",
                          debounce=True),
            ]),
        ]),
        html.Div(className="field", children=[
            dcc.Checklist(
                id="chk-iam", className="chk-row",
                options=[{"label": " Aplicar IAM (ángulo de incidencia)",
                          "value": "iam"}],
                value=[],
            ),
        ]),
    ]),

    html.Div(className="section", children=[
        html.Div(className="section-head", children=[
            html.H3("Fuente de irradiancia"),
            html.Span("05", className="num"),
        ]),
        dcc.RadioItems(
            id="src-irr", className="seg",
            options=[
                {"label": "Cielo claro", "value": "clearsky"},
                {"label": "TMY real · PVGIS", "value": "tmy"},
            ],
            value="clearsky",
        ),
        html.Div(id="src-irr-hint", className="hint",
                 style={"marginTop": "6px"},
                 children="Modelo de cielo despejado (optimista, determinista)."),
    ]),

    html.Button(id="btn-calc", className="calc-btn", n_clicks=0, children=[
        svg_img(_ICON_BOLT, 14, 14),
        html.Span("Calcular generación anual"),
        html.Span("⌘ ⏎", className="kbd"),
    ]),
])


# ───────────────────────── KPI cards ───────────────────────────────────────────
def kpi(card_id, label, icon_svg):
    return html.Div(className="kpi", children=[
        html.Div(className="kpi-head", children=[
            html.Div(label, className="kpi-label"),
            html.Div(className="kpi-icn", children=[
                svg_img(icon_svg, 14, 14),
            ]),
        ]),
        html.Div("—", id=card_id, className="kpi-value"),
        html.Div("", id=f"{card_id}-foot", className="kpi-foot"),
    ])


# ───────────────────────── Main / dashboard ────────────────────────────────────
main = html.Main(className="main", children=[
    html.Div(id="error-alert", className="alert hidden", children=[
        svg_img(_ICON_ALERT, 18, 18, className="icn"),
        html.Div(className="body", children=[
            html.Strong("Error de cálculo"),
            html.Span("", id="error-msg"),
        ]),
    ]),

    # ── Diagnóstico rápido (siempre visible, sin botón) ──
    html.Div(className="page-head", children=[
        html.Div(children=[
            html.H1("Diagnóstico rápido"),
            html.P("Cómo se comporta 1 panel en un día típico de cielo claro · "
                   "reacciona en vivo al mover inclinación y azimut.",
                   className="sub"),
        ]),
        html.Div(className="meta", children=[
            dcc.RadioItems(
                id="dia-tipico-sel", className="seg",
                options=[
                    {"label": "Equinoccio", "value": "2026-03-21"},
                    {"label": "Verano", "value": "2026-06-21"},
                    {"label": "Invierno", "value": "2026-12-21"},
                ],
                value=DIA_TIPICO_DEFAULT, inline=True,
            ),
        ]),
    ]),
    html.Div(className="grid-12", children=[
        html.Div(className="card col-7", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Irradiancia del día · GHI / DNI / DHI / POA",
                            className="card-title"),
                    html.P("W/m² sobre el plano del panel para el día seleccionado",
                           className="card-sub"),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("graph-dia-irr"),
                dcc.Graph(id="graph-dia-irr", figure=empty_fig("Calculando…"),
                          config={"displayModeBar": False},
                          style={"height": "280px", "width": "100%"}),
            ]),
        ]),
        html.Div(className="card col-5", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Potencia de 1 panel", className="card-title"),
                    html.P("Potencia óptica en cielo claro (sin pérdidas ni "
                           "recorte de inversor). Puede superar los Wp nominales "
                           "cuando la POA > 1000 W/m².", className="card-sub"),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("graph-dia-pot"),
                dcc.Graph(id="graph-dia-pot", figure=empty_fig("Calculando…"),
                          config={"displayModeBar": False},
                          style={"height": "280px", "width": "100%"}),
            ]),
        ]),
    ]),

    html.Div(className="page-head", style={"marginTop": "8px"}, children=[
        html.Div(children=[
            html.H1("Resumen anual"),
            html.P("Ejecuta el cálculo para ver los resultados.",
                   className="sub", id="page-sub"),
        ]),
        html.Div(className="meta", id="page-meta", children=[
            "MODELO JENSEN",
        ]),
    ]),

    # KPIs
    html.Div(className="kpis", children=[
        kpi("kpi-energia", "Energía anual", _ICON_ENERGY),
        kpi("kpi-pico", "Potencia pico", _ICON_PEAK),
        kpi("kpi-cf", "Factor de capacidad", _ICON_CF),
        kpi("kpi-mes", "Mes pico", _ICON_SUN),
    ]),

    # Charts grid
    html.Div(className="grid-12", children=[
        # Daily
        html.Div(className="card col-12", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Generación diaria · año completo",
                            className="card-title"),
                    html.P("kWh/día estimados a partir de POA · Jensen + clear-sky/ineichen",
                           className="card-sub"),
                ]),
                html.Div(className="card-actions", children=[
                    html.Div(className="legend", children=[
                        html.Span([
                            html.Span(className="swatch",
                                      style={"background": ACCENT}),
                            "Generación",
                        ]),
                    ]),
                    html.Button(id="btn-download", n_clicks=0,
                                className="download-btn",
                                children="↓ CSV 15 min"),
                ]),
            ]),
            html.Div(className="chart-wrap tall", children=[
                chart_dl_btn("graph-timeseries"),
                dcc.Loading(
                    dcc.Graph(
                        id="graph-timeseries", figure=empty_fig(),
                        config={
                            "scrollZoom": False,
                            "displayModeBar": True,
                            "doubleClick": "reset+autosize",
                            "modeBarButtonsToRemove": [
                                "pan2d", "lasso2d", "select2d", "autoScale2d",
                            ],
                            "toImageButtonOptions": {"format": "png", "scale": 2},
                        },
                        style={"height": "300px", "width": "100%"},
                    ),
                    color=ACCENT, type="circle",
                ),
            ]),
            html.Div(className="ministats", children=[
                html.Div(children=[
                    html.Div("Día pico", className="ms-lbl"),
                    html.Div("—", id="ms-peak", className="ms-val"),
                ]),
                html.Div(children=[
                    html.Div("Día mínimo", className="ms-lbl"),
                    html.Div("—", id="ms-min", className="ms-val"),
                ]),
                html.Div(children=[
                    html.Div("Promedio diario", className="ms-lbl"),
                    html.Div("—", id="ms-avg", className="ms-val"),
                ]),
            ]),
        ]),

        # Monthly
        html.Div(className="card col-5 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Producción mensual", className="card-title"),
                    html.P("Acumulado por mes · 12 meses",
                           className="card-sub"),
                ]),
                html.Div(className="legend", children=[
                    html.Span([
                        html.Span(className="swatch",
                                  style={"background": ACCENT}),
                        "kWh",
                    ]),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("graph-monthly"),
                dcc.Graph(id="graph-monthly", figure=empty_fig(),
                          config={"displayModeBar": False},
                          style={"height": "260px", "width": "100%"}),
            ]),
        ]),

        # Irradiance
        html.Div(className="card col-7 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Irradiancia · GHI vs POA",
                            className="card-title"),
                    html.P("W/m² sobre el rango seleccionado",
                           className="card-sub"),
                ]),
                html.Div(className="legend-hint",
                         children="Clic en la leyenda para mostrar/ocultar · doble clic para aislar"),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("graph-irradiance"),
                dcc.Graph(id="graph-irradiance",
                          figure=empty_fig("Ejecuta el cálculo primero"),
                          config={"displayModeBar": False,
                                  "doubleClick": "reset+autosize"},
                          style={"height": "260px", "width": "100%"}),
            ]),
            html.Div(className="range-stack", style={"display": "none"}, children=[
                html.Div(className="range-row", children=[
                    dcc.Input(id="dr-from", type="text",
                              value="2026-06-20",
                              placeholder="YYYY-MM-DD",
                              debounce=True),
                    dcc.Input(id="dr-to", type="text",
                              value="2026-06-26",
                              placeholder="YYYY-MM-DD",
                              debounce=True),
                ]),
                html.Div(className="range-row range-row--cmp", children=[
                    dcc.Input(id="dr-from-2", type="text",
                              value="2026-12-20",
                              placeholder="YYYY-MM-DD",
                              debounce=True),
                    dcc.Input(id="dr-to-2", type="text",
                              value="2026-12-26",
                              placeholder="YYYY-MM-DD",
                              debounce=True),
                ]),
            ]),
        ]),

        # 15-min energy — same date range as irradiance
        html.Div(className="card col-12 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Energía quinceminutal · resolución 15 min",
                            className="card-title"),
                    html.P(
                        "kWh por intervalo de 15 min — "
                        "rango compartido con la gráfica de irradiancia",
                        className="card-sub",
                    ),
                ]),
                html.Div(className="card-actions", children=[
                    html.Div(className="legend", children=[
                        html.Span([
                            html.Span(className="swatch",
                                      style={"background": ACCENT}),
                            "Energía (kWh / intervalo)",
                        ]),
                    ]),
                    # Mini stats below the title (populated by callback)
                    html.Div(id="e15-stats", className="e15-stats"),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("graph-energy-15min"),
                dcc.Loading(
                    dcc.Graph(
                        id="graph-energy-15min",
                        figure=empty_fig(
                            "Ejecuta el cálculo y selecciona un rango"),
                        config={"displayModeBar": False,
                                "doubleClick": "reset+autosize"},
                        style={"height": "260px", "width": "100%"},
                    ),
                    color=ACCENT, type="circle",
                ),
            ]),
        ]),

        # Descomposición de irradiancia (solo Modo Avanzado)
        html.Div(className="card col-12 row-gap-14 adv-only", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Descomposición de irradiancia",
                            className="card-title"),
                    html.P("GHI · DNI · DHI · POA (W/m²) — rango compartido con "
                           "la gráfica de irradiancia · elevación solar "
                           "superpuesta en GHI",
                           className="card-sub"),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("graph-decomp"),
                dcc.Graph(id="graph-decomp",
                          figure=empty_fig("Ejecuta el cálculo en Modo Avanzado"),
                          config={"displayModeBar": False},
                          style={"height": "560px", "width": "100%"}),
            ]),
        ]),

        # Cascada de pérdidas (solo Modo Avanzado)
        html.Div(className="card col-12 row-gap-14 adv-only", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Cascada de pérdidas del sistema",
                            className="card-title"),
                    html.P("De energía nominal (STC) a energía neta (kWh/año)",
                           className="card-sub"),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("graph-waterfall"),
                dcc.Graph(id="graph-waterfall",
                          figure=empty_fig("Ejecuta el cálculo en Modo Avanzado"),
                          config={"displayModeBar": False},
                          style={"height": "420px", "width": "100%"}),
            ]),
        ]),
    ]),

    html.Footer(className="app-footer", children=[
        html.Span("KARDASHEV-I · BUILD 0.2.0"),
        html.Span("JENSEN · CLEAR-SKY"),
    ]),
])


# ───────────────────────── Finance page ────────────────────────────────────────
def fin_kpi(card_id, label, icon_svg):
    return html.Div(className="kpi", children=[
        html.Div(className="kpi-head", children=[
            html.Div(label, className="kpi-label"),
            html.Div(className="kpi-icn", children=[svg_img(icon_svg, 14, 14)]),
        ]),
        html.Div("—", id=card_id, className="kpi-value"),
        html.Div("", id=f"{card_id}-foot", className="kpi-foot"),
    ])


finance_page = html.Main(className="main", children=[
    html.Div(id="fin-error-alert", className="alert hidden", children=[
        svg_img(_ICON_ALERT, 18, 18, className="icn"),
        html.Div(className="body", children=[
            html.Strong("Error en el análisis"),
            html.Span("", id="fin-error-msg"),
        ]),
    ]),

    html.Div(className="page-head", children=[
        html.Div(children=[
            html.H1("Análisis financiero & ROI"),
            html.P("Sube la demanda real y evalúa la inversión del sistema FV.",
                   className="sub"),
        ]),
        html.Div(className="meta", children=[
            "TARIFA CFE GDMTH · AUTOCONSUMO + BATERÍAS",
        ]),
    ]),

    # ── Configuración del análisis ──
    html.Div(className="card col-12", style={"marginBottom": "14px"}, children=[
        html.Div(className="card-head", children=[
            html.Div(className="card-titlewrap", children=[
                html.H3("Configuración del análisis", className="card-title"),
                html.P("Carga el perfil de demanda y ajusta los costos de inversión.",
                       className="card-sub"),
            ]),
        ]),
        html.Div(className="fin-config", children=[
            # ── Método de captura de demanda (mutuamente excluyente) ──
            html.Div(className="field", children=[
                html.Label("¿Cómo quieres capturar tu consumo?"),
                dcc.RadioItems(
                    id="demanda-metodo", className="radio-row",
                    options=[
                        {"label": " Recibo o kWh mensual", "value": "rapido"},
                        {"label": " Tabla de 12 meses", "value": "tabla"},
                        {"label": " Subir CSV de medición", "value": "csv"},
                    ],
                    value="rapido", inline=True,
                ),
                html.P("Elige un solo método: con CSV o tabla no necesitas el "
                       "dato rápido, y viceversa.", className="tarifa-desc"),
            ]),

            # ── Método A: CSV de medición real ──
            html.Div(id="wrap-demanda-csv", style={"display": "none"}, children=[
                dcc.Upload(
                    id="upload-demanda",
                    className="fin-upload",
                    children=html.Div([
                        svg_img(_ICON_ENERGY, 18, 18),
                        html.Div([
                            html.Strong("Arrastra o haz clic"),
                            html.Span(" para subir el CSV de demanda",
                                      className="fin-up-sub"),
                        ]),
                        html.Div(
                            "Columnas: Fecha_Hora · Energia_kWh · Energia_kVArh "
                            "(15 min, 2026)",
                            className="fin-up-hint"),
                    ]),
                    multiple=False,
                    accept=".csv",
                ),
                html.Div(id="fin-upload-status", className="fin-up-status"),
            ]),

            # ── Tarifa CFE (compartida por "rápido" y "tabla") ──
            html.Div(id="wrap-demanda-tarifa", children=[
                html.Div(className="fin-tarifa", children=[
                    html.Div(className="field", children=[
                        html.Label(["Tarifa CFE ",
                                    html.Span("", id="tarifa-fecha", className="hint")]),
                        dcc.Dropdown(
                            id="dd-tarifa", className="dd-tarifa",
                            options=tarifas_cfe.familias_dropdown(),
                            value=FAMILIA_DEFAULT, clearable=False,
                        ),
                    ]),
                    html.Div(id="wrap-subtarifa", className="field", children=[
                        html.Label(["Subtarifa doméstica ",
                                    html.Span("región", className="hint")]),
                        dcc.Dropdown(
                            id="dd-subtarifa", className="dd-tarifa",
                            options=tarifas_cfe.subtarifas_dropdown("domestica"),
                            value=SUBTARIFA_DEFAULT, clearable=False,
                        ),
                    ]),
                    html.P("", id="tarifa-desc", className="tarifa-desc"),
                ]),
            ]),

            # ── Método A (rápido): un solo dato mensual ──
            html.Div(id="wrap-demanda-rapido", children=[
                html.Div(className="fin-tarifa", children=[
                    html.Div(className="field", children=[
                        dcc.RadioItems(
                            id="consumo-modo", className="radio-row",
                            options=[
                                {"label": " kWh / mes", "value": "kwh"},
                                {"label": " Recibo MXN / mes", "value": "recibo"},
                            ],
                            value="recibo", inline=True,
                        ),
                    ]),
                    html.Div(className="field", children=[
                        html.Div(id="wrap-kwh", children=[
                            html.Label(["Consumo mensual ",
                                        html.Span("kWh/mes", className="hint")]),
                            dcc.Input(id="inp-kwh-mes", type="number",
                                      value=KWH_MES_DEFAULT, step="any", min=0.1,
                                      className="input", debounce=True),
                        ]),
                        html.Div(id="wrap-recibo", style={"display": "none"}, children=[
                            html.Label(["Recibo mensual ",
                                        html.Span("MXN/mes", className="hint")]),
                            dcc.Input(id="inp-recibo-mes", type="number",
                                      value=RECIBO_MES_DEFAULT, step="any", min=1,
                                      className="input", debounce=True),
                        ]),
                    ]),
                    html.Div(id="consumo-status", className="consumo-status"),
                ]),
            ]),

            # ── Método B (tabla): 12 meses del recibo, kWh o $ ──
            html.Div(id="wrap-demanda-tabla", style={"display": "none"}, children=[
                html.Div(className="fin-tarifa", children=[
                    html.Div(className="field", children=[
                        html.Label("Captura cada mes en:"),
                        dcc.RadioItems(
                            id="tabla-unidad", className="radio-row",
                            options=[
                                {"label": " kWh / mes", "value": "kwh"},
                                {"label": " $ / mes (recibo)", "value": "dinero"},
                            ],
                            value="kwh", inline=True,
                        ),
                    ]),
                    dash_table.DataTable(
                        id="tabla-demanda-12m",
                        columns=[
                            {"name": "Mes", "id": "mes", "editable": False},
                            {"name": "kWh / mes", "id": "valor", "type": "numeric",
                             "editable": True},
                        ],
                        data=[{"mes": MESES_ES_SHORT[i], "valor": KWH_MES_DEFAULT}
                              for i in range(12)],
                        editable=True,
                        cell_selectable=True,
                        style_as_list_view=True,
                        style_table={"overflowX": "auto", "marginTop": "4px"},
                        style_cell={
                            "backgroundColor": "rgba(255,255,255,.02)",
                            "color": "#e6e6e6",
                            "border": "1px solid rgba(255,255,255,.08)",
                            "fontFamily": "var(--mono)", "fontSize": "12.5px",
                            "padding": "7px 12px", "textAlign": "left",
                            "height": "34px",
                        },
                        # La columna editable se distingue con fondo tintado y un
                        # candado visual; el mes va atenuado y no es editable.
                        style_cell_conditional=[
                            {"if": {"column_id": "mes"},
                             "width": "42%", "color": "#9aa0a6",
                             "textTransform": "uppercase", "fontSize": "11px"},
                            {"if": {"column_id": "valor"},
                             "width": "58%", "color": "#ffffff",
                             "backgroundColor": "rgba(90,150,255,.08)"},
                        ],
                        # Celda activa/seleccionada: alto contraste para que SIEMPRE
                        # se lea lo que se escribe (antes quedaba blanca sobre blanco).
                        style_data_conditional=[
                            {"if": {"state": "active"},
                             "backgroundColor": "rgba(90,150,255,.28)",
                             "border": "1px solid #5a96ff",
                             "color": "#ffffff"},
                            {"if": {"state": "selected"},
                             "backgroundColor": "rgba(90,150,255,.28)",
                             "border": "1px solid #5a96ff",
                             "color": "#ffffff"},
                        ],
                        style_header={
                            "backgroundColor": "rgba(255,255,255,.04)",
                            "color": "#9aa0a6", "fontWeight": "500",
                            "textTransform": "uppercase", "fontSize": "10.5px",
                            "letterSpacing": ".06em",
                        },
                        # El <input> de edición hereda el tema oscuro: texto claro,
                        # fondo tintado, alineado a la izquierda (no se va al borde).
                        css=[
                            {"selector": "td.dash-cell input.dash-cell-value",
                             "rule": ("color:#ffffff !important;"
                                      "background:rgba(90,150,255,.30) !important;"
                                      "text-align:left !important;"
                                      "font-family:var(--mono) !important;"
                                      "caret-color:#7aa2ff !important;"
                                      "padding:0 !important;")},
                            {"selector": ".dash-spreadsheet-inner tr:hover td",
                             "rule": ("background-color:rgba(90,150,255,.16) "
                                      "!important; color:#ffffff !important;")},
                            {"selector": ".dash-spreadsheet-inner tr:hover td "
                                         ".dash-cell-value",
                             "rule": "color:#ffffff !important;"},
                        ],
                    ),
                    html.P("Haz clic en la columna de la derecha y escribe el "
                           "consumo de cada mes.", className="tarifa-desc"),
                    html.Div(id="tabla-status", className="consumo-status"),
                ]),
            ]),

            # ── Modo Simple: resiliencia con lenguaje humano ──
            html.Div(className="simple-only", children=[
                html.Div(className="fin-tarifa", children=[
                    html.Div(className="field", children=[
                        html.Label("¿Tienes apagones?"),
                        dcc.RadioItems(
                            id="apagones-si-no", className="radio-row",
                            options=[
                                {"label": " No", "value": "no"},
                                {"label": " Sí", "value": "si"},
                            ],
                            value="no", inline=True,
                        ),
                    ]),
                    html.Div(id="wrap-apagon-critico", style={"display": "none"},
                             children=[
                        html.Div(className="field", children=[
                            html.Label(["¿Cuánto duró tu apagón más crítico? ",
                                        html.Span("h", className="hint")]),
                            dcc.Input(id="inp-apagon-critico", type="number",
                                      value=2, step=0.5, min=0,
                                      className="input", debounce=True),
                            html.P("Dimensionamos el almacenamiento para sostener "
                                   "tu carga durante un evento de esa duración.",
                                   className="tarifa-desc"),
                        ]),
                    ]),
                ]),
            ]),

            # Costo de panel aplica en ambos modos; el costo de pila y los
            # parámetros finos de apagón se reservan al Modo Avanzado.
            html.Div(className="fin-inputs", children=[
                html.Div(className="field", children=[
                    html.Label(["Costo panel ", html.Span("MXN/m²", className="hint")]),
                    dcc.Input(id="inp-costo-panel", type="number",
                              value=COSTO_PANEL_M2_DEFAULT, step=50, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field adv-only", children=[
                    html.Label(["Costo pila ", html.Span("MXN/100kWh", className="hint")]),
                    dcc.Input(id="inp-costo-pila", type="number",
                              value=COSTO_PILA_DEFAULT, step=10000, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field adv-only", children=[
                    html.Label(["Núm. apagones ", html.Span("/año", className="hint")]),
                    dcc.Input(id="inp-num-apagones", type="number",
                              value=NUM_APAGONES_DEFAULT, step=1, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field adv-only", children=[
                    html.Label(["Duración apagón ", html.Span("h", className="hint")]),
                    dcc.Input(id="inp-dur-apagon", type="number",
                              value=DUR_APAGON_DEFAULT, step=0.5, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field adv-only", children=[
                    html.Label(["Respaldo deseado ", html.Span("kWh", className="hint")]),
                    dcc.Input(id="inp-cap-respaldo", type="number",
                              value=CAP_RESPALDO_DEFAULT, step=50, min=0,
                              className="input", debounce=True),
                ]),
            ]),

            # ── Tipo de batería (vida útil por ciclos) · Modo Avanzado ──
            html.Div(className="field adv-only", children=[
                html.Label([
                    "Tipo de batería ",
                    html.Span("ⓘ valores estándar", className="hint",
                              title=bateria_specs.tooltip_text()),
                ]),
                dcc.Dropdown(
                    id="dd-bateria", className="dd-tarifa",
                    options=bateria_specs.opciones_dropdown(),
                    value=bateria_specs.BATERIA_DEFAULT, clearable=False,
                ),
                html.P("", id="bateria-rango", className="tarifa-desc"),
            ]),

            # ── Tarifa horaria manual + finanzas avanzadas (solo Modo Avanzado) ──
            html.Div(className="adv-only", children=[
                # Costos por horario: solo tienen sentido en la tarifa horaria
                # GDMTH; se ocultan para doméstica (bloques) y GDMTO (plana).
                html.Div(id="wrap-tarifa-horaria", children=[
                    html.Div(className="fin-divider",
                             children="tarifa CFE horaria (GDMTH)"),
                    html.Div(className="info-box info-box--sm", children=[
                        "Precios por horario y cargos por demanda (kW) de la "
                        "tarifa GDMTH. Solo aplican a GDMTH: las domésticas se "
                        "cobran por bloques y la GDMTO con energía plana, por "
                        "eso estos campos no se muestran para ellas.",
                    ]),
                    html.Div(className="fin-inputs", children=[
                        html.Div(className="field", children=[
                            html.Label(["Precio Base ",
                                        html.Span("MXN/kWh", className="hint")]),
                            dcc.Input(id="inp-precio-base", type="number",
                                      value=PRECIO_BASE_DEFAULT, step="any", min=0,
                                      className="input", debounce=True),
                        ]),
                        html.Div(className="field", children=[
                            html.Label(["Precio Intermedio ",
                                        html.Span("MXN/kWh", className="hint")]),
                            dcc.Input(id="inp-precio-int", type="number",
                                      value=PRECIO_INT_DEFAULT, step="any", min=0,
                                      className="input", debounce=True),
                        ]),
                        html.Div(className="field", children=[
                            html.Label(["Precio Punta ",
                                        html.Span("MXN/kWh", className="hint")]),
                            dcc.Input(id="inp-precio-punta", type="number",
                                      value=PRECIO_PUNTA_DEFAULT, step="any", min=0,
                                      className="input", debounce=True),
                        ]),
                        html.Div(className="field", children=[
                            html.Label(["Cargo capacidad ",
                                        html.Span("MXN/kW", className="hint")]),
                            dcc.Input(id="inp-cargo-cap", type="number",
                                      value=CARGO_CAP_DEFAULT, step="any", min=0,
                                      className="input", debounce=True),
                        ]),
                        html.Div(className="field", children=[
                            html.Label(["Cargo distribución ",
                                        html.Span("MXN/kW", className="hint")]),
                            dcc.Input(id="inp-cargo-dist", type="number",
                                      value=CARGO_DIST_DEFAULT, step="any", min=0,
                                      className="input", debounce=True),
                        ]),
                    ]),
                ]),
                # Supuestos financieros: aplican a cualquier tarifa.
                html.Div(className="fin-divider",
                         children="supuestos financieros"),
                html.Div(className="info-box info-box--sm", children=[
                    "El VPN se calcula como una anualidad creciente: el ahorro "
                    "sube con la inflación y se descuenta a la tasa indicada a lo "
                    "largo de los años de proyección que definas (por defecto 10).",
                ]),
                html.Div(className="fin-inputs", children=[
                    html.Div(className="field", children=[
                        html.Label(["Inflación energía ",
                                    html.Span("%/año", className="hint")]),
                        dcc.Input(id="inp-inflacion", type="number",
                                  value=INFLACION_DEFAULT, step="any",
                                  className="input", debounce=True),
                    ]),
                    html.Div(className="field", children=[
                        html.Label(["Tasa de descuento ",
                                    html.Span("%/año", className="hint")]),
                        dcc.Input(id="inp-descuento", type="number",
                                  value=DESCUENTO_DEFAULT, step="any",
                                  className="input", debounce=True),
                    ]),
                    html.Div(className="field", children=[
                        html.Label(["Años de proyección ",
                                    html.Span("años", className="hint")]),
                        dcc.Input(id="inp-horizonte", type="number",
                                  value=HORIZONTE_ANIOS, step=1, min=1, max=40,
                                  className="input", debounce=True),
                    ]),
                ]),
            ]),

            # ── Capa opcional: cotización realista (solo Modo Avanzado) ──
            html.Div(className="cot-block adv-only", children=[
                html.Div(className="fin-divider",
                         children="cotización realista (opcional)"),
                html.Div(className="field", children=[
                    dcc.Checklist(
                        id="chk-cotizacion", className="radio-row",
                        options=[{
                            "label": " Incluir cotización realista "
                                     "(pilas, instalación e interrupciones)",
                            "value": "on"}],
                        value=["on"],  # preset demo: cotización activa
                    ),
                    html.P("Reemplaza la estimación de catálogo: usa el costo "
                           "real del sistema (llave en mano) más el valor de las "
                           "interrupciones evitadas. Al activarla, las tarjetas "
                           "ROI · Payback · VPN · Ahorro reflejan esta cotización.",
                           className="tarifa-desc"),
                ]),
                html.Div(id="wrap-cotizacion", style={"display": "none"}, children=[
                    # Origen del costo: estimado por $/kWh+BOS o costo total directo.
                    html.Div(className="field", children=[
                        html.Label("¿Cómo capturas el costo del sistema?"),
                        dcc.RadioItems(
                            id="cot-modo", className="radio-row",
                            options=[
                                {"label": " Estimar ($/kWh + instalación)",
                                 "value": "desglose"},
                                {"label": " Costo total del proyecto",
                                 "value": "total"},
                            ],
                            value="total", inline=True,  # preset demo: costo total directo
                        ),
                    ]),
                    # A) Estimación por $/kWh + BOS.
                    html.Div(id="wrap-cot-desglose", className="fin-inputs", children=[
                        html.Div(className="field", children=[
                            html.Label(["Costo BESS instalado ",
                                        html.Span("MXN/kWh", className="hint")]),
                            dcc.Input(id="inp-costo-kwh-bess", type="number",
                                      value=COSTO_KWH_BESS_DEFAULT, step=500, min=0,
                                      className="input", debounce=True),
                        ]),
                        html.Div(className="field", children=[
                            html.Label(["Instalación / BOS ",
                                        html.Span("%", className="hint")]),
                            dcc.Input(id="inp-bos-pct", type="number",
                                      value=BOS_PCT_DEFAULT, step=5, min=0,
                                      className="input", debounce=True),
                        ]),
                    ]),
                    # B) Costo total directo (de una cotización del proveedor).
                    html.Div(id="wrap-cot-total", style={"display": "none"},
                             className="fin-inputs", children=[
                        html.Div(className="field", children=[
                            html.Label(["Costo total del proyecto ",
                                        html.Span("MXN", className="hint")]),
                            dcc.Input(id="inp-costo-total", type="number",
                                      value=COSTO_TOTAL_DEFAULT, step=10000, min=0,
                                      className="input", debounce=True),
                        ]),
                    ]),
                    html.P("«Estimar» calcula el CapEx desde la capacidad necesaria "
                           "(batería+inversor+instalación) más el % BOS. «Costo "
                           "total» usa directamente el monto de tu cotización.",
                           className="tarifa-desc"),
                    # Interrupciones (pérdidas evitadas) — reutiliza el número de
                    # apagones y la duración capturados arriba (mismos eventos que
                    # dimensionan la batería), para no pedir lo mismo dos veces.
                    # Aquí solo se añade el costo monetario de cada hora caída.
                    html.Div(className="fin-inputs", children=[
                        html.Div(className="field", children=[
                            html.Label(["Costo inactividad ",
                                        html.Span("MXN/h", className="hint")]),
                            dcc.Input(id="inp-cot-costo-hora", type="number",
                                      value=COT_COSTO_HORA_DEFAULT, step=500, min=0,
                                      className="input", debounce=True),
                        ]),
                    ]),
                    html.P("Las pérdidas evitadas usan el «Núm. apagones» y la "
                           "«Duración apagón» que definiste arriba (los mismos "
                           "eventos que dimensionan la batería) multiplicados por "
                           "este costo por hora de inactividad.",
                           className="tarifa-desc"),
                ]),
            ]),

            html.Button(id="btn-fin-run", className="calc-btn", n_clicks=0, children=[
                svg_img(_ICON_BOLT, 14, 14),
                html.Span("Ejecutar análisis"),
            ]),
        ]),
    ]),

    # ── KPIs ──
    html.Div(className="kpis", style={"gridTemplateColumns": "repeat(5,1fr)"}, children=[
        fin_kpi("kpi-roi", "ROI (horizonte)", _ICON_TREND),
        fin_kpi("kpi-payback", "Payback", _ICON_CLOCK),
        fin_kpi("kpi-npv", "VPN", _ICON_MONEY),
        fin_kpi("kpi-ahorro", "Ahorro anual CFE", _ICON_PIGGY),
        fin_kpi("kpi-curtail", "Curtailment", _ICON_WASTE),
    ]),

    # ── Charts ──
    html.Div(className="grid-12", children=[
        html.Div(className="card col-7", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Recibo CFE mensual · base vs sistema",
                            className="card-title"),
                    html.P("MXN por mes con y sin sistema fotovoltaico",
                           className="card-sub"),
                ]),
                html.Div(className="legend", children=[
                    html.Span([html.Span(className="swatch",
                                         style={"background": ACCENT_FILL_SOFT}),
                               "Sin sistema"]),
                    html.Span([html.Span(className="swatch",
                                         style={"background": ACCENT}),
                               "Con sistema"]),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("fin-graph-bill"),
                dcc.Graph(id="fin-graph-bill", figure=empty_fig("Ejecuta el análisis"),
                          config={"displayModeBar": False},
                          style={"height": "280px", "width": "100%"}),
            ]),
        ]),
        html.Div(className="card col-5", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Curtailment mensual", className="card-title"),
                    html.P("Energía solar desperdiciada (kWh)", className="card-sub"),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("fin-graph-curtail"),
                dcc.Graph(id="fin-graph-curtail", figure=empty_fig("Ejecuta el análisis"),
                          config={"displayModeBar": False},
                          style={"height": "280px", "width": "100%"}),
            ]),
        ]),
        html.Div(className="card col-12 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Energía mensual · demanda, red y solar",
                            className="card-title"),
                    html.P("Demanda total vs compra a la red vs generación solar",
                           className="card-sub"),
                ]),
                html.Div(className="legend", children=[
                    html.Span([html.Span(className="swatch",
                                         style={"background": INFO}), "Demanda"]),
                    html.Span([html.Span(className="swatch",
                                         style={"background": DANGER}), "Compra red"]),
                    html.Span([html.Span(className="swatch",
                                         style={"background": ACCENT}), "Solar"]),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("fin-graph-energy"),
                dcc.Graph(id="fin-graph-energy", figure=empty_fig("Ejecuta el análisis"),
                          config={"displayModeBar": False},
                          style={"height": "300px", "width": "100%"}),
            ]),
        ]),

        # Recuperación de la inversión (VPN acumulado año a año)
        html.Div(className="card col-12 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Recuperación de la inversión · VPN acumulado",
                            className="card-title"),
                    html.P("Flujo de caja descontado acumulado por año — cruza a "
                           "verde en el año de recuperación; el último valor es el VPN",
                           className="card-sub"),
                ]),
                html.Div(className="legend", children=[
                    html.Span([html.Span(className="swatch",
                                         style={"background": DANGER}),
                               "Sin recuperar"]),
                    html.Span([html.Span(className="swatch",
                                         style={"background": SUCCESS}),
                               "Recuperado"]),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                chart_dl_btn("fin-graph-payback"),
                dcc.Graph(id="fin-graph-payback",
                          figure=empty_fig("Ejecuta el análisis"),
                          config={"displayModeBar": False},
                          style={"height": "300px", "width": "100%"}),
            ]),
        ]),

        # Recomendaciones
        html.Div(className="card col-7 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Recomendaciones", className="card-title"),
                    html.P("Lectura automática de los KPIs del proyecto",
                           className="card-sub"),
                ]),
            ]),
            html.Div(id="fin-recommendations", className="rec-list", children=[
                html.Div("Ejecuta el análisis para ver recomendaciones.",
                         className="rec-empty"),
            ]),
        ]),

        # Resumen de inversión
        html.Div(className="card col-5 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Resumen de inversión", className="card-title"),
                    html.P("Desglose del CapEx y dimensionamiento", className="card-sub"),
                ]),
            ]),
            html.Div(id="fin-capex-summary", className="fin-summary", children=[
                html.Div("—", className="rec-empty"),
            ]),
        ]),

        # Tabla recibo con sistema
        html.Div(className="card col-12 row-gap-14", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Recibo mensual detallado · con sistema",
                            className="card-title"),
                    html.P("Demanda, factor de potencia y total CFE estimado por mes",
                           className="card-sub"),
                ]),
                html.Button(id="btn-download-recibo", className="mode-btn",
                            n_clicks=0, children=[html.Span("Descargar Excel")]),
            ]),
            html.Div(id="fin-table-sis", className="fin-table-wrap", children=[
                html.Div("Ejecuta el análisis para ver el detalle.",
                         className="rec-empty"),
            ]),
        ]),

        # ── Reporte imprimible ──
        html.Div(className="card col-12 row-gap-14", id="fin-report-card", children=[
            html.Div(className="card-head", children=[
                html.Div(className="card-titlewrap", children=[
                    html.H3("Reporte del proyecto", className="card-title"),
                    html.P("Resumen imprimible con gráficas · usa «Imprimir / PDF» "
                           "y elige «Guardar como PDF» en el navegador",
                           className="card-sub"),
                ]),
                html.Button(id="btn-report", className="mode-btn", n_clicks=0,
                            children=[html.Span("Imprimir / PDF")]),
            ]),
            html.Div(id="fin-report", children=[
                html.Div("Ejecuta el análisis para generar el reporte.",
                         className="rec-empty"),
            ]),
            # Gráficas más relevantes para el reporte (se imprimen con el texto).
            html.Div(className="report-charts", children=[
                html.Div(className="report-group-h", children="Generación solar"),
                html.Div(className="report-chart", children=[
                    html.H4("Generación mensual", className="report-h"),
                    dcc.Graph(id="report-graph-solar-monthly",
                              figure=empty_fig("Ejecuta el análisis"),
                              config={"displayModeBar": False},
                              style={"height": "260px", "width": "100%"}),
                ]),
                html.Div(className="report-chart", children=[
                    html.H4("Generación diaria (año)", className="report-h"),
                    dcc.Graph(id="report-graph-solar-daily",
                              figure=empty_fig("Ejecuta el análisis"),
                              config={"displayModeBar": False},
                              style={"height": "260px", "width": "100%"}),
                ]),
                html.Div(className="report-chart", children=[
                    html.H4("Irradiancia · GHI vs POA (días representativos)",
                            className="report-h"),
                    dcc.Graph(id="report-graph-solar-irr",
                              figure=empty_fig("Ejecuta el análisis"),
                              config={"displayModeBar": False},
                              style={"height": "260px", "width": "100%"}),
                ]),
                html.Div(className="report-group-h", children="Finanzas"),
                html.Div(className="report-chart", children=[
                    html.H4("Recibo CFE mensual · base vs sistema",
                            className="report-h"),
                    dcc.Graph(id="report-graph-bill",
                              figure=empty_fig("Ejecuta el análisis"),
                              config={"displayModeBar": False},
                              style={"height": "260px", "width": "100%"}),
                ]),
                html.Div(className="report-chart", children=[
                    html.H4("Energía mensual · demanda, red y solar",
                            className="report-h"),
                    dcc.Graph(id="report-graph-energy",
                              figure=empty_fig("Ejecuta el análisis"),
                              config={"displayModeBar": False},
                              style={"height": "260px", "width": "100%"}),
                ]),
                html.Div(className="report-chart", children=[
                    html.H4("Recuperación de la inversión · VPN acumulado",
                            className="report-h"),
                    dcc.Graph(id="report-graph-payback",
                              figure=empty_fig("Ejecuta el análisis"),
                              config={"displayModeBar": False},
                              style={"height": "260px", "width": "100%"}),
                ]),
            ]),
        ]),
    ]),

    html.Footer(className="app-footer", children=[
        html.Span("KARDASHEV-I · BUILD 0.2.0"),
        html.Span("CFE GDMTH · AUTOCONSUMO"),
    ]),
])


# ───────────────────────── Layout ──────────────────────────────────────────────
app.layout = html.Div([
    dcc.Location(id="url"),
    dcc.Store(id="store-df"),
    dcc.Store(id="store-meta"),
    dcc.Store(id="store-demand"),
    dcc.Store(id="store-losses"),
    dcc.Store(id="ui-mode", data="simple"),
    dcc.Store(id="dummy-landing"),
    dcc.Store(id="dummy-tilt"),
    dcc.Store(id="dummy-az"),
    dcc.Store(id="dummy-mode"),
    dcc.Store(id="dummy-print"),
    dcc.Store(id="store-recibo"),
    dcc.Download(id="download-csv"),
    dcc.Download(id="download-xlsx"),
    dcc.Download(id="download-graph-xls"),
    landing,
    html.Div(id="app", children=[
        topbar,
        html.Div(id="page-sim", children=[
            html.Div(className="shell", children=[sidebar, main]),
        ]),
        html.Div(id="page-fin", style={"display": "none"}, children=[finance_page]),
    ]),
])


# ───────────────────────── Clientside callbacks ────────────────────────────────

# Landing → App transition
clientside_callback(
    """
    function(n) {
        if (!n) return window.dash_clientside.no_update;
        const land = document.getElementById('landing');
        const app = document.getElementById('app');
        if (land) land.classList.add('hidden');
        if (app) app.classList.add('visible');
        // Resize charts and map after the fade-in
        setTimeout(function(){ window.dispatchEvent(new Event('resize')); }, 650);
        return '';
    }
    """,
    Output("dummy-landing", "data"),
    Input("enter-app", "n_clicks"),
    prevent_initial_call=True,
)

# Tilt: bidirectional sync slider ↔ numeric input
clientside_callback(
    """
    function(sliderVal, inputVal) {
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const fromSlider = ctx.triggered[0].prop_id.indexOf('sld-tilt') === 0;
        let v;
        if (fromSlider) {
            v = +sliderVal;
        } else {
            if (inputVal === null || inputVal === '' || isNaN(inputVal)) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }
            v = Math.max(0, Math.min(90, parseInt(inputVal)));
        }
        if (fromSlider) {
            return [window.dash_clientside.no_update,
                    (+inputVal === v) ? window.dash_clientside.no_update : v];
        } else {
            const sldOut = (+sliderVal === v) ? window.dash_clientside.no_update : v;
            const inpOut = (parseInt(inputVal) === v) ? window.dash_clientside.no_update : v;
            return [sldOut, inpOut];
        }
    }
    """,
    Output("sld-tilt", "value", allow_duplicate=True),
    Output("inp-tilt-num", "value", allow_duplicate=True),
    Input("sld-tilt", "value"),
    Input("inp-tilt-num", "value"),
    prevent_initial_call=True,
)

# Tilt: paint the slider gradient (runs on initial load too)
clientside_callback(
    """
    function(v) {
        const sld = document.getElementById('sld-tilt');
        if (sld && v !== null && v !== undefined) {
            const pct = ((+v - 0) / 90) * 100;
            sld.style.backgroundSize = pct + '% 100%';
        }
        return '';
    }
    """,
    Output("dummy-tilt", "data"),
    Input("sld-tilt", "value"),
)

# Azimuth: bidirectional sync
clientside_callback(
    """
    function(sliderVal, inputVal) {
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const fromSlider = ctx.triggered[0].prop_id.indexOf('sld-azimuth') === 0;
        let v;
        if (fromSlider) {
            v = +sliderVal;
        } else {
            if (inputVal === null || inputVal === '' || isNaN(inputVal)) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }
            v = Math.max(0, Math.min(360, parseInt(inputVal)));
        }
        if (fromSlider) {
            return [window.dash_clientside.no_update,
                    (+inputVal === v) ? window.dash_clientside.no_update : v];
        } else {
            const sldOut = (+sliderVal === v) ? window.dash_clientside.no_update : v;
            const inpOut = (parseInt(inputVal) === v) ? window.dash_clientside.no_update : v;
            return [sldOut, inpOut];
        }
    }
    """,
    Output("sld-azimuth", "value", allow_duplicate=True),
    Output("inp-az-num", "value", allow_duplicate=True),
    Input("sld-azimuth", "value"),
    Input("inp-az-num", "value"),
    prevent_initial_call=True,
)

# Azimuth: paint slider + rotate needle + update direction label
clientside_callback(
    """
    function(v) {
        if (v === null || v === undefined) return '';
        const n = +v;
        // Convención solar de UI: 0° = Sur, 90° = Este, 180° = Norte, 270° =
        // Oeste → ángulo geográfico (0° = Norte) = (180 − n). Para la AGUJA
        // usamos el valor sin módulo (geoRaw, continuo) para que la transición
        // no dé una vuelta entera; el módulo (geo) solo nombra la dirección.
        const geoRaw = 180 - n;
        const geo = ((geoRaw % 360) + 360) % 360;
        const sld = document.getElementById('sld-azimuth');
        if (sld) sld.style.backgroundSize = ((n / 360) * 100) + '% 100%';
        const needle = document.getElementById('needle');
        if (needle) needle.style.transform = 'translate(-50%,-100%) rotate(' + geoRaw + 'deg)';
        const dirs = [
            {min:337.5,max:360,name:'NORTE'},{min:0,max:22.5,name:'NORTE'},
            {min:22.5,max:67.5,name:'NORESTE'},
            {min:67.5,max:112.5,name:'ESTE'},
            {min:112.5,max:157.5,name:'SURESTE'},
            {min:157.5,max:202.5,name:'SUR'},
            {min:202.5,max:247.5,name:'SUROESTE'},
            {min:247.5,max:292.5,name:'OESTE'},
            {min:292.5,max:337.5,name:'NOROESTE'}
        ];
        let name = 'NORTE';
        for (let i = 0; i < dirs.length; i++) {
            const d = dirs[i];
            if (geo >= d.min && geo < d.max) { name = d.name; break; }
        }
        const suffix = (geo > 135 && geo < 225) ? ' · óptimo en hemisferio N'
                     : (geo > 315 || geo < 45) ? ' · óptimo en hemisferio S' : '';
        const dirEl = document.getElementById('val-azdir');
        if (dirEl) dirEl.textContent = name + suffix;
        return '';
    }
    """,
    Output("dummy-az", "data"),
    Input("sld-azimuth", "value"),
)


# Total area display (clientside, instant)
clientside_callback(
    """
    function(n, area) {
        const panels = Math.max(1, parseInt(n) || 1);
        const a = parseFloat(area) || 0;
        const total = (panels * a).toFixed(1);
        return 'Area total: ' + total + ' m²';
    }
    """,
    Output("total-area-display", "children"),
    Input("inp-n-panels", "value"),
    Input("inp-area", "value"),
)


# Especificación del panel (clientside, instant): Wp = area · η · 1000 W/m²
clientside_callback(
    """
    function(n, area, eff) {
        const panels = Math.max(1, parseInt(n) || 1);
        const a = parseFloat(area) || 0;
        const e = parseFloat(eff) || 0;
        const wp = Math.round(a * e * 1000);
        const kwp = (panels * a * e).toFixed(2);
        return 'Panel: ' + wp + ' Wp · ' + a.toFixed(1) + ' m² · η ' +
               Math.round(e * 100) + '% · ' + kwp + ' kWp';
    }
    """,
    Output("stc-power-display", "children"),
    Input("inp-n-panels", "value"),
    Input("inp-area", "value"),
    Input("inp-eff", "value"),
)


# Sync bidireccional Potencia nominal (Wp) ↔ eficiencia η, mediado por el área.
# Permite personalizar el panel por su potencia nominal en Modo Avanzado sin
# tocar el motor (que sigue usando η). Wp = η · área · 1000.
clientside_callback(
    """
    function(pnom, eff, area) {
        const ctx = window.dash_clientside.callback_context;
        const nu = window.dash_clientside.no_update;
        if (!ctx.triggered.length) return [nu, nu];
        const a = parseFloat(area) || 0;
        if (a <= 0) return [nu, nu];
        const trig = ctx.triggered[0].prop_id;
        if (trig.indexOf('inp-pnom') === 0) {
            const p = parseFloat(pnom);
            if (isNaN(p)) return [nu, nu];
            const e = Math.round((p / (a * 1000)) * 10000) / 10000;
            return [nu, (parseFloat(eff) === e) ? nu : e];
        } else {
            const e = parseFloat(eff);
            if (isNaN(e)) return [nu, nu];
            const p = Math.round(e * a * 1000);
            return [(parseFloat(pnom) === p) ? nu : p, nu];
        }
    }
    """,
    Output("inp-pnom", "value", allow_duplicate=True),
    Output("inp-eff", "value", allow_duplicate=True),
    Input("inp-pnom", "value"),
    Input("inp-eff", "value"),
    Input("inp-area", "value"),
    prevent_initial_call=True,
)


# Mode toggle: Simple ↔ Avanzado (alterna la clase del body)
clientside_callback(
    """
    function(n) {
        const adv = (n % 2) === 1;
        document.body.classList.toggle('mode-advanced', adv);
        setTimeout(function(){ window.dispatchEvent(new Event('resize')); }, 60);
        return [adv ? 'avanzado' : 'simple', adv ? 'Modo Simple' : 'Modo Avanzado'];
    }
    """,
    Output("ui-mode", "data"),
    Output("mode-label", "children"),
    Input("btn-mode", "n_clicks"),
    prevent_initial_call=True,
)

# Badge: marca si algún parámetro avanzado difiere de su valor por defecto
clientside_callback(
    """
    function(eff,pr,fp,tamb,gamma,noct,soil,wire,inv,degr,yr,iam,alt) {
        const d = {eff:0.22,pr:0.82,fp:1.0,tamb:25,gamma:-0.40,noct:45,
                   soil:3,wire:2,inv:97,degr:0.5,yr:0,alt:540};
        let diff = (+eff!==d.eff)||(+pr!==d.pr)||(+fp!==d.fp)||(+tamb!==d.tamb)||
                   (+gamma!==d.gamma)||(+noct!==d.noct)||(+soil!==d.soil)||
                   (+wire!==d.wire)||(+inv!==d.inv)||(+degr!==d.degr)||(+yr!==d.yr)||
                   (+alt!==d.alt);
        if (iam && iam.length) diff = true;
        return diff ? 'mode-badge' : 'mode-badge hidden';
    }
    """,
    Output("mode-badge", "className"),
    Input("inp-eff", "value"), Input("inp-pr", "value"), Input("inp-fp", "value"),
    Input("inp-tamb", "value"), Input("inp-gamma", "value"), Input("inp-noct", "value"),
    Input("inp-soiling", "value"), Input("inp-wiring", "value"),
    Input("inp-eta-inv", "value"), Input("inp-degr", "value"),
    Input("inp-year-idx", "value"), Input("chk-iam", "value"),
    Input("inp-alt", "value"),
)

# Consumo: mostrar el campo correcto (kWh/día vs recibo)
clientside_callback(
    """
    function(modo) {
        return [ modo === 'kwh' ? {display:'block'} : {display:'none'},
                 modo === 'recibo' ? {display:'block'} : {display:'none'} ];
    }
    """,
    Output("wrap-kwh", "style"),
    Output("wrap-recibo", "style"),
    Input("consumo-modo", "value"),
)


# Método de demanda: mostrar solo el bloque del método elegido (excluyentes).
# La tarifa se comparte entre "rápido" y "tabla" (no aplica al CSV).
clientside_callback(
    """
    function(metodo) {
        const show = function(v){ return v ? {display:'block'} : {display:'none'}; };
        return [ show(metodo === 'csv'),
                 show(metodo === 'rapido'),
                 show(metodo === 'tabla'),
                 show(metodo === 'rapido' || metodo === 'tabla') ];
    }
    """,
    Output("wrap-demanda-csv", "style"),
    Output("wrap-demanda-rapido", "style"),
    Output("wrap-demanda-tabla", "style"),
    Output("wrap-demanda-tarifa", "style"),
    Input("demanda-metodo", "value"),
)


# Subtarifa doméstica: visible solo cuando la familia es doméstica.
clientside_callback(
    """
    function(familia) {
        return familia === 'domestica'
            ? {display:'block'} : {display:'none'};
    }
    """,
    Output("wrap-subtarifa", "style"),
    Input("dd-tarifa", "value"),
)


# Tabla 12 meses: el encabezado de la columna editable refleja la unidad activa.
clientside_callback(
    """
    function(unidad) {
        var lbl = unidad === 'dinero' ? '$ / mes' : 'kWh / mes';
        return [ {name:'Mes', id:'mes', editable:false},
                 {name:lbl, id:'valor', type:'numeric', editable:true} ];
    }
    """,
    Output("tabla-demanda-12m", "columns"),
    Input("tabla-unidad", "value"),
)


# Cotización realista: revelar los campos solo si la casilla está marcada.
clientside_callback(
    """
    function(val) {
        var on = Array.isArray(val) && val.indexOf('on') !== -1;
        return on ? {display:'block'} : {display:'none'};
    }
    """,
    Output("wrap-cotizacion", "style"),
    Input("chk-cotizacion", "value"),
)


# Cotización: alternar entre estimación ($/kWh + BOS) y costo total directo.
clientside_callback(
    """
    function(modo) {
        var show = {}, hide = {display:'none'};
        return [ modo === 'total' ? hide : show,
                 modo === 'total' ? show : hide ];
    }
    """,
    Output("wrap-cot-desglose", "style"),
    Output("wrap-cot-total", "style"),
    Input("cot-modo", "value"),
)


# Botón de reporte: dispara la impresión del navegador (Guardar como PDF).
clientside_callback(
    """
    function(n) {
        if (n) {
            // Forzar a Plotly a recalcular tamaño antes de imprimir las gráficas.
            window.dispatchEvent(new Event('resize'));
            setTimeout(function(){ window.print(); }, 300);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("dummy-print", "data"),
    Input("btn-report", "n_clicks"),
    prevent_initial_call=True,
)


# Apagones (Modo Simple): revelar la duración crítica solo si responde "Sí"
clientside_callback(
    """
    function(resp) {
        return resp === 'si' ? {display:'block'} : {display:'none'};
    }
    """,
    Output("wrap-apagon-critico", "style"),
    Input("apagones-si-no", "value"),
)


# Fuente de irradiancia: actualizar la pista descriptiva
clientside_callback(
    """
    function(src) {
        if (src === 'tmy') {
            return 'Datos meteorológicos reales con nubosidad (PVGIS). ' +
                   'Requiere internet; si falla, usa cielo claro. ' +
                   'En Modo Avanzado usa temperatura ambiente real del TMY para la cascada de pérdidas.';
        }
        return 'Modelo de cielo despejado (optimista, determinista).';
    }
    """,
    Output("src-irr-hint", "children"),
    Input("src-irr", "value"),
)


# ───────────────────────── Server callbacks ────────────────────────────────────

@callback(
    Output("inp-tz", "value"),
    Input("inp-lat", "value"),
    Input("inp-lon", "value"),
)
def auto_timezone(lat, lon):
    if lat is None or lon is None:
        return TZ_DEFAULT
    tz = _tf.timezone_at(lat=lat, lng=lon)
    return tz if tz else TZ_DEFAULT


@callback(
    Output("map-marker", "center"),
    Input("inp-lat", "value"),
    Input("inp-lon", "value"),
)
def sync_marker(lat, lon):
    if lat is None or lon is None:
        return no_update
    return [lat, lon]


@callback(
    Output("land-meta-coords", "children"),
    Input("inp-lat", "value"),
    Input("inp-lon", "value"),
    Input("inp-tz", "value"),
)
def sync_landing_meta(lat, lon, tz):
    lat_s = f"{lat:.4f}" if isinstance(lat, (int, float)) else "—"
    lon_s = f"{lon:.4f}" if isinstance(lon, (int, float)) else "—"
    return f"LAT {lat_s} · LON {lon_s} · {tz or TZ_DEFAULT}"


@callback(
    Output("tarifa-desc", "children"),
    Output("tarifa-fecha", "children"),
    Input("dd-tarifa", "value"),
    Input("dd-subtarifa", "value"),
)
def tarifa_info(familia, subtarifa):
    tid = tarifas_cfe.tarifa_efectiva(familia, subtarifa)
    t = tarifas_cfe.TARIFAS.get(tid)
    if not t:
        return "", ""
    return t["descripcion"], t.get("actualizado", "")


@callback(
    Output("wrap-tarifa-horaria", "style"),
    Input("dd-tarifa", "value"),
)
def toggle_tarifa_horaria(familia):
    """Muestra los precios por horario solo para la tarifa horaria GDMTH."""
    if familia == "GDMTH":
        return {}
    return {"display": "none"}


@callback(
    Output("bateria-rango", "children"),
    Input("dd-bateria", "value"),
)
def bateria_info(bid):
    return bateria_specs.spec(bid)["rango"]


@callback(
    Output("inp-lat", "value"),
    Output("inp-lon", "value"),
    Output("inp-alt", "value"),
    Input("map", "clickData"),
    prevent_initial_call=True,
)
def map_click(click):
    """Clic en el mapa → fija lat/lon y consulta la altitud (Open-Elevation).

    Si la API de elevación falla, conserva el valor previo del campo de altitud.
    """
    if not click:
        return no_update, no_update, no_update
    latlng = click.get("latlng") or {}
    lat, lon = latlng.get("lat"), latlng.get("lng")
    if lat is None or lon is None:
        return no_update, no_update, no_update
    lat, lon = round(float(lat), 4), round(float(lon), 4)
    alt = fetch_altitude(lat, lon)
    return lat, lon, (alt if alt is not None else no_update)


@callback(
    Output("sld-tilt", "value", allow_duplicate=True),
    Output("inp-tilt-num", "value", allow_duplicate=True),
    Output("sld-azimuth", "value", allow_duplicate=True),
    Output("inp-az-num", "value", allow_duplicate=True),
    Input("inp-lat", "value"),
    Input("inp-lon", "value"),
    State("inp-alt", "value"),
    State("inp-tz", "value"),
    State("inp-area", "value"),
    State("inp-eff", "value"),
    State("src-irr", "value"),
    prevent_initial_call=True,
)
def auto_orient(lat, lon, alt, tz, area, eff, src):
    """Al cambiar la ubicación, fija la inclinación y el azimut óptimos por
    producción (barrido con el motor, no por reglas).

    - **Inclinación (tilt):** se optimiza con la **fuente seleccionada**. Con
      **TMY real** (``motor_tmy``) el tilt refleja el clima del sitio (peso
      estacional real); con **cielo claro**, el día típico (equinoccio). El tilt
      es robusto al sesgo de marca de tiempo del TMY porque la elevación solar
      es simétrica alrededor del mediodía. Si no hay red, TMY cae a cielo claro.
    - **Azimut:** se optimiza **siempre con cielo claro** (da el ecuador, estable
      y correcto). El azimut por TMY NO es fiable: el convenio de marca de tiempo
      de PVGIS (irradiancia promediada por hora vs. posición solar instantánea)
      introduce una asimetría Este/Oeste artificial que sesgaría el resultado.
    """
    try:
        if lat is None or lon is None:
            return (no_update,) * 4
        lat, lon = float(lat), float(lon)
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return (no_update,) * 4
        alt = float(alt) if alt is not None and alt >= 0 else ALT_DEFAULT
        eff = float(eff) if eff is not None and 0 < eff <= 1 else EFF_DEFAULT
        area = float(area) if area is not None and area > 0 else AREA_DEFAULT
        tz_motor = _tz_para_motor(tz or TZ_DEFAULT)

        # Fuente de optimización: TMY real si está seleccionado y hay datos.
        usar_tmy = (src == "tmy")
        prep = None
        if usar_tmy:
            try:
                prep = preparar_tmy(lat, lon, alt)
            except TMYUnavailable:
                usar_tmy = False   # sin red → cae a cielo claro

        # Geometría de cielo claro precalculada UNA vez (96 puntos): el barrido
        # solo repite la transposición por ángulo (barata), sin recomputar la
        # posición solar en cada candidato.
        prep_cs = preparar_dia(lat, lon, alt, tz_motor)

        def geo(az_ui):                       # UI (0°=Sur) → geográfico (0°=Norte)
            return (180.0 - az_ui) % 360.0

        def energia_cs(t, az_ui):    # cielo claro → AZIMUT estable
            return poa_anual(prep_cs, t, geo(az_ui))

        def energia(t, az_ui):       # fuente seleccionada (TMY/cielo claro) → TILT
            if usar_tmy:
                return poa_anual(prep, t, geo(az_ui))
            return poa_anual(prep_cs, t, geo(az_ui))

        # Punto de partida del azimut: hacia el ecuador (Sur en N, Norte en S).
        az_base = 0 if lat >= 0 else 180

        # 1) Tilt grueso (fuente seleccionada) mirando al ecuador.
        t_coarse = max(range(0, 81, 5), key=lambda t: energia(t, az_base))
        # 2) Azimut SIEMPRE con cielo claro: el azimut por TMY no es fiable por el
        #    convenio de marca de tiempo de PVGIS (irradiancia promediada por hora)
        #    que sesga Este/Oeste; el cielo claro da el ecuador, estable y correcto.
        az_cands = [(az_base + d) % 360 for d in range(-45, 46, 5)]
        best_az = max(az_cands, key=lambda a: energia_cs(t_coarse, a))
        # 3) Tilt fino (fuente seleccionada) al mejor azimut.
        lo, hi = max(0, t_coarse - 4), min(90, t_coarse + 4)
        best_tilt = max(range(lo, hi + 1), key=lambda t: energia(t, best_az))
        return best_tilt, best_tilt, best_az, best_az
    except Exception:
        return (no_update,) * 4


@callback(
    Output("store-demand", "data", allow_duplicate=True),
    Output("consumo-status", "children"),
    Output("consumo-status", "className"),
    Input("demanda-metodo", "value"),
    Input("consumo-modo", "value"),
    Input("inp-kwh-mes", "value"),
    Input("inp-recibo-mes", "value"),
    Input("dd-tarifa", "value"),
    Input("dd-subtarifa", "value"),
    prevent_initial_call=True,
)
def gen_demand_profile(metodo, modo, kwh_mes, recibo, familia, subtarifa):
    """Genera un perfil de demanda sintético (estimador rápido) → store-demand.

    Alimenta el mismo store que usa el análisis financiero, de modo que el
    usuario no experto no necesita subir un CSV. Solo aplica cuando el método
    de captura activo es "rapido"; con CSV o tabla, el perfil lo escriben sus
    propios callbacks y no debemos sobrescribirlo.
    """
    try:
        if metodo != "rapido":
            return no_update, no_update, no_update
        tarifa = tarifas_cfe.tarifa_efectiva(familia, subtarifa)
        if modo == "recibo":
            # Campo aún vacío: no es un error, solo esperamos un valor válido.
            if recibo is None or recibo == "":
                return no_update, no_update, no_update
            kwh_mes_val = tarifas_cfe.kwh_mes_desde_costo(recibo, tarifa)
        else:
            if kwh_mes is None or kwh_mes == "":
                return no_update, no_update, no_update
            kwh_mes_val = float(kwh_mes)
        kwh_dia = kwh_mes_val / 30.4
        df = perfil_demanda.generar_perfil(kwh_dia, "residencial")
        store = df.to_json(orient="split", date_format="iso")
        anual = perfil_demanda.consumo_anual_kwh(df)
        msg = (f"✓ Perfil generado · {kwh_mes_val:,.0f} kWh/mes · "
               f"{anual:,.0f} kWh/año")
        return store, msg, "consumo-status ok"
    except Exception as exc:
        return no_update, f"✕ {exc}", "consumo-status err"


@callback(
    Output("store-demand", "data", allow_duplicate=True),
    Output("tabla-status", "children"),
    Output("tabla-status", "className"),
    Input("demanda-metodo", "value"),
    Input("tabla-demanda-12m", "data"),
    Input("tabla-unidad", "value"),
    Input("dd-tarifa", "value"),
    Input("dd-subtarifa", "value"),
    prevent_initial_call=True,
)
def gen_demand_from_table(metodo, rows, unidad, familia, subtarifa):
    """Construye el perfil 15-min desde la tabla editable de 12 meses.

    Respeta el consumo de cada mes (estacionalidad). Si la tabla está en $/mes,
    invierte cada celda a kWh con la tarifa vigente del mes correspondiente.
    Solo aplica cuando el método de captura activo es "tabla".
    """
    try:
        if metodo != "tabla":
            return no_update, no_update, no_update
        valores = []
        for i in range(12):
            v = rows[i].get("valor") if rows and i < len(rows) else None
            try:
                valores.append(float(v))
            except (TypeError, ValueError):
                valores.append(0.0)
        tarifa = tarifas_cfe.tarifa_efectiva(familia, subtarifa)
        if unidad == "dinero":
            kwh_por_mes = [
                (tarifas_cfe.kwh_mes_desde_costo(c, tarifa, mes=i + 1)
                 if c and c > 0 else 0.0)
                for i, c in enumerate(valores)
            ]
        else:
            kwh_por_mes = valores
        df = perfil_demanda.generar_perfil_mensual(kwh_por_mes, "residencial")
        store = df.to_json(orient="split", date_format="iso")
        anual = perfil_demanda.consumo_anual_kwh(df)
        unit_lbl = "$/mes" if unidad == "dinero" else "kWh/mes"
        msg = f"✓ Perfil de 12 meses ({unit_lbl}) · {anual:,.0f} kWh/año"
        return store, msg, "consumo-status ok"
    except Exception as exc:
        return no_update, f"✕ {exc}", "consumo-status err"


@callback(
    Output("kpi-energia", "children"),
    Output("kpi-pico", "children"),
    Output("kpi-cf", "children"),
    Output("kpi-mes", "children"),
    Output("kpi-energia-foot", "children"),
    Output("kpi-pico-foot", "children"),
    Output("kpi-cf-foot", "children"),
    Output("kpi-mes-foot", "children"),
    Output("graph-timeseries", "figure"),
    Output("graph-monthly", "figure"),
    Output("ms-peak", "children"),
    Output("ms-min", "children"),
    Output("ms-avg", "children"),
    Output("store-df", "data"),
    Output("store-meta", "data"),
    Output("store-losses", "data"),
    Output("error-alert", "className"),
    Output("error-msg", "children"),
    Output("page-sub", "children"),
    Input("btn-calc", "n_clicks"),
    State("inp-lat", "value"),
    State("inp-lon", "value"),
    State("inp-tz", "value"),
    State("sld-tilt", "value"),
    State("sld-azimuth", "value"),
    State("inp-alt", "value"),
    State("inp-n-panels", "value"),
    State("inp-area", "value"),
    State("inp-eff", "value"),
    State("inp-pr", "value"),
    State("ui-mode", "data"),
    State("inp-tamb", "value"),
    State("inp-gamma", "value"),
    State("inp-noct", "value"),
    State("inp-soiling", "value"),
    State("inp-wiring", "value"),
    State("inp-eta-inv", "value"),
    State("inp-degr", "value"),
    State("inp-year-idx", "value"),
    State("chk-iam", "value"),
    State("src-irr", "value"),
    prevent_initial_call=True,
)
def run_calculation(_, lat, lon, tz, tilt, azimuth, alt, n_panels, area, eff, pr,
                    ui_mode, tamb, gamma, noct, soiling, wiring, eta_inv,
                    degr, year_idx, iam, src):
    blank = empty_fig()
    try:
        if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError("Lat/Lon fuera de rango.")
        if eff is None or pr is None or not (0 < eff <= 1) or not (0 < pr <= 1):
            raise ValueError("η y PR deben estar entre 0 y 1.")
        if area is None or area <= 0:
            raise ValueError("Área por panel debe ser mayor que 0.")
        if alt is None or alt < 0:
            raise ValueError("Altitud debe ser ≥ 0 msnm.")
        n = int(n_panels) if n_panels and n_panels >= 1 else 1
        total_area = n * float(area)

        # Azimut de UI (0°=Sur, 90°=Este) → geográfico (0°=Norte) = (180 − az).
        azimuth = (180.0 - float(azimuth if azimuth is not None else AZ_DEFAULT)) % 360.0

        modo = ui_mode or "simple"
        tz_motor = _tz_para_motor(tz or TZ_DEFAULT)
        perdidas = None
        fuente = src or "clearsky"
        usar_tmy = (fuente == "tmy")
        tmy_fallback = False

        # ── Fuente de irradiancia: TMY real (PVGIS) con fallback a cielo claro ──
        if usar_tmy:
            try:
                df = calculate_tmy(lat, lon, float(alt), tz_motor,
                                   float(tilt), float(azimuth),
                                   total_area, float(eff), float(pr))
                if modo == "avanzado":
                    df, perdidas = apply_advanced_losses(
                        df, total_area, float(eff),
                        gamma_pmax=(float(gamma) / 100.0) if gamma is not None else -0.0040,
                        noct=float(noct) if noct is not None else 45.0,
                        soiling=(float(soiling) / 100.0) if soiling is not None else 0.03,
                        wiring_loss=(float(wiring) / 100.0) if wiring is not None else 0.02,
                        eta_inv=(float(eta_inv) / 100.0) if eta_inv is not None else 0.97,
                        degradation=(float(degr) / 100.0) if degr is not None else 0.005,
                        year_index=int(year_idx) if year_idx else 0,
                        use_iam=bool(iam),
                    )
                store_cols = ["ghi", "poa_global", "potencia_generada",
                              "dni", "dhi", "solar_elevation"]
            except TMYUnavailable:
                usar_tmy = False
                tmy_fallback = True  # degradar con gracia a cielo claro

        if not usar_tmy:
            if modo == "avanzado":
                df, perdidas = calculate_advanced(
                    lat, lon, float(alt), tz_motor,
                    float(tilt), float(azimuth), total_area, float(eff), float(pr),
                    tamb=float(tamb) if tamb is not None else 25.0,
                    gamma_pmax=(float(gamma) / 100.0) if gamma is not None else -0.0040,
                    noct=float(noct) if noct is not None else 45.0,
                    soiling=(float(soiling) / 100.0) if soiling is not None else 0.03,
                    wiring_loss=(float(wiring) / 100.0) if wiring is not None else 0.02,
                    eta_inv=(float(eta_inv) / 100.0) if eta_inv is not None else 0.97,
                    degradation=(float(degr) / 100.0) if degr is not None else 0.005,
                    year_index=int(year_idx) if year_idx else 0,
                    use_iam=bool(iam),
                )
                store_cols = ["ghi", "poa_global", "potencia_generada",
                              "dni", "dhi", "solar_elevation"]
            else:
                df = calculate(lat, lon, float(alt), tz_motor,
                               float(tilt), float(azimuth),
                               total_area, float(eff), float(pr))
                store_cols = ["ghi", "poa_global", "potencia_generada"]

        energia_kwh = df["energia_generada_kWh"].sum()
        pico_w = df["potencia_generada"].max()
        cf_pct = (energia_kwh / (total_area * eff * 8760)) * 100
        df_monthly = df["energia_generada_kWh"].resample("ME").sum()
        daily = df["energia_generada_kWh"].resample("D").sum()
        peak_idx = int(df_monthly.values.argmax())
        peak_month_name = MESES_ES[df_monthly.index[peak_idx].month - 1]
        peak_month_kwh = df_monthly.iloc[peak_idx]

        kpi_energia = [f"{energia_kwh:,.0f}", html.Span("kWh", className="u")]
        kpi_pico = [f"{pico_w / 1000:.2f}", html.Span("kWp", className="u")]
        kpi_cf = [f"{cf_pct:.1f}", html.Span("%", className="u")]
        kpi_mes = peak_month_name

        foot_energia = f"{n} paneles · {total_area:.1f} m² total"
        foot_pico = f"{area:.1f} m²/panel · PR {pr}"
        foot_cf = "anualizado"
        foot_mes = f"{peak_month_kwh:,.0f} kWh"

        fig_ts = build_daily_fig(daily)
        fig_mo = build_monthly_fig(df_monthly, peak_idx)

        peak_day = daily.idxmax()
        min_day = daily.idxmin()
        ms_peak = [f"{daily.max():.1f}",
                   html.Span(f"kWh · {peak_day.strftime('%d %b').lower()}",
                             className="u")]
        ms_min = [f"{daily.min():.1f}",
                  html.Span(f"kWh · {min_day.strftime('%d %b').lower()}",
                            className="u")]
        ms_avg = [f"{daily.mean():.1f}",
                  html.Span("kWh/día", className="u")]

        df_store = df[store_cols].copy()
        df_store.index = df_store.index.tz_localize(None)
        store_json = df_store.to_json(orient="split", date_format="iso")
        losses_json = json.dumps(perdidas) if perdidas is not None else None

        modo_lbl = "avanzado · física detallada" if modo == "avanzado" else "simple"
        if usar_tmy:
            fuente_lbl = "TMY real (PVGIS)"
        elif tmy_fallback:
            fuente_lbl = "cielo claro (TMY no disponible — sin red)"
        else:
            fuente_lbl = "cielo claro (Ineichen)"
        page_sub = (f"{n} paneles · {total_area:.1f} m² · η {eff} · PR {pr} "
                    f"a {lat:.2f}°, {lon:.2f}° · modo {modo_lbl} · {fuente_lbl}.")

        store_meta = {"num_paneles": n, "area": float(area),
                      "total_area": total_area}

        return (kpi_energia, kpi_pico, kpi_cf, kpi_mes,
                foot_energia, foot_pico, foot_cf, foot_mes,
                fig_ts, fig_mo,
                ms_peak, ms_min, ms_avg,
                store_json, store_meta, losses_json, "alert hidden", "", page_sub)

    except Exception as exc:
        return ("—", "—", "—", "—",
                "", "", "", "",
                blank, blank,
                "—", "—", "—",
                None, None, None, "alert", str(exc),
                "Ejecuta el cálculo para ver los resultados.")


@callback(
    Output("graph-dia-irr", "figure"),
    Output("graph-dia-pot", "figure"),
    Input("dia-tipico-sel", "value"),
    Input("sld-tilt", "value"),
    Input("sld-azimuth", "value"),
    Input("inp-lat", "value"),
    Input("inp-lon", "value"),
    Input("inp-alt", "value"),
    Input("inp-eff", "value"),
    Input("inp-area", "value"),
    State("inp-tz", "value"),
    prevent_initial_call=False,
)
def update_dia_tipico(dia, tilt, azimuth, lat, lon, alt, eff, area, tz):
    """Diagnóstico instantáneo: 1 panel en un día típico (cielo claro).

    Reacciona en vivo a tilt/azimut y a la ubicación, sin correr la simulación
    anual. Cómputo de ~96 puntos (decenas de ms en caliente).
    """
    try:
        lat = float(lat) if lat is not None else LAT_DEFAULT
        lon = float(lon) if lon is not None else LON_DEFAULT
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError("Lat/Lon fuera de rango.")
        alt = float(alt) if alt is not None and alt >= 0 else ALT_DEFAULT
        eff = float(eff) if eff is not None and 0 < eff <= 1 else EFF_DEFAULT
        area = float(area) if area is not None and area > 0 else AREA_DEFAULT
        tilt = float(tilt) if tilt is not None else TILT_DEFAULT
        # Azimut de UI (0°=Sur, 90°=Este) → geográfico (0°=Norte) = (180 − az).
        azimuth = (180.0 - float(azimuth if azimuth is not None else AZ_DEFAULT)) % 360.0
        tz_motor = _tz_para_motor(tz or TZ_DEFAULT)
        df = dia_tipico(lat, lon, alt, tz_motor, tilt, azimuth, area, eff,
                        dia=dia or DIA_TIPICO_DEFAULT)
        return build_dia_tipico_irr_fig(df), build_dia_tipico_pot_fig(df)
    except Exception as exc:
        e = empty_fig(f"Día típico no disponible: {exc}")
        return e, e


@callback(
    Output("graph-irradiance", "figure"),
    Input("dr-from", "value"),
    Input("dr-to", "value"),
    Input("dr-from-2", "value"),
    Input("dr-to-2", "value"),
    Input("store-df", "data"),
    prevent_initial_call=True,
)
def update_irradiance(start, end, start2, end2, stored):
    if stored is None:
        return empty_fig("Ejecuta el cálculo primero")
    if not start or not end:
        return empty_fig("Selecciona un rango de fechas")
    try:
        df = pd.read_json(StringIO(stored), orient="split")
        df.index = pd.to_datetime(df.index)
        sample = df.loc[start:end]
    except Exception:
        return empty_fig("Rango de fechas inválido")
    if sample.empty:
        return empty_fig("Sin datos en el rango seleccionado")

    sample2 = None
    if start2 and end2:
        try:
            s2 = df.loc[start2:end2]
            if not s2.empty:
                sample2 = s2
        except Exception:
            pass

    return build_irradiance_fig(sample, sample2)


@callback(
    Output("graph-energy-15min", "figure"),
    Output("e15-stats", "children"),
    Input("dr-from", "value"),
    Input("dr-to", "value"),
    Input("store-df", "data"),
    prevent_initial_call=True,
)
def update_energy_15min(start, end, stored):
    empty_stats = ""
    if stored is None:
        return empty_fig("Ejecuta el cálculo primero"), empty_stats
    if not start or not end:
        return empty_fig("Selecciona un rango de fechas"), empty_stats
    try:
        df = pd.read_json(StringIO(stored), orient="split")
        df.index = pd.to_datetime(df.index)
        sample = df.loc[start:end]
    except Exception:
        return empty_fig("Rango de fechas inválido"), empty_stats
    if sample.empty:
        return empty_fig("Sin datos en el rango seleccionado"), empty_stats

    e = sample["potencia_generada"] * (15.0 / 60.0) / 1000.0
    total_kwh = e.sum()
    peak_kwh = e.max()
    peak_time = e.idxmax().strftime("%d %b %H:%M")
    n_days = max(1, (sample.index[-1] - sample.index[0]).days + 1)
    avg_daily = total_kwh / n_days

    stats = html.Div(className="e15-pill-row", children=[
        html.Span([html.Strong(f"{total_kwh:.2f}"), " kWh total"],
                  className="e15-pill"),
        html.Span([html.Strong(f"{peak_kwh:.4f}"), f" kWh pico · {peak_time}"],
                  className="e15-pill"),
        html.Span([html.Strong(f"{avg_daily:.2f}"), " kWh/día (rango)"],
                  className="e15-pill"),
    ])
    return build_energy_15min_fig(sample), stats


@callback(
    Output("graph-decomp", "figure"),
    Input("dr-from", "value"),
    Input("dr-to", "value"),
    Input("store-df", "data"),
    prevent_initial_call=True,
)
def update_decomp(start, end, stored):
    if not stored:
        return empty_fig("Ejecuta el cálculo en Modo Avanzado")
    try:
        df = pd.read_json(StringIO(stored), orient="split")
        df.index = pd.to_datetime(df.index)
    except Exception:
        return empty_fig("Sin datos")
    if "dni" not in df.columns:
        return empty_fig("Disponible solo en Modo Avanzado")
    if start and end:
        try:
            df = df.loc[start:end]
        except Exception:
            return empty_fig("Rango de fechas inválido")
    if df.empty:
        return empty_fig("Sin datos en el rango seleccionado")
    return build_decomp_fig(df)


@callback(
    Output("graph-waterfall", "figure"),
    Input("store-losses", "data"),
    prevent_initial_call=True,
)
def update_waterfall(stored):
    if not stored:
        return empty_fig("Ejecuta el cálculo en Modo Avanzado")
    try:
        p = json.loads(stored)
    except Exception:
        return empty_fig("Sin datos de pérdidas")
    return build_waterfall_fig(p)


@callback(
    Output("download-csv", "data"),
    Input("btn-download", "n_clicks"),
    State("store-df", "data"),
    State("inp-fp", "value"),
    prevent_initial_call=True,
)
def download_csv(_, stored, fp_val):
    if not stored:
        return no_update
    df = pd.read_json(StringIO(stored), orient="split")
    df.index = pd.to_datetime(df.index)

    fp = float(fp_val) if fp_val else 1.0
    fp = max(0.01, min(1.0, fp))

    # Active energy per 15-min interval: P(W) × (15 min / 60) / 1000
    e_kwh = (df["potencia_generada"] * (15.0 / 60.0) / 1000.0).round(6)

    # Reactive energy: Q = P × tan(φ), where cos(φ) = fp
    tan_phi = 0.0 if fp >= 1.0 else float(np.sqrt(1.0 - fp ** 2) / fp)
    e_kvarh = (e_kwh * tan_phi).round(6)

    df_out = pd.DataFrame({
        "Fecha_Hora": df.index.strftime("%Y-%m-%d %H:%M"),
        "Energia_kWh": e_kwh.values,
        "Energia_kVArh": e_kvarh.values,
    })
    return dcc.send_data_frame(df_out.to_csv, "kardashev_15min.csv", index=False)


@callback(
    Output("download-xlsx", "data"),
    Input("btn-download-recibo", "n_clicks"),
    State("store-recibo", "data"),
    prevent_initial_call=True,
)
def download_recibo_xlsx(_, stored):
    """Exporta el recibo mensual detallado (con sistema) a un archivo Excel."""
    if not stored:
        return no_update
    df = pd.read_json(StringIO(stored), orient="split")
    return dcc.send_data_frame(df.to_excel, "recibo_mensual_detallado.xlsx",
                               sheet_name="Recibo", index=False)


# Gráficas con exportación a Excel (su figura es la fuente de datos).
EXPORT_GRAPH_IDS = [
    "graph-dia-irr", "graph-dia-pot", "graph-timeseries", "graph-monthly",
    "graph-irradiance", "graph-energy-15min", "graph-decomp", "graph-waterfall",
    "fin-graph-bill", "fin-graph-curtail", "fin-graph-energy", "fin-graph-payback",
]


@callback(
    Output("download-graph-xls", "data"),
    Input({"type": "dl-graph", "index": ALL}, "n_clicks"),
    [State(g, "figure") for g in EXPORT_GRAPH_IDS],
    prevent_initial_call=True,
)
def export_graph_xls(n_clicks_list, *figures):
    """Exporta a Excel los datos de la gráfica cuyo botón se pulsó."""
    if not n_clicks_list or not any(n_clicks_list):
        return no_update
    trig = ctx.triggered_id
    gid = trig.get("index") if isinstance(trig, dict) else None
    if not gid:
        return no_update
    df = figure_to_df(dict(zip(EXPORT_GRAPH_IDS, figures)).get(gid))
    if df is None or df.empty:
        return no_update
    fname = gid.replace("graph-", "").replace("fin-", "fin_") + ".xlsx"
    return dcc.send_data_frame(df.to_excel, fname, sheet_name="Datos", index=False)


# ───────────────────────── Routing ─────────────────────────────────────────────
@callback(
    Output("page-sim", "style"),
    Output("page-fin", "style"),
    Output("nav-sim", "className"),
    Output("nav-fin", "className"),
    Input("url", "pathname"),
)
def route(pathname):
    is_fin = bool(pathname) and pathname.rstrip("/").endswith("finanzas")
    if is_fin:
        return ({"display": "none"}, {"display": "block"},
                "nav-link", "nav-link active")
    return ({"display": "block"}, {"display": "none"},
            "nav-link active", "nav-link")


# ───────────────────────── Finance: upload demand ──────────────────────────────
@callback(
    Output("store-demand", "data"),
    Output("fin-upload-status", "children"),
    Output("fin-upload-status", "className"),
    Input("upload-demanda", "contents"),
    State("upload-demanda", "filename"),
    prevent_initial_call=True,
)
def parse_demand(contents, filename):
    if not contents:
        return no_update, no_update, no_update
    try:
        _, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
        df = pd.read_csv(StringIO(decoded.decode("utf-8")),
                         index_col=0, parse_dates=True)
        faltantes = [c for c in ("Energia_kWh", "Energia_kVArh")
                     if c not in df.columns]
        if faltantes:
            raise ValueError(f"Faltan columnas: {', '.join(faltantes)}.")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("La primera columna debe ser la fecha/hora.")
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[["Energia_kWh", "Energia_kVArh"]]
        store = df.to_json(orient="split", date_format="iso")
        n = len(df)
        msg = f"✓ {filename} · {n:,} registros cargados"
        return store, msg, "fin-up-status ok"
    except Exception as exc:
        return None, f"✕ No se pudo leer el archivo: {exc}", "fin-up-status err"


# ───────────────────────── Finance: run analysis ───────────────────────────────
@callback(
    Output("kpi-roi", "children"),
    Output("kpi-payback", "children"),
    Output("kpi-npv", "children"),
    Output("kpi-ahorro", "children"),
    Output("kpi-curtail", "children"),
    Output("kpi-roi-foot", "children"),
    Output("kpi-payback-foot", "children"),
    Output("kpi-npv-foot", "children"),
    Output("kpi-ahorro-foot", "children"),
    Output("kpi-curtail-foot", "children"),
    Output("fin-graph-bill", "figure"),
    Output("fin-graph-curtail", "figure"),
    Output("fin-graph-energy", "figure"),
    Output("fin-graph-payback", "figure"),
    Output("fin-recommendations", "children"),
    Output("fin-capex-summary", "children"),
    Output("fin-table-sis", "children"),
    Output("fin-report", "children"),
    Output("report-graph-solar-monthly", "figure"),
    Output("report-graph-solar-daily", "figure"),
    Output("report-graph-solar-irr", "figure"),
    Output("report-graph-bill", "figure"),
    Output("report-graph-energy", "figure"),
    Output("report-graph-payback", "figure"),
    Output("store-recibo", "data"),
    Output("fin-error-alert", "className"),
    Output("fin-error-msg", "children"),
    Input("btn-fin-run", "n_clicks"),
    State("store-df", "data"),
    State("store-meta", "data"),
    State("store-demand", "data"),
    State("inp-costo-panel", "value"),
    State("inp-costo-pila", "value"),
    State("inp-num-apagones", "value"),
    State("inp-dur-apagon", "value"),
    State("inp-cap-respaldo", "value"),
    State("dd-bateria", "value"),
    State("apagones-si-no", "value"),
    State("inp-apagon-critico", "value"),
    State("ui-mode", "data"),
    State("inp-precio-base", "value"),
    State("inp-precio-int", "value"),
    State("inp-precio-punta", "value"),
    State("inp-cargo-cap", "value"),
    State("inp-cargo-dist", "value"),
    State("inp-inflacion", "value"),
    State("inp-descuento", "value"),
    State("inp-horizonte", "value"),
    State("chk-cotizacion", "value"),
    State("cot-modo", "value"),
    State("inp-costo-kwh-bess", "value"),
    State("inp-bos-pct", "value"),
    State("inp-costo-total", "value"),
    State("inp-cot-costo-hora", "value"),
    State("dd-tarifa", "value"),
    State("dd-subtarifa", "value"),
    prevent_initial_call=True,
)
def run_financial(_, store_df, store_meta, store_demand,
                  costo_panel, costo_pila, num_apagones, dur_apagon, cap_respaldo,
                  bateria, apagones_si_no, apagon_critico,
                  ui_mode, precio_base, precio_int, precio_punta,
                  cargo_cap, cargo_dist, inflacion, descuento, horizonte_val,
                  chk_cotizacion, cot_modo, costo_kwh_bess, bos_pct, costo_total,
                  cot_costo_hora, familia, subtarifa):
    blank = empty_fig()
    dash_vals = ["—"] * 5
    foots = [""] * 5
    empty_recs = [html.Div("Ejecuta el análisis.", className="rec-empty")]
    empty_summary = [html.Div("—", className="rec-empty")]
    empty_table = [html.Div("Sin datos.", className="rec-empty")]
    empty_report = [html.Div("Ejecuta el análisis para generar el reporte.",
                             className="rec-empty")]

    def err(msg):
        return (*dash_vals, *foots, blank, blank, blank, blank,
                empty_recs, empty_summary, empty_table, empty_report,
                blank, blank, blank, blank, blank, blank, None,
                "alert", msg)

    try:
        if not store_df or not store_meta:
            raise ValueError(
                "Primero corre el Simulador FV para calcular la generación solar.")
        if not store_demand:
            raise ValueError(
                "Sube un CSV de demanda o genera un perfil con el estimador.")

        df_solar = pd.read_json(StringIO(store_df), orient="split")
        df_solar.index = pd.to_datetime(df_solar.index)
        df_dem = pd.read_json(StringIO(store_demand), orient="split")
        df_dem.index = pd.to_datetime(df_dem.index)

        num_paneles = int(store_meta.get("num_paneles", 1))
        area = float(store_meta.get("area", 1.0))

        # Horizonte de proyección (años): configurable en Modo Avanzado; en
        # Simple usa el default. Afecta flujo de caja, VPN, ROI y reemplazos.
        horizonte = HORIZONTE_ANIOS
        if (ui_mode or "simple") == "avanzado" and horizonte_val:
            try:
                horizonte = max(1, min(40, int(float(horizonte_val))))
            except (TypeError, ValueError):
                horizonte = HORIZONTE_ANIOS

        # ── Resiliencia según el modo ──
        # Avanzado: el usuario controla nº de apagones, duración y respaldo.
        # Simple: pregunta humana ("¿tienes apagones?" + duración crítica) →
        #   un único evento de esa duración dimensiona el banco; sin apagones
        #   no se pide respaldo (autoconsumo directo, 0 pilas).
        if (ui_mode or "simple") == "avanzado":
            n_apagones = int(num_apagones or 0)
            dur_ap = float(dur_apagon or 1.0)
            cap_resp = float(cap_respaldo or 0)
        elif apagones_si_no == "si" and apagon_critico:
            n_apagones = 1
            dur_ap = float(apagon_critico)
            cap_resp = 0.0
        else:
            n_apagones = 0
            dur_ap = 1.0
            cap_resp = 0.0

        # En Modo Avanzado se aplican las tarifas e inflación personalizadas;
        # en Simple se usan los valores fijos del motor (None → defaults).
        if (ui_mode or "simple") == "avanzado":
            kw = dict(
                precio_base=precio_base, precio_intermedio=precio_int,
                precio_punta=precio_punta, cargo_capacidad=cargo_cap,
                cargo_distribucion=cargo_dist,
                tasa_inflacion=(float(inflacion) / 100.0) if inflacion is not None else None,
                tasa_descuento=(float(descuento) / 100.0) if descuento is not None else None,
            )
        else:
            kw = {}

        # Tarifa CFE elegida (familia + subtarifa doméstica): define cómo se
        # factura el recibo — bloques sin horarios para doméstica, plana para
        # GDMTO, horaria con demanda para GDMTH.
        tarifa_id = tarifas_cfe.tarifa_efectiva(familia, subtarifa)

        res = simular_financiero(
            df_solar=df_solar, df_demanda=df_dem,
            num_paneles=num_paneles, area=area,
            costo_panel_m2=float(costo_panel or 0),
            costo_pila=float(costo_pila or 0),
            cap_respaldo_max_kwh=cap_resp,
            num_apagones=n_apagones,
            duracion_horas_apagon=dur_ap,
            horizonte=horizonte,
            tarifa_id=tarifa_id,
            **kw,
        )

        # KPIs
        payback = res["payback_anios"]
        payback_txt = ("∞" if payback == float("inf")
                       else [f"{payback:.1f}", html.Span("años", className="u")])
        kpi_roi = [f"{res['roi_pct']:.0f}", html.Span("%", className="u")]
        kpi_npv = [f"${res['npv']/1000:,.0f}", html.Span("k MXN", className="u")]
        kpi_ahorro = [f"${res['ahorro_anual']/1000:,.0f}",
                      html.Span("k MXN/año", className="u")]
        kpi_curtail = [f"{res['pct_desperdicio']:.1f}", html.Span("%", className="u")]

        foot_roi = f"horizonte {horizonte} años"
        foot_payback = ("no se recupera" if payback == float("inf")
                        else "recuperación simple")
        foot_npv = "valor presente neto"
        foot_ahorro = f"${res['ahorro_anual']:,.0f} MXN"
        foot_curtail = f"{res['total_desperdiciada']:,.0f} kWh · ${res['dinero_tirado']:,.0f}"

        # Figures
        fig_bill = build_bill_compare_fig(res["df_recibo_sis"], res["df_recibo_base"])
        fig_curtail = build_curtail_fig(res["df_energia_mensual"])
        fig_energy = build_energy_month_fig(res["df_energia_mensual"])
        fig_payback = build_payback_fig(res["df_flujo"])

        recs = build_recommendations(res["recomendaciones"])

        adv = (ui_mode or "simple") == "avanzado"

        # Vida útil de la batería por ciclos (química elegida + throughput real
        # de descarga que reporta el motor).
        vida = bateria_specs.estimar_vida(
            bateria, res["sizing_diario_requerido"],
            res["descarga_total_kwh"], horizonte)

        # Almacenamiento como protagonista (capacidad necesaria, dato físico
        # siempre válido). El costo de pilas y el CapEx detallado se reservan al
        # Modo Avanzado / capa de cotización, para no mezclar física y precio.
        summary_rows = [
            _summ_row("Paneles", f"{num_paneles} uds · {num_paneles*area:.1f} m²"),
            _summ_row("Almacenamiento necesario",
                      f"{res['sizing_diario_requerido']:,.0f} kWh", strong=True),
            _summ_row("Pilas (referencia)", f"{res['cant_pilas']} uds"),
            _summ_row("Solar generada", f"{res['total_generada']:,.0f} kWh/año"),
        ]
        if adv:
            summary_rows += [
                _summ_row("Batería", vida["nombre"]),
                _summ_row("Ciclos equiv./año", f"{vida['ciclos_por_anio']:.0f}"),
                _summ_row("Vida útil estimada", _vida_str(vida)),
                _summ_row("Reemplazos (horizonte)", f"{vida['reemplazos']}"),
                _summ_row("Costo paneles (catálogo)",
                          f"${res['costo_total_paneles']:,.0f}"),
                _summ_row("Costo pilas (catálogo)",
                          f"${res['costo_total_pilas']:,.0f}"),
                _summ_row("CapEx estimado (catálogo)",
                          f"${res['capex']:,.0f}", strong=True),
            ]
        # ── Capa opcional: cotización realista (solo Modo Avanzado) ──
        cot_on = (adv and isinstance(chk_cotizacion, (list, tuple))
                  and "on" in chk_cotizacion)
        cot = None
        if cot_on:
            # Tasas del modelo de valor presente (mismas que el motor).
            infl = (float(inflacion) / 100.0 if inflacion is not None
                    else TASA_INFLACION_DEFAULT)
            desc = (float(descuento) / 100.0 if descuento is not None
                    else TASA_DESCUENTO_DEFAULT)
            # Origen del CapEx: estimado ($/kWh + BOS) o costo total directo.
            if cot_modo == "total":
                capex_real = float(costo_total or 0)
                costo_paneles = costo_bess = costo_bos = None
            else:
                capacidad_kwh = res["sizing_diario_requerido"]
                costo_bess = capacidad_kwh * float(costo_kwh_bess or 0)
                costo_paneles = res["costo_total_paneles"]
                equipo = costo_paneles + costo_bess
                capex_real = equipo * (1.0 + float(bos_pct or 0) / 100.0)
                costo_bos = capex_real - equipo
            # Reemplazos de batería dentro del horizonte → costo en valor presente
            # (cada reemplazo ocurre al cumplirse la vida útil estimada).
            costo_bateria_unit = (res["sizing_diario_requerido"]
                                  * float(costo_kwh_bess or 0))
            costo_reemplazos = 0.0
            for k in range(1, vida["reemplazos"] + 1):
                t_rep = k * vida["vida_anios"]
                if t_rep < horizonte:
                    costo_reemplazos += costo_bateria_unit / (1 + desc) ** t_rep
            capex_real += costo_reemplazos
            # Pérdidas evitadas por interrupciones (beneficio anual adicional).
            # Reutiliza los mismos apagones/duración que dimensionan la batería
            # (n_apagones · dur_ap), no parámetros duplicados.
            beneficio_int = (float(n_apagones or 0) * float(dur_ap or 0)
                             * float(cot_costo_hora or 0))
            ahorro_total = res["ahorro_anual"] + beneficio_int
            vp = ahorro_total * factor_vp_ahorros(infl, desc, horizonte)
            npv_real = vp - capex_real
            payback_real = (capex_real / ahorro_total
                            if ahorro_total > 0 else float("inf"))
            roi_real = (npv_real / capex_real * 100.0) if capex_real > 0 else 0.0
            cot = dict(
                modo=cot_modo, costo_paneles=costo_paneles, costo_bess=costo_bess,
                costo_bos=costo_bos, costo_reemplazos=costo_reemplazos,
                capex_real=capex_real, beneficio_int=beneficio_int,
                ahorro_total=ahorro_total, npv_real=npv_real,
                payback_real=payback_real, roi_real=roi_real,
            )
            # Con cotización activa, las tarjetas principales reflejan los KPIs
            # ajustados (CapEx real + pérdidas evitadas), para que cambiar estos
            # campos sí mueva ROI / Payback / VPN / Ahorro a la vista.
            kpi_roi = [f"{roi_real:.0f}", html.Span("%", className="u")]
            kpi_npv = [f"${npv_real/1000:,.0f}", html.Span("k MXN", className="u")]
            payback_txt = ("∞" if payback_real == float("inf")
                           else [f"{payback_real:.1f}",
                                 html.Span("años", className="u")])
            kpi_ahorro = [f"${ahorro_total/1000:,.0f}",
                          html.Span("k MXN/año", className="u")]
            foot_roi = "con pérdidas evitadas"
            foot_payback = ("no se recupera" if payback_real == float("inf")
                            else "cotización + interrupciones")
            foot_npv = "VPN con cotización real"
            foot_ahorro = (f"CFE ${res['ahorro_anual']:,.0f} + interrup. "
                           f"${beneficio_int:,.0f}")

            # La gráfica de VPN acumulado y las recomendaciones deben contar la
            # misma historia que las tarjetas: se reconstruyen con el CapEx real
            # de la cotización y el ahorro total (no el CapEx de catálogo del
            # motor), si no el VPN de abajo contradice al de arriba.
            acum = -capex_real
            flujo_cot = []
            for t_anio in range(1, horizonte + 1):
                ahorro_desc = (ahorro_total * (1 + infl) ** (t_anio - 1)
                               / (1 + desc) ** t_anio)
                acum += ahorro_desc
                flujo_cot.append({"Anio": t_anio,
                                  "Acumulado_MXN": round(acum, 2)})
            fig_payback = build_payback_fig(pd.DataFrame(flujo_cot))
            recs = build_recommendations(_generar_recomendaciones(
                payback_anios=payback_real, npv=npv_real, roi_pct=roi_real,
                pct_desperdicio=res["pct_desperdicio"], ahorro_anual=ahorro_total,
                fp_sis=res["df_recibo_sis"]["FP_Mensual"].min(),
                sizing=res["sizing_diario_requerido"], cant_pilas=res["cant_pilas"],
                cobertura=res["cobertura"],
            ))

            summary_rows.append(
                _summ_row("CapEx realista (llave en mano)",
                          f"${capex_real:,.0f}"))
            summary_rows.append(
                _summ_row("ROI con pérdidas evitadas", f"{roi_real:.0f} %",
                          strong=True))
            summary_rows.append(html.P(
                "Las tarjetas de arriba (ROI · Payback · VPN · Ahorro) usan "
                "esta cotización realista, no la estimación de catálogo.",
                className="tarifa-desc"))

        summary = html.Div(className="fin-summary-grid", children=summary_rows)

        table = build_recibo_table(res["df_recibo_sis"])
        report = build_project_report(num_paneles, area, df_dem, res, cot, vida)
        recibo_json = res["df_recibo_sis"].to_json(orient="split",
                                                   date_format="iso")
        fig_sol_mo, fig_sol_da, fig_sol_irr = build_solar_report_figs(df_solar)

        return (kpi_roi, payback_txt, kpi_npv, kpi_ahorro, kpi_curtail,
                foot_roi, foot_payback, foot_npv, foot_ahorro, foot_curtail,
                fig_bill, fig_curtail, fig_energy, fig_payback,
                recs, summary, table, report,
                fig_sol_mo, fig_sol_da, fig_sol_irr,
                fig_bill, fig_energy, fig_payback, recibo_json,
                "alert hidden", "")

    except Exception as exc:
        return err(str(exc))


def _summ_row(label, value, strong=False):
    return html.Div(className="fin-summary-row" + (" strong" if strong else ""),
                    children=[
                        html.Span(label, className="fs-lbl"),
                        html.Span(value, className="fs-val"),
                    ])


def _report_section(titulo, rows):
    return html.Div(className="report-section", children=[
        html.H4(titulo, className="report-h"),
        html.Div(className="fin-summary-grid", children=rows),
    ])


def _vida_str(vida):
    """Texto de la vida útil estimada (años + qué la limita)."""
    v = vida["vida_anios"]
    if v == float("inf"):
        return "sin uso (∞)"
    return f"{v:.1f} años · limita {vida['limita']}"


# Mapa de códigos de dtype de Plotly (typed arrays) a numpy.
_PLOTLY_DTYPES = {
    "f8": "float64", "f4": "float32", "i1": "int8", "i2": "int16",
    "i4": "int32", "i8": "int64", "u1": "uint8", "u2": "uint16",
    "u4": "uint32", "u8": "uint64",
}


def _coerce_array(v):
    """Normaliza un eje de traza a lista de Python.

    Plotly/Dash serializa los arrays numéricos como binario base64
    (``{"dtype": "f8", "bdata": "..."}``); aquí se decodifican a números. Los
    ejes de texto (categorías, fechas) ya llegan como lista.
    """
    if v is None:
        return None
    if isinstance(v, dict) and "bdata" in v:
        npdt = _PLOTLY_DTYPES.get(v.get("dtype"), "float64")
        arr = np.frombuffer(base64.b64decode(v["bdata"]), dtype=npdt)
        return arr.tolist()
    try:
        return list(v)
    except TypeError:
        return [v]


def figure_to_df(fig):
    """Convierte una figura (dict de Plotly) en un DataFrame con sus datos.

    Si todas las trazas comparten el mismo eje X, produce columnas ``x`` + una
    por traza; si no, usa formato largo (serie, x, y).
    """
    if not fig:
        return None
    data = fig.get("data") if isinstance(fig, dict) else getattr(fig, "data", None)
    if not data:
        return None
    series = []
    for i, tr in enumerate(data):
        get = tr.get if isinstance(tr, dict) else (lambda k, d=None: getattr(tr, k, d))
        y = _coerce_array(get("y"))
        if y is None:
            continue
        x = _coerce_array(get("x"))
        name = get("name") or f"serie{i + 1}"
        series.append((str(name), x, y))
    if not series:
        return None
    xs = [s[1] for s in series]
    same_x = (all(x is not None for x in xs)
              and len({len(x) for x in xs}) == 1
              and all(xs[0] == x for x in xs))
    if same_x:
        df = pd.DataFrame({"x": xs[0]})
        seen = {}
        for name, _x, y in series:
            col = name
            if col in seen:
                seen[col] += 1
                col = f"{name}_{seen[name]}"
            else:
                seen[col] = 0
            if len(y) != len(df):
                y = (list(y) + [None] * len(df))[:len(df)]
            df[col] = y
        return df
    rows = []
    for name, x, y in series:
        xv = x if x is not None else list(range(len(y)))
        for xi, yi in zip(xv, y):
            rows.append({"serie": name, "x": xi, "y": yi})
    return pd.DataFrame(rows)


def build_solar_report_figs(df_solar):
    """Figuras solares del reporte derivadas del store solar (potencia 15-min).

    Devuelve (mensual, diaria, irradiancia GHI vs POA). La energía se obtiene de
    ``potencia_generada`` (W × 0.25 h / 1000), válido para cualquier resolución.
    """
    e_kwh = df_solar["potencia_generada"] * 0.25 / 1000.0
    df_monthly = e_kwh.resample("ME").sum()
    daily = e_kwh.resample("D").sum()
    peak_idx = int(df_monthly.values.argmax()) if len(df_monthly) else 0
    fig_mo = build_monthly_fig(df_monthly, peak_idx)
    fig_da = build_daily_fig(daily)
    # Ventana representativa cerca del equinoccio de primavera (GHI vs POA).
    try:
        yr = df_solar.index[0].year
        target = pd.Timestamp(year=yr, month=3, day=20)
        mask = (df_solar.index >= target) & \
               (df_solar.index < target + pd.Timedelta(days=3))
        sample = df_solar.loc[mask]
        if sample.empty:
            sample = df_solar.iloc[:min(len(df_solar), 288)]
        fig_irr = build_irradiance_fig(sample)
    except Exception:
        fig_irr = empty_fig("Irradiancia no disponible")
    return fig_mo, fig_da, fig_irr


def build_project_report(num_paneles, area, df_dem, res, cot, vida=None):
    """Documento imprimible del proyecto (resumen para PDF).

    Reúne sistema, energía, batería (vida útil), finanzas (ahorro CFE) y —si se
    activó— la cotización realista con pilas + instalación/BOS + pérdidas
    evitadas + reemplazos de batería y el ROI ajustado.
    """
    fecha = datetime.date.today().strftime("%d/%m/%Y")
    demanda_anual = float(df_dem["Energia_kWh"].sum())
    payback = res["payback_anios"]
    payback_s = "∞" if payback == float("inf") else f"{payback:.1f} años"

    secciones = [
        html.Div(className="report-head", children=[
            html.Strong("Kardashev-I · Reporte de proyecto fotovoltaico"),
            html.Span(f"Generado el {fecha}", className="report-date"),
        ]),
        _report_section("Sistema", [
            _summ_row("Paneles", f"{num_paneles} uds · {num_paneles*area:.1f} m²"),
            _summ_row("Almacenamiento necesario",
                      f"{res['sizing_diario_requerido']:,.0f} kWh", strong=True),
            _summ_row("Pilas (referencia)", f"{res['cant_pilas']} uds"),
        ]),
        _report_section("Energía (anual)", [
            _summ_row("Demanda", f"{demanda_anual:,.0f} kWh/año"),
            _summ_row("Solar generada", f"{res['total_generada']:,.0f} kWh/año"),
            _summ_row("Curtailment", f"{res['pct_desperdicio']:.1f} %"),
        ]),
    ]

    if vida:
        secciones.append(_report_section("Batería · vida útil", [
            _summ_row("Química", vida["nombre"]),
            _summ_row("Ciclos equivalentes / año",
                      f"{vida['ciclos_por_anio']:.0f}"),
            _summ_row("Vida útil estimada", _vida_str(vida), strong=True),
            _summ_row("Reemplazos en el horizonte", f"{vida['reemplazos']}"),
        ]))

    secciones.append(_report_section(
        "Financiero · estimación rápida (catálogo, solo ahorro CFE)", [
        _summ_row("Ahorro anual CFE", f"${res['ahorro_anual']:,.0f}"),
        _summ_row("ROI (horizonte)", f"{res['roi_pct']:.0f} %"),
        _summ_row("Payback", payback_s),
        _summ_row("VPN", f"${res['npv']:,.0f}"),
    ]))

    if cot:
        pb = cot["payback_real"]
        pb_s = "∞" if pb == float("inf") else f"{pb:.1f} años"
        cot_rows = []
        if cot.get("modo") == "total":
            cot_rows.append(_summ_row("CapEx total (cotización)",
                                      f"${cot['capex_real']:,.0f}", strong=True))
        else:
            cot_rows += [
                _summ_row("Costo paneles", f"${cot['costo_paneles']:,.0f}"),
                _summ_row("Costo BESS instalado", f"${cot['costo_bess']:,.0f}"),
                _summ_row("Instalación / BOS", f"${cot['costo_bos']:,.0f}"),
                _summ_row("CapEx total (realista)",
                          f"${cot['capex_real']:,.0f}", strong=True),
            ]
        cot_rows += [
            _summ_row("Reemplazos de batería (VP)",
                      f"${cot.get('costo_reemplazos', 0):,.0f}"),
            _summ_row("Pérdidas evitadas / año", f"${cot['beneficio_int']:,.0f}"),
            _summ_row("Ahorro total / año", f"${cot['ahorro_total']:,.0f}"),
            _summ_row("ROI por pérdidas evitadas",
                      f"{cot['roi_real']:.0f} %", strong=True),
            _summ_row("Payback ajustado", pb_s),
            _summ_row("VPN ajustado", f"${cot['npv_real']:,.0f}"),
        ]
        secciones.append(_report_section(
            "Cotización realista · costo del sistema + interrupciones", cot_rows))
    else:
        secciones.append(html.P(
            "Activa «cotización realista» antes de ejecutar para incluir pilas, "
            "instalación/BOS y el costo de las interrupciones evitadas.",
            className="tarifa-desc"))

    return html.Div(className="report-doc", children=secciones)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
