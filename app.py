import dash
from dash import dcc, html, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_leaflet as dl
import plotly.graph_objects as go
import pandas as pd
from motor_2 import calculate

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG], title="Kardashev-I")
server = app.server

LAT_DEFAULT = 25.6
LON_DEFAULT = -100.3
ACCENT = "#f0a500"
THEME = "plotly_dark"
PAPER_BG = "rgba(0,0,0,0)"


# ── Helpers ────────────────────────────────────────────────────────────────────

def empty_fig(msg="Ejecuta el cálculo para ver resultados"):
    fig = go.Figure()
    fig.update_layout(
        template=THEME,
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PAPER_BG,
        annotations=[dict(
            text=msg, x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#666"), xref="paper", yref="paper",
        )],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=0, r=0, t=0, b=0),
    )
    return fig


def kpi_card(card_id, label):
    return dbc.Card(
        dbc.CardBody([
            html.P(label, className="text-muted small mb-1 text-truncate"),
            html.H4("—", id=card_id, className="text-warning mb-0 text-truncate"),
        ]),
        className="text-center border-secondary shadow-sm h-100",
    )


# ── Sidebar ────────────────────────────────────────────────────────────────────

sidebar = dbc.Card([
    dbc.CardHeader(html.Strong("Parámetros")),
    dbc.CardBody([
        html.P("Ubicación", className="text-warning fw-semibold mb-2 small"),
        dbc.InputGroup([
            dbc.InputGroupText("Lat", className="small"),
            dbc.Input(id="inp-lat", type="number", value=LAT_DEFAULT, step=0.0001, size="sm"),
        ], className="mb-2 input-group-sm"),
        dbc.InputGroup([
            dbc.InputGroupText("Lon", className="small"),
            dbc.Input(id="inp-lon", type="number", value=LON_DEFAULT, step=0.0001, size="sm"),
        ], className="mb-2 input-group-sm"),
        dbc.InputGroup([
            dbc.InputGroupText("TZ", className="small"),
            dbc.Input(id="inp-tz", type="text", value="Etc/GMT+6", size="sm"),
        ], className="mb-3 input-group-sm"),

        html.P("Panel solar", className="text-warning fw-semibold mb-1 small"),
        html.Small(id="lbl-tilt", className="text-muted"),
        dcc.Slider(id="sld-tilt", min=0, max=90, step=1, value=25,
                   marks={0: "0°", 45: "45°", 90: "90°"},
                   tooltip={"placement": "bottom", "always_visible": False},
                   className="mb-1"),
        html.Small(id="lbl-azimuth", className="text-muted"),
        dcc.Slider(id="sld-azimuth", min=0, max=360, step=5, value=180,
                   marks={0: "N", 90: "E", 180: "S", 270: "O"},
                   tooltip={"placement": "bottom", "always_visible": False},
                   className="mb-2"),
        dbc.InputGroup([
            dbc.InputGroupText("m²", className="small"),
            dbc.Input(id="inp-area", type="number", value=1.7, step=0.1, min=0.1, size="sm"),
        ], className="mb-2 input-group-sm"),
        dbc.InputGroup([
            dbc.InputGroupText("η", className="small"),
            dbc.Input(id="inp-eff", type="number", value=0.20, step=0.01,
                      min=0.01, max=1.0, size="sm"),
        ], className="mb-2 input-group-sm"),
        dbc.InputGroup([
            dbc.InputGroupText("PR", className="small"),
            dbc.Input(id="inp-pr", type="number", value=0.75, step=0.01,
                      min=0.01, max=1.0, size="sm"),
        ], className="mb-3 input-group-sm"),

        dbc.Button("Calcular", id="btn-calc", color="warning",
                   size="lg", className="w-100 fw-bold"),
    ]),
], className="border-secondary shadow")


# ── Map card ───────────────────────────────────────────────────────────────────

map_card = dbc.Card([
    dbc.CardHeader(html.Small("Ubicación", className="text-muted")),
    dbc.CardBody(
        dl.Map(
            id="map",
            center=[LAT_DEFAULT, LON_DEFAULT],
            zoom=7,
            children=[
                dl.TileLayer(
                    url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
                    attribution="&copy; CartoDB",
                ),
                dl.Marker(id="map-marker", position=[LAT_DEFAULT, LON_DEFAULT]),
            ],
            style={"height": "220px", "borderRadius": "6px"},
        ),
        className="p-1",
    ),
], className="border-secondary shadow mb-3")


# ── Main dashboard ─────────────────────────────────────────────────────────────

