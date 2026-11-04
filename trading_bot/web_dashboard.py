"""
MT5 Trading Bot - Web Dashboard
http://localhost:8050
"""
import sys, os, threading, time, webbrowser
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime, date
import pandas as pd
import numpy as np

import dash
from dash import dcc, html, Input, Output, State, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import talib

import mt5_connector as mt5c
import indicators    as ind_engine
import risk_manager  as rm
from config import GOAL, TRADING

# ══════════════════════════════════════════════════════════
#  THEME
# ══════════════════════════════════════════════════════════
BG    = "#0d1117"
CARD  = "#161b22"
BORD  = "#30363d"
TEXT  = "#e6edf3"
MUTED = "#8b949e"
GREEN = "#3fb950"
RED   = "#f85149"
YEL   = "#d29922"
BLUE  = "#58a6ff"
PUR   = "#bc8cff"
CYAN  = "#39d353"
ACC   = "#1f6feb"

CS = {"backgroundColor": CARD, "border": f"1px solid {BORD}",
      "borderRadius": "8px", "padding": "16px", "marginBottom": "12px"}

SYMBOLS = ["XAUUSDm", "BTCUSDm", "ETHUSDm"]

# ══════════════════════════════════════════════════════════
#  GLOBAL STATE
# ══════════════════════════════════════════════════════════
S = {
    "connected":     False,
    "account":       {},
    "positions":     [],
    "trades":        [],
    "analyses":      {},          # sym -> {df, analysis}
    "goal":          {},
    "log":           [],
    "start_balance": 100.0,
    "daily_start":   100.0,
    "daily_profit":  0.0,
    "last_update":   None,
}
LOCK = threading.Lock()


def log(msg, level="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    with LOCK:
        S["log"].insert(0, {"ts": ts, "msg": msg, "level": level})
        S["log"] = S["log"][:60]
    print(f"[{ts}] {msg}")


# ══════════════════════════════════════════════════════════
#  MT5 CONNECT + INITIAL LOAD
# ══════════════════════════════════════════════════════════

def load_symbol(sym):
    """Load OHLCV + run full analysis for one symbol."""
    try:
        df = mt5c.get_ohlcv(sym, "H1", bars=500)
        if df is None or len(df) < 210:
            log(f"Not enough data for {sym}", "warning")
            return
        analysis = ind_engine.analyze(df)
        with LOCK:
            S["analyses"][sym] = {"df": df, "analysis": analysis}
        sc = analysis.get("overall_score", 0)
        ac = analysis.get("action", "?")
        log(f"{sym}: score={sc:+.1f}  action={ac}", "info")
    except Exception as e:
        log(f"Error loading {sym}: {e}", "warning")


def initial_load():
    """Synchronous first load - called before server starts."""
    log("Connecting to MT5...")
    if not mt5c.connect():
        log("MT5 connect FAILED", "danger")
        return False

    acc = mt5c.get_account_info()
    if not acc:
        log("No account info", "danger")
        return False

    bal = acc.get("balance", 100)
    with LOCK:
        S["connected"]     = True
        S["account"]       = acc
        S["start_balance"] = bal
        S["daily_start"]   = bal

    log(f"Connected: #{acc.get('login')} | ${bal:.2f} | {acc.get('server')}", "success")

    # Load all symbols
    avail = mt5c.check_symbols(SYMBOLS)
    log(f"Symbols: {avail}")
    for sym in avail:
        log(f"Loading {sym}...")
        load_symbol(sym)

    # Positions & trades
    pos    = mt5c.get_open_positions(magic=TRADING["magic_number"])
    trades = mt5c.get_trade_history(days=7)
    daily  = acc.get("balance", 0) - S["daily_start"]
    goal   = rm.check_goal_status(acc, S["start_balance"], daily)

    with LOCK:
        S["positions"]   = pos
        S["trades"]      = trades
        S["daily_profit"]= daily
        S["goal"]        = goal
        S["last_update"] = datetime.now()

    log(f"Initial load done. {len(avail)} symbols, {len(pos)} positions", "success")
    return True


def background_refresh():
    """Refresh every 30s in background."""
    while True:
        time.sleep(30)
        try:
            if not S["connected"]:
                continue
            acc    = mt5c.get_account_info()
            pos    = mt5c.get_open_positions(magic=TRADING["magic_number"])
            trades = mt5c.get_trade_history(days=7)
            daily  = acc.get("balance", 0) - S["daily_start"]
            goal   = rm.check_goal_status(acc, S["start_balance"], daily)

            for sym in list(S["analyses"].keys()):
                load_symbol(sym)

            with LOCK:
                S["account"]      = acc
                S["positions"]    = pos
                S["trades"]       = trades
                S["daily_profit"] = daily
                S["goal"]         = goal
                S["last_update"]  = datetime.now()
            log("Refreshed", "info")
        except Exception as e:
            log(f"Refresh err: {e}", "warning")


# ══════════════════════════════════════════════════════════
#  CHART HELPERS
# ══════════════════════════════════════════════════════════

def empty_fig(msg="No data"):
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor=CARD, plot_bgcolor=CARD, height=400,
        margin=dict(l=10,r=10,t=10,b=10), font=dict(color=TEXT),
        annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                          font=dict(color=MUTED, size=14), xref="paper", yref="paper")]
    )
    return fig


