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
from dash import (Input, Output, State, callback, clientside_callback, dcc,
                  html, no_update)
import dash_leaflet as dl
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from timezonefinder import TimezoneFinder

from motor_2 import calculate
from motor_fisica_avanzada import calculate_advanced
from motor_financiero import HORIZONTE_ANIOS, simular_financiero
import perfil_demanda
import tarifas_cfe
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
AZ_DEFAULT = 180
AREA_DEFAULT = 2.1      # m² por panel
N_PANELS_DEFAULT = 20   # número de paneles → total 42 m²
EFF_DEFAULT = 0.21
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
KWH_DIA_DEFAULT = 15    # kWh/día
RECIBO_MES_DEFAULT = 1500  # MXN/mes
TARIFA_DEFAULT = "DAC"

# Defaults financieros (editables en la página de análisis)
COSTO_PANEL_M2_DEFAULT = 1000     # MXN / m²
COSTO_PILA_DEFAULT = 500000       # MXN / pila (100 kWh)
NUM_APAGONES_DEFAULT = 10
DUR_APAGON_DEFAULT = 1.5          # horas
CAP_RESPALDO_DEFAULT = 100        # kWh

# Tarifa GDMTH manual (Modo Avanzado, finanzas) — defaults = constantes del motor
PRECIO_BASE_DEFAULT = 1.10        # MXN/kWh
PRECIO_INT_DEFAULT = 1.50         # MXN/kWh
PRECIO_PUNTA_DEFAULT = 3.20       # MXN/kWh
CARGO_CAP_DEFAULT = 350           # MXN/kW (capacidad/punta)
CARGO_DIST_DEFAULT = 100          # MXN/kW (distribución)
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