dashboard = html.Div([
    # KPI row
    dbc.Row([
        dbc.Col(kpi_card("kpi-energia", "Energía anual"), width=3),
        dbc.Col(kpi_card("kpi-pico", "Potencia pico"), width=3),
        dbc.Col(kpi_card("kpi-cf", "Factor de capacidad"), width=3),
        dbc.Col(kpi_card("kpi-mes", "Mes de mayor prod."), width=3),
    ], className="g-2 mb-3"),

    # Daily time series
    dbc.Card([
        dbc.CardHeader("Generación diaria — Año completo"),
        dbc.CardBody(
            dcc.Loading(
                dcc.Graph(id="graph-timeseries", figure=empty_fig(),
                          config={"displayModeBar": True, "scrollZoom": True},
                          style={"height": "300px"}),
                color=ACCENT, type="circle",
            )
        ),
    ], className="border-secondary shadow mb-3"),

    # Monthly bar
    dbc.Card([
        dbc.CardHeader("Producción mensual (kWh)"),
        dbc.CardBody(
            dcc.Graph(id="graph-monthly", figure=empty_fig(),
                      config={"displayModeBar": False},
                      style={"height": "260px"})
        ),
    ], className="border-secondary shadow mb-3"),

    # GHI vs POA with date picker
    dbc.Card([
        dbc.CardHeader(
            dbc.Row([
                dbc.Col("Irradiancia: GHI vs POA", className="align-self-center fw-semibold"),
                dbc.Col(
                    dcc.DatePickerRange(
                        id="date-picker",
                        min_date_allowed="2026-01-01",
                        max_date_allowed="2026-12-31",
                        start_date="2026-06-20",
                        end_date="2026-06-26",
                        display_format="DD MMM",
                        style={"fontSize": "12px"},
                    ),
                    className="d-flex justify-content-end",
                ),
            ], align="center"),
        ),
        dbc.CardBody(
            dcc.Graph(id="graph-irradiance", figure=empty_fig("Ejecuta el cálculo y selecciona un rango de fechas"),
                      config={"displayModeBar": False},
                      style={"height": "260px"})
        ),
    ], className="border-secondary shadow mb-3"),

    dbc.Alert(id="error-alert", color="danger", is_open=False, dismissable=True),
])


# ── App layout ─────────────────────────────────────────────────────────────────

app.layout = html.Div([
    dcc.Store(id="store-df"),
    dbc.Navbar(
        dbc.Container(
            html.Span("Kardashev-I — Simulador Solar Fotovoltaico",
                      className="navbar-brand fw-bold fs-5 mb-0"),
            fluid=True,
        ),
        color="dark", dark=True, className="shadow mb-3 py-2",
    ),
    dbc.Container([
        dbc.Row([
            dbc.Col([map_card, sidebar], width=3),
            dbc.Col(dashboard, width=9),
        ]),
    ], fluid=True, className="px-4 pb-4"),
])


# ── Callbacks ──────────────────────────────────────────────────────────────────

@callback(Output("lbl-tilt", "children"), Input("sld-tilt", "value"))
def label_tilt(v):
    return f"Inclinación: {v}°"