def sig_color(sig):
    return {
        "BUY": GREEN, "SELL": RED, "NEUTRAL": YEL, "WAIT": MUTED
    }.get(str(sig), MUTED)


def make_main_chart(sym):
    data = S["analyses"].get(sym)
    if not data:
        return empty_fig(f"Loading {sym}... please wait")

    df  = data["df"].tail(150).copy()
    an  = data["analysis"]
    ind = an.get("indicators", {})
    close = df["close"].values.astype(float)
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    vol   = df["volume"].values.astype(float)

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.55, 0.15, 0.15, 0.15],
    )

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="Price",
        increasing_fillcolor=GREEN, decreasing_fillcolor=RED,
        increasing_line_color=GREEN, decreasing_line_color=RED,
        line_width=1,
    ), row=1, col=1)

    # EMAs
    for period, color, name in [(20,"#f0c040","EMA20"),(50,"#58a6ff","EMA50"),(200,"#bc8cff","EMA200")]:
        if len(close) >= period:
            ema = talib.EMA(close, period)
            fig.add_trace(go.Scatter(x=df.index, y=ema, name=name,
                line=dict(color=color, width=1.3),
                hoverinfo="skip"), row=1, col=1)

    # Bollinger Bands
    if len(close) >= 20:
        bb_u, bb_m, bb_l = talib.BBANDS(close, 20, 2, 2)
        fig.add_trace(go.Scatter(x=df.index, y=bb_u, name="BB Upper",
            line=dict(color=MUTED, width=0.8, dash="dash"), hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=bb_l, name="BB Lower",
            line=dict(color=MUTED, width=0.8, dash="dash"),
            fill="tonexty", fillcolor="rgba(139,148,158,0.06)",
            hoverinfo="skip"), row=1, col=1)

    # RSI
    if len(close) >= 14:
        rsi = talib.RSI(close, 14)
        fig.add_trace(go.Scatter(x=df.index, y=rsi, name="RSI",
            line=dict(color=PUR, width=1.5)), row=2, col=1)
        for lvl, col in [(70, RED), (30, GREEN), (50, MUTED)]:
            fig.add_hline(y=lvl, line_color=col, line_dash="dot",
                          line_width=0.8, row=2, col=1)

    # MACD
    if len(close) >= 26:
        ml, sl2, hist = talib.MACD(close, 12, 26, 9)
        hcolors = [GREEN if (v or 0) >= 0 else RED for v in hist]
        fig.add_trace(go.Bar(x=df.index, y=hist, name="Hist",
            marker_color=hcolors, opacity=0.7, showlegend=False), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=ml,  name="MACD",
            line=dict(color=BLUE,  width=1.2)), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=sl2, name="Signal",
            line=dict(color=YEL, width=1.2)), row=3, col=1)

    # Volume
    vcols = [GREEN if c >= o else RED
             for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["volume"], name="Vol",
        marker_color=vcols, opacity=0.6, showlegend=False), row=4, col=1)

    cur    = float(close[-1])
    score  = an.get("overall_score", 0)
    action = an.get("action", "WAIT")
    ac     = sig_color(action)

    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG, height=530,
        margin=dict(l=50, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.02, x=0,
                    font=dict(size=10, color=MUTED), bgcolor="rgba(0,0,0,0)"),
        xaxis_rangeslider_visible=False,
        font=dict(color=TEXT, size=11),
        title=dict(
            text=f"<b>{sym}</b>  {cur:,.5f if cur < 10000 else ',.2f'}  |  Score: {score:+.0f}  |  Action: <b>{action}</b>",
            font=dict(size=13, color=ac), x=0.01,
        ),
    )
    for r in range(1, 5):
        fig.update_xaxes(gridcolor=BORD, showgrid=True, row=r, col=1, zeroline=False)
        fig.update_yaxes(gridcolor=BORD, showgrid=True, row=r, col=1, zeroline=False)

    return fig


def make_radar(sym):
    data = S["analyses"].get(sym)
    if not data:
        return empty_fig("Loading...")

    ind  = data["analysis"].get("indicators", {})
    cats = ["EMA","Ichimoku","RSI","MACD","Stoch","CCI","Williams",
            "MFI","BB","Keltner","ADX","Aroon","Patterns","S/R"]
    keys = ["ema","ichimoku","rsi","macd","stochastic","cci","williams",
            "mfi","bollinger","keltner","adx","aroon","patterns","sr"]

    vals = [(ind.get(k,{}).get("score") or 0) for k in keys]
    norm = [(v + 1) / 2 for v in vals]   # -1..1 → 0..1

    fig = go.Figure(go.Scatterpolar(
        r=norm + [norm[0]], theta=cats + [cats[0]],
        fill="toself",
        line=dict(color=BLUE, width=2),
        fillcolor="rgba(88,166,255,0.18)",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor=CARD,
            radialaxis=dict(visible=True, range=[0,1], gridcolor=BORD,
                            showticklabels=False, tickfont=dict(size=8)),
            angularaxis=dict(gridcolor=BORD, tickfont=dict(size=10, color=TEXT)),
        ),
        paper_bgcolor=CARD, plot_bgcolor=CARD,
        height=330, margin=dict(l=55,r=55,t=35,b=10),
        showlegend=False, font=dict(color=TEXT),
        title=dict(text="Indicator Radar", font=dict(size=12, color=MUTED), x=0.5),
    )
    return fig