# ───────────────────────── Advanced figures ────────────────────────────────────
def build_decomp_fig(sample):
    """4 paneles GHI/DNI/DHI/POA (W/m²) + elevación solar sobre GHI."""
    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"secondary_y": True}, {}], [{}, {}]],
        subplot_titles=("GHI + elevación solar", "DNI (haz directo)",
                        "DHI (difusa)", "POA / Gtot (plano del panel)"),
        horizontal_spacing=0.10, vertical_spacing=0.20,
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
    fig.update_layout(showlegend=False)
    fig.update_xaxes(showgrid=False, linecolor="#1a1a1a", tickcolor=TICK,
                     zeroline=False, type="date")
    fig.update_yaxes(gridcolor=GRID, showgrid=True, linecolor="#1a1a1a",
                     tickcolor=TICK, zeroline=False)
    fig.update_yaxes(title_text="W/m²", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="°", row=1, col=1, secondary_y=True,
                     showgrid=False, range=[0, 90])
    fig.for_each_annotation(lambda a: a.update(font=dict(size=12.5, color=TEXT)))
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
        ("Otras (PR)", "relative", -p.get("otras_pr", 0)),
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
            html.Label("Azimut", style={"marginBottom": "8px"}),
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
        html.Div(className="field-row", children=[
            html.Div(className="field", children=[
                html.Label(["Núm. paneles ",
                            html.Span("uds", className="hint")]),
                dcc.Input(id="inp-n-panels", type="number",
                          value=N_PANELS_DEFAULT, step=1, min=1,
                          className="input", debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Área / panel ",
                            html.Span("m²", className="hint")]),
                dcc.Input(id="inp-area", type="number", value=AREA_DEFAULT,
                          step=0.1, min=0.1, className="input", debounce=True),
            ]),
        ]),
        html.Div(id="total-area-display", className="total-area-display",
                 children=f"Área total: {N_PANELS_DEFAULT * AREA_DEFAULT:.1f} m²"),
        html.Div(className="field-row adv-only", children=[
            html.Div(className="field", children=[
                html.Label(["Eficiencia η (Realistic ~ 0.15-0.22) ",
                            html.Span("0–1", className="hint")]),
                dcc.Input(id="inp-eff", type="number", value=EFF_DEFAULT,
                          step=0.01, min=0.01, max=1, className="input",
                          debounce=True),
            ]),
            html.Div(className="field", children=[
                html.Label(["Performance ratio (Loss factor ~ 0.7–0.8) ",
                            html.Span("0–1", className="hint")]),
                dcc.Input(id="inp-pr", type="number", value=PR_DEFAULT,
                          step=0.01, min=0.01, max=1, className="input",
                          debounce=True),
            ]),
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

    html.Button(id="btn-calc", className="calc-btn", n_clicks=0, children=[
        svg_img(_ICON_BOLT, 14, 14),
        html.Span("Calcular generación"),
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

    html.Div(className="page-head", children=[
        html.Div(children=[
            html.H1("Resumen anual"),
            html.P("Ejecuta el cálculo para ver los resultados.",
                   className="sub", id="page-sub"),
        ]),
        html.Div(className="meta", id="page-meta", children=[
            "MODELO JENSEN · CLEAR-SKY (INEICHEN)",
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
            dcc.Upload(
                id="upload-demanda",
                className="fin-upload",
                children=html.Div([
                    svg_img(_ICON_ENERGY, 18, 18),
                    html.Div([
                        html.Strong("Arrastra o haz clic"),
                        html.Span(" para subir el CSV de demanda", className="fin-up-sub"),
                    ]),
                    html.Div(
                        "Columnas: Fecha_Hora · Energia_kWh · Energia_kVArh (15 min, 2026)",
                        className="fin-up-hint"),
                ]),
                multiple=False,
                accept=".csv",
            ),
            html.Div(id="fin-upload-status", className="fin-up-status"),

            # ── Alternativa sin CSV: tarifa + perfil sintético de demanda ──
            html.Div(className="fin-divider", children="o estima tu demanda"),
            html.Div(className="fin-tarifa", children=[
                html.Div(className="field", children=[
                    html.Label(["Tarifa CFE ",
                                html.Span("", id="tarifa-fecha", className="hint")]),
                    dcc.Dropdown(
                        id="dd-tarifa", className="dd-tarifa",
                        options=tarifas_cfe.opciones_dropdown(),
                        value=TARIFA_DEFAULT, clearable=False,
                    ),
                    html.P("", id="tarifa-desc", className="tarifa-desc"),
                ]),
                html.Div(className="field", children=[
                    dcc.RadioItems(
                        id="consumo-modo", className="radio-row",
                        options=[
                            {"label": " kWh / día", "value": "kwh"},
                            {"label": " Recibo MXN / mes", "value": "recibo"},
                        ],
                        value="kwh", inline=True,
                    ),
                ]),
                html.Div(className="field", children=[
                    html.Div(id="wrap-kwh", children=[
                        html.Label(["Consumo diario ",
                                    html.Span("kWh/día", className="hint")]),
                        dcc.Input(id="inp-kwh-dia", type="number",
                                  value=KWH_DIA_DEFAULT, step="any", min=0.1,
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

            html.Div(className="fin-inputs", children=[
                html.Div(className="field", children=[
                    html.Label(["Costo panel ", html.Span("MXN/m²", className="hint")]),
                    dcc.Input(id="inp-costo-panel", type="number",
                              value=COSTO_PANEL_M2_DEFAULT, step=50, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field", children=[
                    html.Label(["Costo pila ", html.Span("MXN/100kWh", className="hint")]),
                    dcc.Input(id="inp-costo-pila", type="number",
                              value=COSTO_PILA_DEFAULT, step=10000, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field", children=[
                    html.Label(["Núm. apagones ", html.Span("/año", className="hint")]),
                    dcc.Input(id="inp-num-apagones", type="number",
                              value=NUM_APAGONES_DEFAULT, step=1, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field", children=[
                    html.Label(["Duración apagón ", html.Span("h", className="hint")]),
                    dcc.Input(id="inp-dur-apagon", type="number",
                              value=DUR_APAGON_DEFAULT, step=0.5, min=0,
                              className="input", debounce=True),
                ]),
                html.Div(className="field", children=[
                    html.Label(["Cap. respaldo ", html.Span("kWh", className="hint")]),
                    dcc.Input(id="inp-cap-respaldo", type="number",
                              value=CAP_RESPALDO_DEFAULT, step=50, min=0,
                              className="input", debounce=True),
                ]),
            ]),

            # ── Tarifa GDMTH manual + finanzas avanzadas (solo Modo Avanzado) ──
            html.Div(className="adv-only", children=[
                html.Div(className="fin-divider",
                         children="tarifa CFE GDMTH personalizada"),
                html.Div(className="info-box info-box--sm", children=[
                    "Ajusta los precios por horario de la tarifa GDMTH y los "
                    "supuestos financieros. El VPN se calcula como una anualidad "
                    "creciente: el ahorro sube con la inflación y se descuenta a "
                    "la tasa indicada a lo largo del horizonte de "
                    f"{HORIZONTE_ANIOS} años.",
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
            ]),
            html.Div(id="fin-table-sis", className="fin-table-wrap", children=[
                html.Div("Ejecuta el análisis para ver el detalle.",
                         className="rec-empty"),
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
    dcc.Download(id="download-csv"),
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
        const sld = document.getElementById('sld-azimuth');
        if (sld) sld.style.backgroundSize = ((n / 360) * 100) + '% 100%';
        const needle = document.getElementById('needle');
        if (needle) needle.style.transform = 'translate(-50%,-100%) rotate(' + n + 'deg)';
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
            if (n >= d.min && n < d.max) { name = d.name; break; }
        }
        const suffix = (n > 135 && n < 225) ? ' · óptimo en hemisferio N'
                     : (n > 315 || n < 45) ? ' · óptimo en hemisferio S' : '';
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
        const d = {eff:0.21,pr:0.82,fp:1.0,tamb:25,gamma:-0.40,noct:45,
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
)
def tarifa_info(tid):
    t = tarifas_cfe.TARIFAS.get(tid)
    if not t:
        return "", ""
    return t["descripcion"], t.get("actualizado", "")


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
    Output("store-demand", "data", allow_duplicate=True),
    Output("consumo-status", "children"),
    Output("consumo-status", "className"),
    Input("consumo-modo", "value"),
    Input("inp-kwh-dia", "value"),
    Input("inp-recibo-mes", "value"),
    Input("dd-tarifa", "value"),
    prevent_initial_call=True,
)
def gen_demand_profile(modo, kwh_dia, recibo, tarifa):
    """Genera un perfil de demanda sintético (Modo Simple) → store-demand.

    Alimenta el mismo store que usa el análisis financiero, de modo que el
    usuario no experto no necesita subir un CSV.
    """
    try:
        if modo == "recibo":
            # Campo aún vacío: no es un error, solo esperamos un valor válido.
            if recibo is None or recibo == "":
                return no_update, no_update, no_update
            # GDMTH no se invierte aquí (usa CSV + motor financiero); para la
            # estimación simple aproximamos con la estructura horaria HM.
            tarifa_inv = "HM" if tarifa == "GDMTH" else tarifa
            kwh = tarifas_cfe.kwh_dia_desde_recibo(recibo, tarifa_inv)
        else:
            if kwh_dia is None or kwh_dia == "":
                return no_update, no_update, no_update
            kwh = float(kwh_dia)
        df = perfil_demanda.generar_perfil(kwh, "residencial")
        store = df.to_json(orient="split", date_format="iso")
        anual = perfil_demanda.consumo_anual_kwh(df)
        msg = f"✓ Perfil generado · {kwh:.1f} kWh/día · {anual:,.0f} kWh/año"
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
    prevent_initial_call=True,
)
def run_calculation(_, lat, lon, tz, tilt, azimuth, alt, n_panels, area, eff, pr,
                    ui_mode, tamb, gamma, noct, soiling, wiring, eta_inv,
                    degr, year_idx, iam):
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

        modo = ui_mode or "simple"
        tz_motor = _tz_para_motor(tz or TZ_DEFAULT)
        perdidas = None
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
        page_sub = (f"{n} paneles · {total_area:.1f} m² · η {eff} · PR {pr} "
                    f"a {lat:.2f}°, {lon:.2f}° · modo {modo_lbl}.")

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
    State("ui-mode", "data"),
    State("inp-precio-base", "value"),
    State("inp-precio-int", "value"),
    State("inp-precio-punta", "value"),
    State("inp-cargo-cap", "value"),
    State("inp-cargo-dist", "value"),
    State("inp-inflacion", "value"),
    State("inp-descuento", "value"),
    prevent_initial_call=True,
)
def run_financial(_, store_df, store_meta, store_demand,
                  costo_panel, costo_pila, num_apagones, dur_apagon, cap_respaldo,
                  ui_mode, precio_base, precio_int, precio_punta,
                  cargo_cap, cargo_dist, inflacion, descuento):
    blank = empty_fig()
    dash_vals = ["—"] * 5
    foots = [""] * 5
    empty_recs = [html.Div("Ejecuta el análisis.", className="rec-empty")]
    empty_summary = [html.Div("—", className="rec-empty")]
    empty_table = [html.Div("Sin datos.", className="rec-empty")]

    def err(msg):
        return (*dash_vals, *foots, blank, blank, blank, blank,
                empty_recs, empty_summary, empty_table, "alert", msg)

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

        res = simular_financiero(
            df_solar=df_solar, df_demanda=df_dem,
            num_paneles=num_paneles, area=area,
            costo_panel_m2=float(costo_panel or 0),
            costo_pila=float(costo_pila or 0),
            cap_respaldo_max_kwh=float(cap_respaldo or 0),
            num_apagones=int(num_apagones or 0),
            duracion_horas_apagon=float(dur_apagon or 1.0),
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

        foot_roi = f"horizonte {HORIZONTE_ANIOS} años"
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

        summary = html.Div(className="fin-summary-grid", children=[
            _summ_row("Paneles", f"{num_paneles} uds · {num_paneles*area:.1f} m²"),
            _summ_row("Costo paneles", f"${res['costo_total_paneles']:,.0f}"),
            _summ_row("Banco diario", f"{res['sizing_diario_requerido']:,.0f} kWh"),
            _summ_row("Pilas", f"{res['cant_pilas']} uds"),
            _summ_row("Costo pilas", f"${res['costo_total_pilas']:,.0f}"),
            _summ_row("CapEx total", f"${res['capex']:,.0f}", strong=True),
            _summ_row("Solar generada", f"{res['total_generada']:,.0f} kWh/año"),
        ])

        table = build_recibo_table(res["df_recibo_sis"])

        return (kpi_roi, payback_txt, kpi_npv, kpi_ahorro, kpi_curtail,
                foot_roi, foot_payback, foot_npv, foot_ahorro, foot_curtail,
                fig_bill, fig_curtail, fig_energy, fig_payback,
                recs, summary, table, "alert hidden", "")

    except Exception as exc:
        return err(str(exc))


def _summ_row(label, value, strong=False):
    return html.Div(className="fin-summary-row" + (" strong" if strong else ""),
                    children=[
                        html.Span(label, className="fs-lbl"),
                        html.Span(value, className="fs-val"),
                    ])


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