@callback(Output("lbl-azimuth", "children"), Input("sld-azimuth", "value"))
def label_azimuth(v):
    dirs = {0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SO", 270: "O", 315: "NO", 360: "N"}
    closest = min(dirs, key=lambda d: abs(d - v))
    return f"Azimut: {v}° ({dirs[closest]})"


@callback(
    Output("map-marker", "position"),
    Output("map", "center"),
    Input("inp-lat", "value"),
    Input("inp-lon", "value"),
)
def sync_map(lat, lon):
    if lat is None or lon is None:
        return no_update, no_update
    return [lat, lon], [lat, lon]


@callback(
    Output("kpi-energia", "children"),
    Output("kpi-pico", "children"),
    Output("kpi-cf", "children"),
    Output("kpi-mes", "children"),
    Output("graph-timeseries", "figure"),
    Output("graph-monthly", "figure"),
    Output("store-df", "data"),
    Output("error-alert", "children"),
    Output("error-alert", "is_open"),
    Input("btn-calc", "n_clicks"),
    State("inp-lat", "value"),
    State("inp-lon", "value"),
    State("inp-tz", "value"),
    State("sld-tilt", "value"),
    State("sld-azimuth", "value"),
    State("inp-area", "value"),
    State("inp-eff", "value"),
    State("inp-pr", "value"),
    prevent_initial_call=True,
)
def run_calculation(_, lat, lon, tz, tilt, azimuth, area, eff, pr):
    blank = empty_fig()
    try:
        df = calculate(lat, lon, tz, tilt, azimuth, area, eff, pr)

        energia_kwh = df["potencia_generada"].sum() / 1000
        pico_w = df["potencia_generada"].max()
        cf_pct = (energia_kwh / (area * eff * 8760)) * 100
        df_monthly = df["potencia_generada"].resample("ME").sum() / 1000
        meses_es = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
        peak_month = meses_es[df_monthly.idxmax().month - 1]

        # ── Daily time series ──────────────────────────────────────────────────
        daily = df["potencia_generada"].resample("D").sum() / 1000
        fig_ts = go.Figure(go.Scatter(
            x=daily.index,
            y=daily.values,
            fill="tozeroy",
            fillcolor="rgba(240,165,0,0.15)",
            line=dict(color=ACCENT, width=1.5),
            hovertemplate="%{x|%d %b %Y}: <b>%{y:.1f} kWh</b><extra></extra>",
        ))
        fig_ts.update_layout(
            template=THEME,
            paper_bgcolor=PAPER_BG,
            yaxis_title="kWh / día",
            hovermode="x unified",
            xaxis=dict(
                rangeslider=dict(visible=True, thickness=0.07, bgcolor="#1a1a1a"),
                type="date",
                rangeselector=dict(
                    buttons=[
                        dict(count=1, label="1 mes", step="month", stepmode="backward"),
                        dict(count=3, label="3 meses", step="month", stepmode="backward"),
                        dict(count=6, label="6 meses", step="month", stepmode="backward"),
                        dict(step="all", label="Año completo"),
                    ],
                    bgcolor="#2a2a2a", activecolor=ACCENT,
                ),
            ),
            margin=dict(l=50, r=20, t=10, b=50),
        )

        # ── Monthly bar ────────────────────────────────────────────────────────
        month_labels = [d.strftime("%b") for d in df_monthly.index]
        fig_mo = go.Figure(go.Bar(
            x=month_labels,
            y=df_monthly.values,
            marker_color=ACCENT,
            marker_line_color="rgba(0,0,0,0)",
            text=[f"{v:.0f}" for v in df_monthly.values],
            textposition="outside",
            textfont=dict(size=11, color=ACCENT),
            hovertemplate="%{x}: <b>%{y:.1f} kWh</b><extra></extra>",
        ))
        fig_mo.update_layout(
            template=THEME,
            paper_bgcolor=PAPER_BG,
            yaxis_title="kWh",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
            xaxis=dict(showgrid=False),
            bargap=0.15,
            margin=dict(l=50, r=20, t=20, b=30),
        )

        # ── Store: serialize tz-stripped DataFrame ─────────────────────────────
        df_store = df[["ghi", "poa_global"]].copy()
        df_store.index = df_store.index.tz_localize(None)
        store_json = df_store.to_json(orient="split", date_format="iso")

        return (
            f"{energia_kwh:,.0f} kWh/año",
            f"{pico_w:,.0f} W",
            f"{cf_pct:.1f}%",
            peak_month,
            fig_ts,
            fig_mo,
            store_json,
            "",
            False,
        )

    except Exception as exc:
        return "—", "—", "—", "—", blank, blank, None, str(exc), True


@callback(
    Output("graph-irradiance", "figure"),
    Input("date-picker", "start_date"),
    Input("date-picker", "end_date"),
    Input("store-df", "data"),
    prevent_initial_call=True,
)
def update_irradiance(start, end, stored):  # stored is now an Input, fires on new data
    if stored is None:
        return empty_fig("Ejecuta el cálculo primero")

    df = pd.read_json(stored, orient="split")
    df.index = pd.to_datetime(df.index)
    sample = df.loc[start:end]

    if sample.empty:
        return empty_fig("Sin datos en el rango seleccionado")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=sample.index, y=sample["ghi"],
        name="GHI (horizontal)",
        line=dict(color="#4a9eda", width=1.5),
        hovertemplate="%{x|%d %b %H:%M}: <b>%{y:.0f} W/m²</b><extra>GHI</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=sample.index, y=sample["poa_global"],
        name="POA (panel inclinado)",
        line=dict(color=ACCENT, width=2),
        hovertemplate="%{x|%d %b %H:%M}: <b>%{y:.0f} W/m²</b><extra>POA</extra>",
    ))
    fig.update_layout(
        template=THEME,
        paper_bgcolor=PAPER_BG,
        yaxis_title="W / m²",
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
        margin=dict(l=50, r=20, t=30, b=30),
    )
    return fig


if __name__ == "__main__":
    app.run(debug=True)