def make_gauge(val, title, suffix="", lo=0, hi=100,
               good_lo=60, bad_hi=30, invert=False):
    if val is None: val = 0
    if invert:
        color = RED if val >= good_lo else GREEN if val <= bad_hi else YEL
    else:
        color = GREEN if val >= good_lo else RED if val <= bad_hi else YEL

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=val,
        number=dict(suffix=suffix, font=dict(color=color, size=30)),
        title=dict(text=title, font=dict(color=MUTED, size=11)),
        gauge=dict(
            axis=dict(range=[lo, hi], tickcolor=MUTED, tickfont=dict(size=8)),
            bar=dict(color=color, thickness=0.3),
            bgcolor=BORD, borderwidth=0,
            steps=[
                dict(range=[lo, bad_hi],  color="#200d0d"),
                dict(range=[bad_hi, good_lo], color="#1a1f26"),
                dict(range=[good_lo, hi], color="#0d200d"),
            ],
        ),
    ))
    fig.update_layout(
        paper_bgcolor=CARD, height=190,
        margin=dict(l=20, r=20, t=50, b=5),
        font=dict(color=TEXT),
    )
    return fig


def make_pnl_chart():
    trades = S.get("trades", [])
    if not trades:
        return empty_fig("No trade history yet")
    df = pd.DataFrame(trades).sort_values("time")
    df["cum"] = df["profit"].cumsum()
    final_color = GREEN if df["cum"].iloc[-1] >= 0 else RED

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.04, row_heights=[0.6, 0.4])
    fig.add_trace(go.Scatter(x=df["time"], y=df["cum"], name="Cumulative",
        fill="tozeroy", fillcolor=f"rgba({'63,185,80' if df['cum'].iloc[-1]>=0 else '248,81,73'},0.15)",
        line=dict(color=final_color, width=2)), row=1, col=1)
    bcolors = [GREEN if p >= 0 else RED for p in df["profit"]]
    fig.add_trace(go.Bar(x=df["time"], y=df["profit"], name="Trade P/L",
        marker_color=bcolors, opacity=0.8), row=2, col=1)
    fig.update_layout(
        paper_bgcolor=CARD, plot_bgcolor=CARD, height=260,
        margin=dict(l=50,r=10,t=10,b=10), font=dict(color=TEXT, size=10),
        legend=dict(font=dict(size=10)),
    )
    for r in range(1, 3):
        fig.update_xaxes(gridcolor=BORD, row=r, col=1)
        fig.update_yaxes(gridcolor=BORD, row=r, col=1)
    return fig


# ══════════════════════════════════════════════════════════
#  APP LAYOUT
# ══════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.CYBORG],
    title="MT5 Bot",
    update_title=None,
    suppress_callback_exceptions=True,
)

def kpi(icon, title, val, sub="", color=TEXT):
    return html.Div([
        html.Div(f"{icon} {title}", style={"color": MUTED, "fontSize": "11px", "marginBottom": "3px"}),
        html.Div(val,  style={"color": color, "fontSize": "21px", "fontWeight": "700"}),
        html.Div(sub,  style={"color": MUTED, "fontSize": "10px", "marginTop": "2px"}),
    ], style={**CS, "flex": "1", "minWidth": "130px", "padding": "12px 14px", "marginBottom": "0"})


def badge(sig):
    c = sig_color(sig)
    return html.Span(str(sig), style={
        "background": f"{c}22", "color": c, "border": f"1px solid {c}55",
        "borderRadius": "4px", "padding": "2px 8px",
        "fontSize": "11px", "fontWeight": "700",
    })


