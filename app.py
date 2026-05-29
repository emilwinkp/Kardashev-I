"""Kardashev-I — Simulador Solar Fotovoltaico (Dash)

Replica visualmente design.html sobre la lógica de Dash + motor_2.py.
NOTA: motor_2.py es intocable.
"""
import base64
from io import StringIO

import dash
from dash import (Input, Output, State, callback, clientside_callback, dcc,
                  html, no_update)
import dash_leaflet as dl
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from timezonefinder import TimezoneFinder

from motor_2 import calculate

_tf = TimezoneFinder()


# ───────────────────────── Constantes ──────────────────────────────────────────
ACCENT = "#fbbf24"
ACCENT_FILL = "rgba(251,191,36,0.20)"
ACCENT_FILL_SOFT = "rgba(251,191,36,0.55)"
INFO = "#60a5fa"
DANGER = "#f43f5e"

PAPER_BG = "rgba(0,0,0,0)"
PLOT_BG = "rgba(0,0,0,0)"
GRID = "#141414"
TICK = "#666"
TEXT = "#a1a1a1"
TOOLTIP_BG = "#0a0a0a"
TOOLTIP_BD = "#262626"
FONT_FAMILY = "Inter, system-ui, sans-serif"

LAT_DEFAULT = 25.7
LON_DEFAULT = -100.3
TZ_DEFAULT = "America/Mexico_City"
TILT_DEFAULT = 22
AZ_DEFAULT = 180
AREA_DEFAULT = 2.1      # m² por panel
N_PANELS_DEFAULT = 20   # número de paneles → total 42 m²
EFF_DEFAULT = 0.21
PR_DEFAULT = 0.82

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


def build_irradiance_fig(sample):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=sample.index, y=sample["ghi"], name="GHI", mode="lines",
        line=dict(color=INFO, width=1.2),
        hovertemplate="<b>%{x|%d %b %H:%M}</b><br>GHI: %{y:.0f} W/m²<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=sample.index, y=sample["poa_global"], name="POA", mode="lines",
        line=dict(color=ACCENT, width=1.4),
        fill="tozeroy", fillcolor=ACCENT_FILL,
        hovertemplate="<b>%{x|%d %b %H:%M}</b><br>POA: %{y:.0f} W/m²<extra></extra>",
    ))
    fig.update_layout(**_base_layout())
    fig.update_layout(**_axes(" W/m²"))
    fig.update_layout(hovermode="x unified")
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
    html.Div(className="topbar-right", children=[
        html.Div(className="pill", children=[
            html.Span(className="dot"),
            "JENSEN · ACTIVO",
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
        html.Div(className="field-row", children=[
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
        html.Div(className="field", children=[
            html.Label(["Factor de potencia ",
                        html.Span("cos φ", className="hint")]),
            dcc.Input(id="inp-fp", type="number", value=1.0,
                      step=0.01, min=0.01, max=1.0, className="input",
                      debounce=True),
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
                    html.P("kWh/día estimados a partir de POA · Jensen + clear-sky",
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
                html.Div(className="card-actions", children=[
                    html.Div(className="legend", children=[
                        html.Span([
                            html.Span(className="swatch",
                                      style={"background": INFO}), "GHI",
                        ]),
                        html.Span([
                            html.Span(className="swatch",
                                      style={"background": ACCENT}), "POA",
                        ]),
                    ]),
                    html.Div(className="range-row", children=[
                        html.Span("RANGO", className="lbl"),
                        dcc.Input(id="dr-from", type="text",
                                  value="2026-06-20",
                                  placeholder="YYYY-MM-DD",
                                  debounce=True),
                        html.Span("→", className="dash"),
                        dcc.Input(id="dr-to", type="text",
                                  value="2026-06-26",
                                  placeholder="YYYY-MM-DD",
                                  debounce=True),
                    ]),
                ]),
            ]),
            html.Div(className="chart-wrap", children=[
                dcc.Graph(id="graph-irradiance",
                          figure=empty_fig("Ejecuta el cálculo primero"),
                          config={"displayModeBar": False,
                                  "doubleClick": "reset+autosize"},
                          style={"height": "260px", "width": "100%"}),
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
    ]),

    html.Footer(className="app-footer", children=[
        html.Span("KARDASHEV-I · BUILD 0.2.0"),
        html.Span("JENSEN · CLEAR-SKY"),
    ]),
])


# ───────────────────────── Layout ──────────────────────────────────────────────
app.layout = html.Div([
    dcc.Store(id="store-df"),
    dcc.Store(id="dummy-landing"),
    dcc.Store(id="dummy-tilt"),
    dcc.Store(id="dummy-az"),
    dcc.Download(id="download-csv"),
    landing,
    html.Div(id="app", children=[
        topbar,
        html.Div(className="shell", children=[sidebar, main]),
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
    Output("error-alert", "className"),
    Output("error-msg", "children"),
    Output("page-sub", "children"),
    Input("btn-calc", "n_clicks"),
    State("inp-lat", "value"),
    State("inp-lon", "value"),
    State("inp-tz", "value"),
    State("sld-tilt", "value"),
    State("sld-azimuth", "value"),
    State("inp-n-panels", "value"),
    State("inp-area", "value"),
    State("inp-eff", "value"),
    State("inp-pr", "value"),
    prevent_initial_call=True,
)
def run_calculation(_, lat, lon, tz, tilt, azimuth, n_panels, area, eff, pr):
    blank = empty_fig()
    try:
        if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError("Lat/Lon fuera de rango.")
        if eff is None or pr is None or not (0 < eff <= 1) or not (0 < pr <= 1):
            raise ValueError("η y PR deben estar entre 0 y 1.")
        if area is None or area <= 0:
            raise ValueError("Área por panel debe ser mayor que 0.")
        n = int(n_panels) if n_panels and n_panels >= 1 else 1
        total_area = n * float(area)

        df = calculate(lat, lon, tz or TZ_DEFAULT,
                       float(tilt), float(azimuth),
                       total_area, float(eff), float(pr))

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

        df_store = df[["ghi", "poa_global", "potencia_generada"]].copy()
        df_store.index = df_store.index.tz_localize(None)
        store_json = df_store.to_json(orient="split", date_format="iso")

        page_sub = (f"{n} paneles · {total_area:.1f} m² · η {eff} · PR {pr} "
                    f"a {lat:.2f}°, {lon:.2f}°.")

        return (kpi_energia, kpi_pico, kpi_cf, kpi_mes,
                foot_energia, foot_pico, foot_cf, foot_mes,
                fig_ts, fig_mo,
                ms_peak, ms_min, ms_avg,
                store_json, "alert hidden", "", page_sub)

    except Exception as exc:
        return ("—", "—", "—", "—",
                "", "", "", "",
                blank, blank,
                "—", "—", "—",
                None, "alert", str(exc),
                "Ejecuta el cálculo para ver los resultados.")


@callback(
    Output("graph-irradiance", "figure"),
    Input("dr-from", "value"),
    Input("dr-to", "value"),
    Input("store-df", "data"),
    prevent_initial_call=True,
)
def update_irradiance(start, end, stored):
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
    return build_irradiance_fig(sample)


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


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