app.layout = html.Div(
    style={"backgroundColor": BG, "minHeight": "100vh",
           "fontFamily": "Consolas, monospace", "color": TEXT},
    children=[
        dcc.Interval(id="iv5",  interval=5_000,  n_intervals=0),
        dcc.Interval(id="iv30", interval=30_000, n_intervals=0),

        # ── NAV ─────────────────────────────────────────
        html.Div(style={
            "backgroundColor": CARD, "borderBottom": f"1px solid {BORD}",
            "padding": "10px 20px", "display": "flex",
            "justifyContent": "space-between", "alignItems": "center",
            "position": "sticky", "top": 0, "zIndex": 999,
        }, children=[
            html.Div([
                html.Span("🤖", style={"fontSize": "20px", "marginRight": "8px"}),
                html.Span("MT5 Trading Bot",
                          style={"color": BLUE, "fontWeight": "700", "fontSize": "17px"}),
                html.Span(" | بوت التداول",
                          style={"color": MUTED, "fontSize": "12px", "marginLeft": "8px"}),
            ], style={"display": "flex", "alignItems": "center"}),
            html.Div([
                html.Span(id="nav-conn", style={"marginRight": "16px", "fontSize": "12px"}),
                html.Span(id="nav-time", style={"color": MUTED, "fontSize": "11px"}),
            ]),
        ]),

        # ── BODY ────────────────────────────────────────
        html.Div(style={"padding": "14px 18px"}, children=[

            # KPI row
            html.Div(id="kpi-row",
                     style={"display": "flex", "gap": "10px",
                            "flexWrap": "wrap", "marginBottom": "12px"}),

            # Goal bar
            html.Div(id="goal-bar", style={"marginBottom": "12px"}),

            # Tabs
            html.Div(dcc.Tabs(id="tabs", value=SYMBOLS[0], children=[
                dcc.Tab(label=f"🥇 {s}", value=s,
                    style={"backgroundColor": BG, "color": MUTED,
                           "border": "none", "padding": "7px 18px", "fontSize": "12px"},
                    selected_style={"backgroundColor": ACC, "color": "white",
                                    "border": "none", "padding": "7px 18px", "fontSize": "12px"})
                for s in SYMBOLS
            ], style={"backgroundColor": CARD, "border": f"1px solid {BORD}",
                      "borderRadius": "8px 8px 0 0"})),

            # Main chart
            html.Div(dcc.Graph(id="main-chart",
                               config={"displayModeBar": True, "scrollZoom": True,
                                       "modeBarButtonsToRemove": ["lasso2d","select2d"]}),
                     style={**CS, "borderRadius": "0 0 8px 8px",
                            "padding": "6px", "marginTop": "0", "marginBottom": "12px"}),

            # Middle row: Radar | Indicators | Gauges+Controls
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "1fr 1fr 0.9fr",
                            "gap": "12px", "marginBottom": "12px"}, children=[

                # Radar
                html.Div(dcc.Graph(id="radar",
                                   config={"displayModeBar": False}), style=CS),

                # Indicator table
                html.Div([
                    html.Div("📋 All Indicators",
                             style={"fontWeight": "700", "color": BLUE,
                                    "marginBottom": "8px", "fontSize": "13px"}),
                    html.Div(id="ind-table",
                             style={"overflowY": "auto", "maxHeight": "310px"}),
                ], style=CS),

                # Gauges
                html.Div([
                    html.Div(style={"display": "grid",
                                    "gridTemplateColumns": "1fr 1fr", "gap": "6px"}, children=[
                        html.Div(dcc.Graph(id="g-rsi",  config={"displayModeBar": False}), style={**CS, "padding": "4px", "marginBottom": "0"}),
                        html.Div(dcc.Graph(id="g-adx",  config={"displayModeBar": False}), style={**CS, "padding": "4px", "marginBottom": "0"}),
                        html.Div(dcc.Graph(id="g-conf", config={"displayModeBar": False}), style={**CS, "padding": "4px", "marginBottom": "0"}),
                        html.Div(dcc.Graph(id="g-goal", config={"displayModeBar": False}), style={**CS, "padding": "4px", "marginBottom": "0"}),
                    ]),
                ]),
            ]),

            # Trade controls + positions
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "0.7fr 1.3fr",
                            "gap": "12px", "marginBottom": "12px"}, children=[

                # Controls
                html.Div([
                    html.Div("⚡ Manual Trade",
                             style={"fontWeight": "700", "color": BLUE,
                                    "marginBottom": "10px", "fontSize": "13px"}),
                    html.Div([
                        html.Div("Symbol", style={"fontSize": "11px", "color": MUTED, "marginBottom": "3px"}),
                        dcc.Dropdown(id="t-sym", value=SYMBOLS[0],
                            options=[{"label": s, "value": s} for s in SYMBOLS],
                            style={"fontSize": "12px"},
                            className="dark-dropdown"),
                    ], style={"marginBottom": "8px"}),
                    html.Div([
                        html.Div("Lot Size", style={"fontSize": "11px", "color": MUTED, "marginBottom": "3px"}),
                        dcc.Input(id="t-lot", type="number", value=0.01,
                                  min=0.01, max=0.1, step=0.01,
                                  style={"width": "100%", "backgroundColor": BORD,
                                         "color": TEXT, "border": f"1px solid {BORD}55",
                                         "borderRadius": "4px", "padding": "6px 8px",
                                         "fontFamily": "inherit"}),
                    ], style={"marginBottom": "8px"}),
                    dcc.RadioItems(id="t-mode",
                        options=[{"label": " Dry Run", "value": "dry"},
                                 {"label": " Live",    "value": "live"}],
                        value="dry",
                        style={"fontSize": "12px", "color": TEXT, "marginBottom": "12px"},
                        labelStyle={"display": "block", "marginBottom": "4px"},
                    ),
                    html.Div([
                        html.Button("▲ BUY", id="btn-buy", n_clicks=0, style={
                            "flex": "1", "backgroundColor": "#1a3d28",
                            "color": GREEN, "border": f"2px solid {GREEN}",
                            "borderRadius": "6px", "padding": "10px",
                            "fontWeight": "800", "fontSize": "14px",
                            "cursor": "pointer", "fontFamily": "inherit",
                        }),
                        html.Button("▼ SELL", id="btn-sell", n_clicks=0, style={
                            "flex": "1", "backgroundColor": "#3d1a1a",
                            "color": RED, "border": f"2px solid {RED}",
                            "borderRadius": "6px", "padding": "10px",
                            "fontWeight": "800", "fontSize": "14px",
                            "cursor": "pointer", "fontFamily": "inherit",
                        }),
                    ], style={"display": "flex", "gap": "8px", "marginBottom": "8px"}),
                    html.Button("✖ Close All Positions", id="btn-close", n_clicks=0, style={
                        "width": "100%", "backgroundColor": BORD,
                        "color": MUTED, "border": f"1px solid {BORD}",
                        "borderRadius": "6px", "padding": "7px",
                        "cursor": "pointer", "fontSize": "12px", "fontFamily": "inherit",
                    }),
                    html.Div(id="trade-out",
                             style={"marginTop": "10px", "fontSize": "12px",
                                    "minHeight": "20px"}),
                ], style=CS),

                # Positions
                html.Div([
                    html.Div("💼 Open Positions",
                             style={"fontWeight": "700", "color": BLUE,
                                    "marginBottom": "8px", "fontSize": "13px"}),
                    html.Div(id="pos-table"),
                ], style=CS),
            ]),

            # P&L chart + signals table
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "1fr 1fr",
                            "gap": "12px", "marginBottom": "12px"}, children=[
                html.Div([
                    html.Div("📊 P&L History",
                             style={"fontWeight": "700", "color": BLUE,
                                    "marginBottom": "6px", "fontSize": "13px"}),
                    dcc.Graph(id="pnl-chart", config={"displayModeBar": False}),
                ], style=CS),
                html.Div([
                    html.Div("🔍 Market Signals Summary",
                             style={"fontWeight": "700", "color": BLUE,
                                    "marginBottom": "8px", "fontSize": "13px"}),
                    html.Div(id="sig-table"),
                ], style=CS),
            ]),

            # Event log
            html.Div([
                html.Div("📝 Event Log",
                         style={"fontWeight": "700", "color": BLUE,
                                "marginBottom": "6px", "fontSize": "13px"}),
                html.Div(id="ev-log",
                         style={"height": "160px", "overflowY": "auto",
                                "fontSize": "11px", "lineHeight": "1.9",
                                "fontFamily": "Consolas, monospace"}),
            ], style=CS),
        ]),
    ]
)


# ══════════════════════════════════════════════════════════
#  CALLBACKS
# ══════════════════════════════════════════════════════════

@app.callback(Output("nav-conn","children"), Output("nav-time","children"),
              Input("iv5","n_intervals"))
def cb_nav(n):
    acc  = S.get("account", {})
    conn = S.get("connected", False)
    bal  = acc.get("balance", 0)
    login= acc.get("login", "?")
    up   = S.get("last_update")
    up_s = up.strftime("%H:%M:%S") if up else "--"

    dot  = "🟢" if conn else "🔴"
    conn_el = html.Span(f"{dot} #{login} │ ${bal:.2f} │ upd {up_s}",
                        style={"color": GREEN if conn else RED, "fontSize": "12px"})
    return conn_el, datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.callback(Output("kpi-row","children"), Input("iv5","n_intervals"))
def cb_kpi(n):
    acc   = S.get("account", {})
    goal  = S.get("goal", {})
    pos   = S.get("positions", [])
    trades= S.get("trades", [])

    bal    = acc.get("balance",    0)
    eq     = acc.get("equity",     0)
    oprof  = acc.get("profit",     0)
    daily  = S.get("daily_profit", 0)
    tot_p  = goal.get("total_profit",     0)
    target = goal.get("target_usd",      20)
    prog   = goal.get("progress",         0)
    mf     = acc.get("margin_free",       0)
    ml     = acc.get("margin_level",      0)

    def pc(v): return GREEN if v >= 0 else RED

    return [
        kpi("💰", "Balance",      f"${bal:.2f}",    f"Start: ${S['start_balance']:.2f}"),
        kpi("📊", "Equity",       f"${eq:.2f}",     f"Free: ${mf:.2f}"),
        kpi("📈", "Open P/L",     f"${oprof:+.2f}", f"{len(pos)} open",
            color=pc(oprof)),
        kpi("📅", "Daily P/L",    f"${daily:+.2f}", "Today",
            color=pc(daily)),
        kpi("🎯", "Total Profit", f"${tot_p:+.2f}", f"{goal.get('total_profit_pct',0):.1f}%",
            color=pc(tot_p)),
        kpi("🏁", "Goal Target",  f"${target:.2f}", f"{prog:.0f}% done", color=BLUE),
        kpi("🔢", "Trades",       str(len(trades)), "Last 7 days",    color=PUR),
        kpi("📉", "Margin Level", f"{ml:.0f}%",     acc.get("server","?"), color=CYAN),
    ]


@app.callback(Output("goal-bar","children"), Input("iv5","n_intervals"))
def cb_goal(n):
    goal   = S.get("goal", {})
    prog   = goal.get("progress", 0)
    status = goal.get("status",   "ACTIVE")
    tot_p  = goal.get("total_profit",  0)
    target = goal.get("target_usd",   20)
    daily  = S.get("daily_profit",     0)
    max_l  = GOAL.get("max_loss_usd", 10)

    sc = {
        "GOAL_ACHIEVED": GREEN, "STOP_LOSS": RED,
        "DAILY_LIMIT": YEL, "ACTIVE": BLUE,
    }.get(status, BLUE)

    d_prog = min(100, max(0, daily / max(GOAL.get("daily_target_usd", 5), 0.01) * 100))

    return html.Div([
        html.Div(style={"display":"flex","justifyContent":"space-between","marginBottom":"5px"}, children=[
            html.Span([
                html.Span("🎯 Goal: ", style={"color": MUTED}),
                html.Span(f"${tot_p:+.2f} / ${target:.2f}", style={"color": sc, "fontWeight": "700"}),
                html.Span(f"   Status: ", style={"color": MUTED, "marginLeft": "16px"}),
                html.Span(status, style={"color": sc, "fontWeight": "700"}),
            ]),
            html.Span(f"{prog:.1f}%", style={"color": sc, "fontWeight": "700"}),
        ]),
        # Main progress bar
        html.Div(style={"backgroundColor": BORD, "borderRadius": "4px",
                        "height": "10px", "marginBottom": "8px", "overflow": "hidden"},
                 children=[html.Div(style={
                     "backgroundColor": sc, "height": "100%",
                     "width": f"{max(0,min(100,prog))}%", "borderRadius": "4px",
                     "transition": "width 0.5s",
                 })]),
        # Daily bar
        html.Div(style={"display":"flex","alignItems":"center","gap":"10px"}, children=[
            html.Span(f"Daily: ${daily:+.2f} / ${GOAL.get('daily_target_usd',5):.2f}",
                      style={"fontSize": "11px", "color": MUTED}),
            html.Div(style={"flex":"1","backgroundColor":BORD,"borderRadius":"3px",
                            "height":"6px","overflow":"hidden","maxWidth":"200px"}, children=[
                html.Div(style={"backgroundColor": CYAN, "height": "100%",
                                "width": f"{d_prog:.0f}%", "borderRadius": "3px"})
            ]),
            html.Span(f"Max Loss: ${max_l:.2f}", style={"fontSize": "11px", "color": RED}),
        ]),
    ], style=CS)


@app.callback(
    Output("main-chart","figure"),
    Output("radar","figure"),
    Input("tabs","value"),
    Input("iv30","n_intervals"),
    Input("iv5","n_intervals"),
)
def cb_charts(sym, n30, n5):
    return make_main_chart(sym), make_radar(sym)


@app.callback(
    Output("g-rsi","figure"), Output("g-adx","figure"),
    Output("g-conf","figure"), Output("g-goal","figure"),
    Input("tabs","value"), Input("iv5","n_intervals"),
)
def cb_gauges(sym, n):
    data  = S["analyses"].get(sym, {})
    an    = data.get("analysis", {}) if data else {}
    ind   = an.get("indicators", {})
    rsi_v = ind.get("rsi",{}).get("value") or 50
    adx_v = ind.get("adx",{}).get("adx")   or 0
    conf  = an.get("confidence", 0)
    prog  = S.get("goal", {}).get("progress", 0)

    return (
        make_gauge(rsi_v, "RSI(14)", "", 0, 100, 60, 30),
        make_gauge(adx_v, "ADX Trend", "", 0, 80, 25, 10),
        make_gauge(conf,  "Signal Conf", "%", 0, 100, 65, 30),
        make_gauge(prog,  "Goal Progress", "%", 0, 100, 80, 20),
    )


@app.callback(Output("ind-table","children"),
              Input("tabs","value"), Input("iv5","n_intervals"))
def cb_ind_table(sym, n):
    data = S["analyses"].get(sym)
    if not data:
        return html.Div("Loading...", style={"color": MUTED, "fontSize": "12px"})

    ind = data["analysis"].get("indicators", {})
    rows_data = [
        ("EMA 20/50/200", ind.get("ema",{})),
        ("Ichimoku",      ind.get("ichimoku",{})),
        ("RSI (14)",      ind.get("rsi",{})),
        ("MACD",          ind.get("macd",{})),
        ("Stochastic",    ind.get("stochastic",{})),
        ("CCI (20)",      ind.get("cci",{})),
        ("Williams %R",   ind.get("williams",{})),
        ("MFI (14)",      ind.get("mfi",{})),
        ("ROC (10)",      ind.get("roc",{})),
        ("Bollinger BB",  ind.get("bollinger",{})),
        ("ATR (14)",      ind.get("atr",{})),
        ("Keltner Ch.",   ind.get("keltner",{})),
        ("Donchian (20)", ind.get("donchian",{})),
        ("ADX (14)",      ind.get("adx",{})),
        ("Aroon (25)",    ind.get("aroon",{})),
        ("OBV",           ind.get("obv",{})),
        ("Patterns",      ind.get("patterns",{})),
        ("Support/Res.",  ind.get("sr",{})),
    ]

    def fmt(d):
        v = (d.get("detail") or d.get("value") or
             d.get("adx")   or d.get("osc"))
        if v is None: return "-"
        if isinstance(v, float): return f"{v:.4f}"
        return str(v)[:28]

    thead = html.Thead(html.Tr([
        html.Th(h, style={"color": MUTED, "padding": "2px 8px",
                          "fontSize": "10px", "fontWeight": "400",
                          "borderBottom": f"1px solid {BORD}"})
        for h in ["Indicator", "Value", "Signal"]
    ]))
    tbody = html.Tbody([
        html.Tr([
            html.Td(name,       style={"padding":"3px 8px","fontSize":"11px","color":MUTED}),
            html.Td(fmt(d),     style={"padding":"3px 8px","fontSize":"11px",
                                       "fontFamily":"Consolas,monospace"}),
            html.Td(badge(d.get("signal","?")), style={"padding":"3px 8px"}),
        ]) for name, d in rows_data
    ])
    return html.Table([thead, tbody],
                      style={"width":"100%","borderCollapse":"collapse"})


@app.callback(Output("pos-table","children"), Input("iv5","n_intervals"))
def cb_positions(n):
    pos = S.get("positions", [])
    if not pos:
        return html.Div("No open positions",
                        style={"color": MUTED, "textAlign": "center",
                               "padding": "20px", "fontSize": "12px"})
    hdrs = ["Ticket","Symbol","Type","Lots","Entry","Current","P/L","SL","TP"]
    rows = []
    for p in pos:
        pl   = p.get("profit", 0)
        tc   = GREEN if p["type"] == "BUY" else RED
        plc  = GREEN if pl >= 0 else RED
        rows.append(html.Tr([
            html.Td(str(p["ticket"])[:7],          style={"padding":"3px 8px","fontSize":"11px","color":MUTED}),
            html.Td(p["symbol"],                   style={"padding":"3px 8px","fontSize":"11px"}),
            html.Td(p["type"],                     style={"padding":"3px 8px","fontSize":"11px","color":tc,"fontWeight":"700"}),
            html.Td(str(p["volume"]),              style={"padding":"3px 8px","fontSize":"11px"}),
            html.Td(f"{p['open_price']:.5f}",      style={"padding":"3px 8px","fontSize":"11px","fontFamily":"Consolas"}),
            html.Td(f"{p['current_price']:.5f}",   style={"padding":"3px 8px","fontSize":"11px","fontFamily":"Consolas"}),
            html.Td(f"${pl:+.2f}",                 style={"padding":"3px 8px","fontSize":"11px","color":plc,"fontWeight":"700"}),
            html.Td(f"{p['sl']:.5f}" if p["sl"] else "-", style={"padding":"3px 8px","fontSize":"11px","color":RED}),
            html.Td(f"{p['tp']:.5f}" if p["tp"] else "-", style={"padding":"3px 8px","fontSize":"11px","color":GREEN}),
        ]))
    return html.Table(
        [html.Thead(html.Tr([
            html.Th(h, style={"color":MUTED,"padding":"3px 8px","fontSize":"10px",
                              "fontWeight":"400","borderBottom":f"1px solid {BORD}"})
            for h in hdrs
        ])), html.Tbody(rows)],
        style={"width":"100%","borderCollapse":"collapse"}
    )


@app.callback(Output("pnl-chart","figure"), Input("iv30","n_intervals"))
def cb_pnl(n): return make_pnl_chart()


@app.callback(Output("sig-table","children"), Input("iv5","n_intervals"))
def cb_sig_table(n):
    hdrs = ["Symbol","Price","RSI","EMA","ADX","Stoch","BB","Score","Action"]
    rows = []
    for sym in SYMBOLS:
        data = S["analyses"].get(sym)
        if not data:
            rows.append(html.Tr([html.Td(sym, style={"padding":"4px 10px","fontSize":"12px"})] +
                                 [html.Td("-", style={"padding":"4px 10px","fontSize":"12px"}) for _ in range(8)]))
            continue
        an  = data["analysis"]
        ind = an.get("indicators", {})
        rsi_v = ind.get("rsi",{}).get("value") or 0
        ema_s = ind.get("ema",{}).get("signal","?")
        adx_v = ind.get("adx",{}).get("adx") or 0
        stk   = ind.get("stochastic",{}).get("k") or 0
        bb_s  = ind.get("bollinger",{}).get("signal","?")
        score = an.get("overall_score", 0)
        action= an.get("action","?")
        price = an.get("current_price", 0)
        pr_s  = f"{price:.5f}" if price < 10000 else f"{price:,.2f}"

        ac    = sig_color(action)
        rows.append(html.Tr([
            html.Td(sym,                    style={"padding":"5px 10px","fontSize":"12px","color":CYAN,"fontWeight":"700"}),
            html.Td(pr_s,                   style={"padding":"5px 10px","fontSize":"11px","fontFamily":"Consolas"}),
            html.Td(f"{rsi_v:.0f}",         style={"padding":"5px 10px","fontSize":"11px",
                                                    "color": RED if rsi_v>70 else GREEN if rsi_v<30 else TEXT}),
            html.Td(badge(ema_s),           style={"padding":"5px 10px"}),
            html.Td(f"{adx_v:.0f}",         style={"padding":"5px 10px","fontSize":"11px",
                                                    "color": GREEN if adx_v>25 else MUTED}),
            html.Td(f"{stk:.0f}",           style={"padding":"5px 10px","fontSize":"11px"}),
            html.Td(badge(bb_s),            style={"padding":"5px 10px"}),
            html.Td(f"{score:+.0f}",        style={"padding":"5px 10px","fontSize":"11px","fontWeight":"700",
                                                    "color": GREEN if score>0 else RED if score<0 else MUTED}),
            html.Td(badge(action),          style={"padding":"5px 10px"}),
        ]))

    return html.Table(
        [html.Thead(html.Tr([
            html.Th(h, style={"color":MUTED,"padding":"4px 10px","fontSize":"10px",
                              "fontWeight":"400","borderBottom":f"1px solid {BORD}"})
            for h in hdrs
        ])), html.Tbody(rows)],
        style={"width":"100%","borderCollapse":"collapse"}
    )


@app.callback(Output("ev-log","children"), Input("iv5","n_intervals"))
def cb_log(n):
    lvl_colors = {"success": GREEN, "danger": RED, "warning": YEL, "info": MUTED}
    return [
        html.Div([
            html.Span(f"[{l['ts']}] ", style={"color": BORD}),
            html.Span(l["msg"], style={"color": lvl_colors.get(l["level"], TEXT)}),
        ]) for l in S.get("log", [])
    ]


@app.callback(
    Output("trade-out","children"),
    Input("btn-buy","n_clicks"), Input("btn-sell","n_clicks"),
    Input("btn-close","n_clicks"),
    State("t-sym","value"), State("t-lot","value"), State("t-mode","value"),
    prevent_initial_call=True,
)
def cb_trade(buy, sell, close_all, sym, lot, mode):
    tid = ctx.triggered_id
    if not tid: return ""
    dry = (mode == "dry")

    if tid == "btn-close":
        if dry:
            return html.Span("🔵 [DRY] Would close all", style={"color": BLUE})
        n = mt5c.close_all_positions(magic=TRADING["magic_number"])
        log(f"Closed {n} positions", "success")
        return html.Span(f"Closed {n} positions", style={"color": GREEN})

    action = "BUY" if tid == "btn-buy" else "SELL"
    lot = lot or 0.01

    if dry:
        msg = f"[DRY] {action} {lot} {sym}"
        log(msg, "info")
        return html.Span(f"🔵 {msg}", style={"color": BLUE})

    si    = mt5c.get_symbol_info(sym)
    data  = S["analyses"].get(sym, {})
    atr   = data.get("analysis",{}).get("indicators",{}).get("atr",{}).get("value") if data else None
    if not atr or not si:
        return html.Span("❌ No data for symbol", style={"color": RED})

    tick  = mt5c.get_symbol_info(sym)
    entry = tick["ask"] if action == "BUY" else tick["bid"]
    sl, tp = rm.calculate_sl_tp(si, action, entry, atr)
    res   = mt5c.place_order(sym, action, lot, sl, tp)

    if res.get("success"):
        msg = f"Ticket #{res['ticket']}"
        log(f"{action} {lot} {sym} @ {res['price']:.5f}", "success")
        return html.Span(f"✅ {action} done! {msg}", style={"color": GREEN})
    else:
        log(f"Order failed: {res.get('error')}", "danger")
        return html.Span(f"❌ {res.get('error')}", style={"color": RED})


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 55)
    print("  MT5 Trading Bot - Web Dashboard")
    print("  http://localhost:8050")
    print("=" * 55)

    # Load all data FIRST (synchronous)
    print("Loading MT5 data...")
    ok = initial_load()
    if not ok:
        print("WARNING: MT5 data not loaded. Dashboard will show partial data.")

    # Start background refresh thread
    t = threading.Thread(target=background_refresh, daemon=True)
    t.start()

    # Open browser after 1.5s
    def _open():
        time.sleep(1.5)
        webbrowser.open("http://localhost:8050")
    threading.Thread(target=_open, daemon=True).start()

    print("Starting server...")
    app.run(debug=False, host="0.0.0.0", port=8050)
