"""
TFG — Rodalies de Catalunya: Deteccio precoç d'incidencies via Twitter
App de visualitzacio amb Streamlit
"""

import os
import re
import base64
import datetime
from io import StringIO
import streamlit as st
import pandas as pd
import folium
from folium.plugins import HeatMap, MarkerCluster
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import json

DATA_START = "2025-01-01"

LINE_COLORS = {
    "R1": "#87CEEB", "R2": "#4CAF50", "R2N": "#90EE90", "R2S": "#006400",
    "R3": "#DC143C", "R4": "#00008B", "R7": "#8B008B", "R8": "#FF69B4",
}
CARACTER_COLORS = {"informatiu": "#3B82F6", "queixa": "#DC143C", "mixt": "#F59E0B"}
TIPO_COLORS = {
    "demora": "#F59E0B", "averia": "#DC143C", "obras": "#6366F1",
    "parada": "#10B981", "arrollamiento": "#7C3AED", "huelga": "#EC4899",
    "sin_incidencia": "#9CA3AF",
}
DEFAULT_COLOR = "#6B7280"
ALL_TIPOS = ["demora", "averia", "obras", "parada", "arrollamiento", "huelga"]

PATHS = {
    "csv":     r"C:\MARINA\Universitat\TFG - Visualització\Fonts\classificacio_estacions_ubicacions.csv",
    "json":    r"C:\MARINA\Universitat\TFG - Visualització\Fonts\stations_info.json",
    "csv_inc": r"C:\MARINA\Universitat\TFG - Visualització\Fonts\tweets_incidencias_final_juny.csv",
}

_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="52" height="52" viewBox="0 0 24 24"
  fill="none" stroke="#7dd3fc" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <rect x="4" y="3" width="16" height="16" rx="2.5"/>
  <path d="M4 11h16"/><path d="M12 3v8"/>
  <path d="M8 19l-2 3"/><path d="M16 19l2 3"/>
  <circle cx="8.5" cy="15.5" r="1.2" fill="#7dd3fc" stroke="none"/>
  <circle cx="15.5" cy="15.5" r="1.2" fill="#7dd3fc" stroke="none"/>
</svg>"""
_LOGO_B64 = base64.b64encode(_LOGO_SVG.encode()).decode()


# ══════════════════════════════════════════════════════════════════════════════
# CARREGA DE DADES
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data
def load_stations_json():
    with open(PATHS["json"], encoding="utf-8") as f:
        raw = json.load(f)
    lookup = {}
    for line, stations in raw.items():
        for s in stations:
            name = s["name"]
            if name not in lookup:
                lookup[name] = {"lat": s["lat"], "lon": s["lon"], "lines": []}
            if line not in lookup[name]["lines"]:
                lookup[name]["lines"].append(line)
    raw_sorted = {line: sorted(sts, key=lambda s: s["index"]) for line, sts in raw.items()}
    return lookup, raw_sorted


@st.cache_data
def load_tweets(file_mtime):
    df = pd.read_csv(PATHS["csv"], encoding="utf-8", low_memory=False)

    def parse_stations(s):
        try:
            if pd.isna(s) or str(s).strip() in ("[]", ""):
                return []
            return json.loads(s)
        except Exception:
            return []

    df["stations_parsed"] = df["stations_with_lines"].apply(parse_stations)
    hora_col = df["hora"].fillna("00:00").astype(str)
    df["timestamp"] = pd.to_datetime(
        df["timestamp"].astype(str) + " " + hora_col, errors="coerce"
    )
    df["date"]  = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["month"] = df["timestamp"].dt.to_period("M").astype(str)
    df["hour"]  = df["timestamp"].dt.hour
    df["lines_list"]    = df["lines_list"].fillna("")
    df["stations_list"] = df["stations_list"].fillna("")
    df["caracter"]      = df["caracter"].fillna("indeterminat")
    return df[df["date"] >= DATA_START].reset_index(drop=True)


@st.cache_data
def build_expanded(df_json, lookup_json, file_mtime):
    lookup = json.loads(lookup_json)
    df = pd.read_json(StringIO(df_json), convert_dates=False)
    rows = []
    for _, row in df.iterrows():
        parsed = row["stations_parsed"] if isinstance(row["stations_parsed"], list) else []
        for entry in parsed:
            name   = entry[0]
            lines_ = entry[1] if len(entry) > 1 else []
            info   = lookup.get(name)
            if info:
                rows.append({
                    "tweet_id":   row["tweet_id"],
                    "tweet_text": row["tweet_text"],
                    "timestamp":  row["timestamp"],
                    "date":       str(row["date"]),
                    "month":      str(row["month"]),
                    "hour":       row["hour"],
                    "idioma":     row["idioma"],
                    "caracter":   row["caracter"],
                    "lines_list": row["lines_list"],
                    "station":    name,
                    "lat":        info["lat"],
                    "lon":        info["lon"],
                    "line":       lines_[0] if lines_ else (info["lines"][0] if info["lines"] else ""),
                })
    return pd.DataFrame(rows)


@st.cache_data
def load_incidents(_file_mtime_inc):
    cols = ["id", "timestamp", "tweet_text", "tipo_incidencia",
            "confianza", "es_incidencia", "metodo"]
    df_i = pd.read_csv(PATHS["csv_inc"], encoding="utf-8",
                       low_memory=False, header=0, names=cols)
    df_i["timestamp"] = pd.to_datetime(df_i["timestamp"], errors="coerce")
    df_i["date"]      = df_i["timestamp"].dt.strftime("%Y-%m-%d")
    df_i["month"]     = df_i["timestamp"].dt.to_period("M").astype(str)
    df_i["hour"]      = df_i["timestamp"].dt.hour
    df_i["confianza"] = pd.to_numeric(df_i["confianza"], errors="coerce")
    metodo_rank = {"llm_confirm": 0, "rules": 1, "cache": 2, "rules_duda_no_ollama": 3, "empty": 4}
    df_i["_rank"] = df_i["metodo"].map(metodo_rank).fillna(9)
    df_i = (df_i.sort_values("_rank")
                .drop_duplicates(subset=["id"], keep="first")
                .drop(columns="_rank"))
    return df_i[df_i["date"] >= DATA_START].reset_index(drop=True)


# ── Carrega inicial ────────────────────────────────────────────────────────────
_mtime     = os.path.getmtime(PATHS["csv"])
_mtime_inc = os.path.getmtime(PATHS["csv_inc"])
station_lookup, stations_raw = load_stations_json()
df     = load_tweets(_mtime)
df_inc = load_incidents(_mtime_inc)
df_exp = build_expanded(
    df[["tweet_id", "tweet_text", "timestamp", "date", "month", "hour",
        "idioma", "caracter", "lines_list", "stations_parsed"]].to_json(),
    json.dumps(station_lookup),
    _mtime,
)

ALL_LINES     = sorted(LINE_COLORS.keys())
ALL_IDIOMES   = sorted(df["idioma"].dropna().unique())
ALL_CARACTERS = sorted(df["caracter"].dropna().unique())
ALL_DATES     = sorted(df["date"].dropna().unique())
ALL_MONTHS    = sorted(df["month"].dropna().unique())
INC_MONTHS    = sorted(df_inc["month"].dropna().unique())
ALL_DATES_DT  = [datetime.date.fromisoformat(d) for d in ALL_DATES if d and d != "NaT"]


# ── Helpers ────────────────────────────────────────────────────────────────────
def caracter_predominant(series):
    return series.value_counts().index[0] if len(series) > 0 else "—"


def apply_filters(src, lines=None, idiomes=None, caracters=None,
                  date_start=None, date_end=None, use_lines_list=False):
    mask = pd.Series(True, index=src.index)
    if lines:
        if use_lines_list:
            # Matching exacte per segment (evita R2 ↔ R2N)
            combined = "|".join(
                r"(?:(?:^|\|)" + re.escape(l) + r"(?:\||$))" for l in lines
            )
            mask &= src["lines_list"].str.contains(combined, na=False, regex=True)
        else:
            mask &= src["line"].isin(lines)
    if idiomes:
        mask &= src["idioma"].isin(idiomes)
    if caracters:
        mask &= src["caracter"].isin(caracters)
    if date_start:
        mask &= src["date"] >= date_start
    if date_end:
        mask &= src["date"] <= date_end
    return src[mask]


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG + CSS
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Anàlisi X · Rodalies", layout="wide", page_icon="🚆")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ══ BASE ══════════════════════════════════════════════════════ */
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
.stApp { background: #080e1a !important; }
.main  { background: #080e1a !important; }
.main .block-container {
    padding-top: 2.5rem !important;
    padding-bottom: 5rem !important;
    max-width: 1400px !important;
}
p, li { line-height: 1.75 !important; }
hr    { border-color: #1e293b !important; opacity: 1 !important; }

/* ══ SIDEBAR ═══════════════════════════════════════════════════ */
[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg, #050c1a 0%, #0f172a 60%, #1e293b 100%) !important;
    border-right: 1px solid #1e293b !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] div { color: #cbd5e1 !important; }

/* ══ TITOLS ════════════════════════════════════════════════════ */
h1 {
    font-size: 2.4rem !important;
    font-weight: 800 !important;
    letter-spacing: -1px !important;
    color: #f8fafc !important;
}
h2 {
    font-size: 1.15rem !important;
    font-weight: 600 !important;
    color: #e2e8f0 !important;
    border-left: 3px solid #7dd3fc !important;
    padding-left: 10px !important;
    margin-top: 1.4rem !important;
}
h3 { color: #cbd5e1 !important; font-weight: 600 !important; }

/* ══ METRIC CARDS ══════════════════════════════════════════════ */
[data-testid="metric-container"] {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
    border: 1px solid #334155 !important;
    border-radius: 12px !important;
    padding: 20px 24px !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3) !important;
    transition: all 0.2s ease !important;
}
[data-testid="metric-container"]:hover {
    border-color: #7dd3fc !important;
    box-shadow: 0 4px 24px rgba(125,211,252,0.12) !important;
    transform: translateY(-1px) !important;
}
[data-testid="stMetricLabel"] > div { color: #64748b !important; font-size: 11px !important; text-transform: uppercase !important; letter-spacing: 0.8px !important; }
[data-testid="stMetricValue"] > div { color: #f8fafc !important; font-size: 2rem !important; font-weight: 800 !important; letter-spacing: -1px !important; }
[data-testid="stMetricDelta"] svg   { display: none !important; }

/* ══ EXPANDERS ═════════════════════════════════════════════════ */
[data-testid="stExpander"] {
    background: #0f172a !important;
    border: 1px solid #1e293b !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    color: #94a3b8 !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 10px 16px !important;
}
[data-testid="stExpander"] summary:hover { color: #f1f5f9 !important; }

/* ══ INFO / ALERT ══════════════════════════════════════════════ */
[data-testid="stInfo"] {
    background: #0c2340 !important;
    border: none !important;
    border-left: 3px solid #3b82f6 !important;
    border-radius: 8px !important;
    color: #93c5fd !important;
    font-size: 13px !important;
}

/* ══ RADIO — SIDEBAR (menu net, sense pills) ══════════════════ */
[data-testid="stSidebar"] [data-testid="stRadio"] > div {
    gap: 1px !important;
    flex-direction: column !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    background: transparent !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 7px 12px !important;
    font-size: 14px !important;
    font-weight: 400 !important;
    color: #94a3b8 !important;
    transition: background 0.15s, color 0.15s !important;
    width: 100% !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: rgba(255,255,255,0.05) !important;
    color: #e2e8f0 !important;
    border: none !important;
}
/* Reduir gap general al sidebar */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0.2rem !important;
}

/* ══ RADIO — CONTINGUT PRINCIPAL (pills per filtres) ═══════════ */
[role="radiogroup"] {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 6px !important;
}
[role="radiogroup"] label {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 7px !important;
    padding: 5px 14px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
    cursor: pointer !important;
}
[role="radiogroup"] label:hover {
    border-color: #7dd3fc !important;
    color: #7dd3fc !important;
}
/* El label del widget (títol sobre els botons) no ha de tenir border */
[data-testid="stWidgetLabel"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
}
[data-testid="stWidgetLabel"] label {
    background: transparent !important;
    border: none !important;
    font-size: 13px !important;
    color: #64748b !important;
    padding: 0 !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.6px !important;
}

/* ══ WIDGETS (selectbox, number_input, date) ═══════════════════ */
[data-testid="stSelectbox"] > div > div,
[data-testid="stDateInput"] > div > div > input,
[data-testid="stNumberInput"] > div > div > input {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #f1f5f9 !important;
    font-size: 13px !important;
}
[data-testid="stSelectbox"] > div > div:hover,
[data-testid="stDateInput"] > div > div > input:focus,
[data-testid="stNumberInput"] > div > div > input:focus {
    border-color: #7dd3fc !important;
}

/* ══ DATAFRAME ═════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {
    border: 1px solid #1e293b !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* ══ DIVIDER ═══════════════════════════════════════════════════ */
[data-testid="stDivider"] { background: #1e293b !important; }

/* ══ HERO ══════════════════════════════════════════════════════ */
.hero-wrap  { display:flex; align-items:center; gap:24px; padding:32px 0 16px; }
.hero-title { font-size:2.4rem; font-weight:800; color:#f8fafc; margin:0; line-height:1.15; letter-spacing:-1px; }
.hero-sub   { font-size:1rem; color:#94a3b8; margin:6px 0 0; line-height:1.6; }
.hero-badge {
    display:inline-flex; align-items:center; gap:8px;
    background:linear-gradient(135deg,#1e293b,#0f172a); border:1px solid #334155;
    border-radius:20px; padding:5px 14px; font-size:12px; color:#7dd3fc;
    font-weight:600; margin-top:14px; box-shadow:0 2px 8px rgba(0,0,0,0.3);
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — navegació + filtres globals
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;padding:8px 0 4px">'
        f'<img src="data:image/svg+xml;base64,{_LOGO_B64}" width="44">'
        f'<div><div style="font-size:16px;font-weight:700;color:#f1f5f9">Anàlisi X · Rodalies</div>'
        f'<div style="font-size:11px;color:#64748b">Deteccio d\'incidencies</div></div></div>',
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Pagina",
        ["Inici", "Mapa geografic", "Analisi temporal",
         "Analisi per linies", "Analisi d'incidencies"],
        label_visibility="collapsed",
        key="nav_page",
    )

    st.markdown(
        "<div style='margin:6px 0 10px;border-top:1px solid #1e293b'></div>"
        "<div style='font-size:13px;font-weight:700;color:#94a3b8;"
        "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:14px'>"
        "Filtres globals</div>",
        unsafe_allow_html=True,
    )

    fil_lines     = st.pills("Linia",    ALL_LINES,     selection_mode="multi",
                              default=ALL_LINES,          key="fil_lines")
    fil_idiomes   = st.pills("Idioma",   ALL_IDIOMES,   selection_mode="multi",
                              default=list(ALL_IDIOMES),  key="fil_idiomes")
    fil_caracters = st.pills("Caracter", ALL_CARACTERS, selection_mode="multi",
                              default=list(ALL_CARACTERS), key="fil_caracters")

    fil_dates = st.date_input(
        "Periode de temps",
        value=(ALL_DATES_DT[0], ALL_DATES_DT[-1]),
        min_value=ALL_DATES_DT[0], max_value=ALL_DATES_DT[-1],
        key="fil_dates",
    )
    # Normalitzar: pot retornar (start, end), (start,) o date
    if isinstance(fil_dates, (list, tuple)) and len(fil_dates) == 2:
        date_start_str, date_end_str = str(fil_dates[0]), str(fil_dates[1])
    elif isinstance(fil_dates, (list, tuple)) and len(fil_dates) == 1:
        date_start_str = date_end_str = str(fil_dates[0])
    else:
        date_start_str = date_end_str = str(fil_dates) if fil_dates else None

    st.markdown(
        "<div style='margin-top:32px;padding-top:14px;border-top:1px solid #1e293b;"
        "text-align:center;font-size:10px;color:#334155;line-height:1.6'>"
        "© Marina Castellano &nbsp;·&nbsp; TFG 2025–2026<br>"
        "Grau en Ciència i Enginyeria de Dades"
        "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: INICI
# ══════════════════════════════════════════════════════════════════════════════
if page == "Inici":

    st.markdown(
        f'<div class="hero-wrap">'
        f'<img src="data:image/svg+xml;base64,{_LOGO_B64}" width="72">'
        f'<div>'
        f'<div class="hero-title">Rodalies de Catalunya</div>'
        f'<div class="hero-sub">Extracció i Anàlisi de dades de X per anticipar incidències en un servei de transport</div>'
        f'<span class="hero-badge">Universitat &nbsp;·&nbsp; Grau en Ciència i Enginyeria de Dades</span>'
        f'<div style="margin-top:14px;font-size:14px;color:#94a3b8;font-weight:500">'
        f'by <span style="color:#f1f5f9;font-weight:700">Marina Castellano</span>'
        f' &nbsp;·&nbsp; TFG 2025–2026</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("""
Aquest treball de fi de grau analitza **66.000+ tweets** publicats a Twitter/X sobre la xarxa de
Rodalies de Catalunya entre 2025 i 2026, amb l'objectiu de detectar incidències ferroviàries
de forma precoç, *abans* que la pròpia operadora les comuniqui oficialment.

Mitjançant tècniques de **processament de llenguatge natural (NLP)** i classificació automàtica,
cada tweet ha estat etiquetat amb la seva naturalesa (informatiu / queixa / mixt) i,
en els casos rellevants, amb el tipus d'incidència (demora, averia, vaga, etc.).

Utilitza la **barra lateral esquerra** per navegar entre les seccions de l'app.
""")

    st.divider()
    st.subheader("Dataset de tweets")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tweets al dataset",   f"{len(df):,}")
    c2.metric("Tweets amb estacio",  f"{df_exp['tweet_id'].nunique():,}")
    c3.metric("Estacions detectades", df_exp["station"].nunique() if len(df_exp) else 0)
    c4.metric("Dies amb dades",      df["date"].nunique())

    st.divider()
    st.subheader("Incidencies detectades (periode complet)")

    inc_total = df_inc[df_inc["tipo_incidencia"].isin(ALL_TIPOS)]
    pct_inc   = round(len(inc_total) / len(df_inc) * 100, 1) if len(df_inc) > 0 else 0

    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Tweets d'incident",  f"{len(inc_total):,}")
    i2.metric("Tipus mes frequent", inc_total["tipo_incidencia"].mode().iloc[0]
              if len(inc_total) > 0 else "—")
    i3.metric("Mesos amb incidents", inc_total["month"].nunique())
    i4.metric("% sobre total",      f"{pct_inc}%")

    st.divider()

    # Grafic rapid: distribucio per tipus (landing page preview)
    if len(inc_total) > 0:
        tcol1, tcol2 = st.columns(2)

        with tcol1:
            st.markdown("**Distribucio per tipus d'incidencia**")
            tipo_dist = (inc_total.groupby("tipo_incidencia").size()
                         .reset_index(name="n").sort_values("n", ascending=True))
            tipo_dist["color"] = tipo_dist["tipo_incidencia"].map(TIPO_COLORS)
            fig_t = go.Figure(go.Bar(
                x=tipo_dist["n"], y=tipo_dist["tipo_incidencia"],
                orientation="h",
                marker_color=tipo_dist["color"].tolist(),
                text=tipo_dist["n"], textposition="outside",
            ))
            fig_t.update_layout(
                height=250, margin=dict(l=100, r=60, t=10, b=30),
                xaxis_title="Tweets", yaxis_title="",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#94a3b8"),
            )
            st.plotly_chart(fig_t, use_container_width=True)

        with tcol2:
            st.markdown("**Evolucio mensual d'incidents**")
            inc_monthly = (inc_total.groupby("month").size()
                           .reset_index(name="n").sort_values("month"))
            fig_im = go.Figure(go.Scatter(
                x=inc_monthly["month"], y=inc_monthly["n"],
                mode="lines+markers", fill="tozeroy",
                line=dict(color="#7dd3fc", width=2),
                fillcolor="rgba(125,211,252,0.12)",
            ))
            fig_im.update_layout(
                height=250, margin=dict(l=40, r=20, t=10, b=40),
                xaxis_title="", yaxis_title="Tweets",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#94a3b8"),
            )
            st.plotly_chart(fig_im, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: MAPA GEOGRAFIC
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Mapa geografic":

    st.title("Mapa geografic")
    st.markdown(
        "<p style='color:#94a3b8;font-size:0.95rem;margin:-8px 0 24px;line-height:1.7'>"
        "En aquesta pàgina es visualitza la distribució geogràfica dels tweets sobre "
        "la xarxa de Rodalies de Catalunya en quatre formats: punts per estació, "
        "mapa de calor, visualització 3D per zones i agrupació per clusters. "
        "Usa els filtres de la barra lateral per explorar períodes o línies concretes."
        "</p>",
        unsafe_allow_html=True,
    )

    # ── Filtrar dades ──────────────────────────────────────────────────────────
    df_f = apply_filters(df_exp, fil_lines, fil_idiomes, fil_caracters,
                         date_start_str, date_end_str)

    station_agg = (
        df_f.groupby(["station", "lat", "lon", "line"])
        .agg(n_tweets=("tweet_id", "nunique"),
             tweets=("tweet_text", list),
             timestamps=("timestamp", list))
        .reset_index()
    )

    line_tweet_counts = (
        station_agg.groupby("line")["n_tweets"].sum().to_dict()
        if len(station_agg) > 0 else {}
    )

    active_lines = fil_lines if fil_lines else ALL_LINES

    # Info periode seleccionat
    is_filtered = (date_start_str != ALL_DATES[0] or date_end_str != ALL_DATES[-1])
    if is_filtered:
        st.info(
            f"{len(station_agg)} estacions · {df_f['tweet_id'].nunique()} tweets "
            f"del {date_start_str} al {date_end_str}"
        )

    # ── Filtre d'etiquetes (fora de columnes per alinear llegenda amb mapa) ───────
    label_mode = st.radio(
        "Mostrar etiquetes als mapes",
        ["Totes les estacions", "Top N estacions", "Codi de linia"],
        horizontal=True, key="label_mode",
    )
    top_n = 10
    if label_mode == "Top N estacions":
        top_n = st.number_input(
            "Nombre d'estacions (les N amb mes tweets)", min_value=1,
            max_value=50, value=10, step=1, key="top_n_val",
        )
    if label_mode == "Totes les estacions":
        labeled_ids = set(station_agg["station"])
        label_map   = {r["station"]: r["station"] for _, r in station_agg.iterrows()}
    elif label_mode == "Top N estacions":
        top_rows    = station_agg.nlargest(int(top_n), "n_tweets")
        labeled_ids = set(top_rows["station"])
        label_map   = {r["station"]: r["station"] for _, r in top_rows.iterrows()}
    else:
        labeled_ids = set(station_agg["station"])
        label_map   = {r["station"]: r["line"] for _, r in station_agg.iterrows()}

    # ── MAP 1: Punts (amplada completa) ──────────────────────────────────────
    st.markdown(
        "<div style='display:flex;align-items:center;gap:14px;margin:0 0 10px;"
        "padding:12px 16px;background:linear-gradient(90deg,#1e293b 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #7dd3fc'>"
        "<div style='width:26px;height:26px;background:#7dd3fc22;border:1px solid #7dd3fc55;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#7dd3fc;flex-shrink:0'>1</div>"
        "<div>"
        "<div style='font-size:9px;color:#7dd3fc;font-weight:700;letter-spacing:1.5px'>MAPA 1</div>"
        "<div style='font-size:15px;color:#f1f5f9;font-weight:600;margin-top:1px'>Distribució per estació</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    m1 = folium.Map(location=[41.65, 1.8], zoom_start=8, tiles="CartoDB positron")

    for line in active_lines:
        if line not in stations_raw:
            continue
        color  = LINE_COLORS.get(line, DEFAULT_COLOR)
        coords = [[s["lat"], s["lon"]] for s in stations_raw[line]]
        folium.PolyLine(coords, color=color, weight=4,
                        opacity=0.65, tooltip=f"Linia {line}").add_to(m1)

    def _fmt_ts(ts):
        try:
            t = pd.Timestamp(ts)
            return t.strftime("%H:%M &nbsp;·&nbsp; %d/%m/%Y") if pd.notna(t) else ""
        except Exception:
            return ""

    max_n = station_agg["n_tweets"].max() if len(station_agg) > 0 else 1
    for _, row in station_agg.iterrows():
        color  = LINE_COLORS.get(row["line"], DEFAULT_COLOR)
        n      = row["n_tweets"]
        radius = 8 + (n / max_n) * 22
        lat, lon, name = row["lat"], row["lon"], row["station"]

        items_html = "".join(
            f"<div style='margin-bottom:7px;padding:6px 8px;background:#f1f5f9;"
            f"border-radius:6px;border-left:3px solid {color}'>"
            f"<div style='font-size:10px;color:#64748b;margin-bottom:3px'>"
            f"{_fmt_ts(ts)}</div>"
            f"<div style='font-size:12px;color:#1e293b;line-height:1.4'>"
            f"{str(tw)[:150]}{'...' if len(str(tw)) > 150 else ''}</div>"
            f"</div>"
            for tw, ts in zip(row["tweets"][:5], row["timestamps"][:5])
        )
        more = (f"<div style='font-size:11px;color:#94a3b8;text-align:center;"
                f"padding-top:4px'>+ {n-5} tweets mes...</div>") if n > 5 else ""
        popup_html = (
            f"<div style='width:300px;font-family:sans-serif'>"
            f"<div style='font-weight:700;font-size:14px;color:{color};"
            f"margin-bottom:4px'>{name}</div>"
            f"<div style='font-size:11px;color:#64748b;margin-bottom:8px'>"
            f"Linia {row['line'] or 'N/D'} &nbsp;·&nbsp; {n} tweet{'s' if n > 1 else ''}</div>"
            f"{items_html}{more}</div>"
        )
        folium.CircleMarker(
            location=[lat, lon], radius=radius,
            color="white", fill=True, fill_color=color,
            fill_opacity=0.9, weight=2,
            popup=folium.Popup(popup_html, max_width=310),
            tooltip=f"{name} · {n} tweets · {row['line'] or 'N/D'}",
        ).add_to(m1)
        if name in labeled_ids:
            folium.Marker(
                location=[lat, lon],
                icon=folium.DivIcon(
                    html=(
                        f"<div style='font-size:9.5px;font-weight:600;"
                        f"font-family:\"Helvetica Neue\",Arial,sans-serif;color:#1a1a1a;"
                        f"white-space:nowrap;pointer-events:none;"
                        f"text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,"
                        f"-1px 1px 0 #fff,1px 1px 0 #fff,0 0 3px #fff;"
                        f"margin-top:{int(radius)+4}px;margin-left:{int(radius)+4}px'>"
                        f"{label_map.get(name, name)}</div>"
                    ),
                    icon_size=(0, 0), icon_anchor=(0, 0),
                ),
            ).add_to(m1)

    # Llegenda overlay dins el mapa (cantonada inferior esquerra)
    legend_items_html = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
        f'<div style="width:22px;height:5px;background:{LINE_COLORS.get(l, DEFAULT_COLOR)};'
        f'border-radius:2px;flex-shrink:0"></div>'
        f'<span style="font-size:11px;color:#cbd5e1;font-family:sans-serif">{l}</span>'
        f'</div>'
        for l in active_lines
    )
    folium.Element(
        f'<div style="position:fixed;bottom:24px;left:16px;z-index:9999;'
        f'background:rgba(8,14,26,0.88);backdrop-filter:blur(6px);'
        f'border:1px solid rgba(51,65,85,0.8);border-radius:10px;'
        f'padding:12px 16px;box-shadow:0 4px 24px rgba(0,0,0,0.5);">'
        f'<div style="font-size:11px;font-weight:700;color:#94a3b8;'
        f'letter-spacing:1px;text-transform:uppercase;margin-bottom:9px;'
        f'font-family:sans-serif">Línies</div>'
        f'{legend_items_html}</div>'
    ).add_to(m1.get_root().html)

    st_folium(m1, width=None, height=650, returned_objects=[], key="map_pts")

    # ── Llegenda (expander sota mapa 1) ───────────────────────────────────────
    with st.expander("Linies actives — veure estacions"):
        leg_cols = st.columns(min(len(active_lines), 4))
        for i, line in enumerate(active_lines):
            color  = LINE_COLORS.get(line, DEFAULT_COLOR)
            n_tw   = line_tweet_counts.get(line, 0)
            sts    = stations_raw.get(line, [])
            st_items = "".join(
                f"<div style='font-size:10.5px;color:#cbd5e1;padding:2px 0 2px 10px;"
                f"border-left:2px solid {color}55;margin:2px 0'>· {s['name']}</div>"
                for s in sts
            )
            with leg_cols[i % len(leg_cols)]:
                st.markdown(
                    f"<div style='margin-bottom:10px'>"
                    f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>"
                    f"<div style='width:18px;height:6px;background:{color};border-radius:3px'></div>"
                    f"<span style='font-weight:700;font-size:13px;color:#f1f5f9'>{line}</span>"
                    f"<span style='color:#64748b;font-size:11px'>{n_tw} tw</span></div>"
                    f"{st_items}</div>",
                    unsafe_allow_html=True,
                )

    # ── MAP 2: Heatmap ────────────────────────────────────────────────────────
    st.markdown(
        "<div style='display:flex;align-items:center;gap:14px;margin:28px 0 10px;"
        "padding:12px 16px;background:linear-gradient(90deg,#1e293b 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #fb923c'>"
        "<div style='width:26px;height:26px;background:#fb923c22;border:1px solid #fb923c55;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#fb923c;flex-shrink:0'>2</div>"
        "<div>"
        "<div style='font-size:9px;color:#fb923c;font-weight:700;letter-spacing:1.5px'>MAPA 2</div>"
        "<div style='font-size:15px;color:#f1f5f9;font-weight:600;margin-top:1px'>Mapa de calor — densitat de tweets</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    m2 = folium.Map(location=[41.65, 1.8], zoom_start=8, tiles="CartoDB positron")
    for line in active_lines:
        if line not in stations_raw:
            continue
        color  = LINE_COLORS.get(line, DEFAULT_COLOR)
        coords = [[s["lat"], s["lon"]] for s in stations_raw[line]]
        folium.PolyLine(coords, color=color, weight=3, opacity=0.5).add_to(m2)
    if len(station_agg) > 0:
        heat_data = station_agg[["lat", "lon", "n_tweets"]].values.tolist()
        HeatMap(heat_data, radius=28, blur=22, min_opacity=0.3,
                max_zoom=14).add_to(m2)
    for _, row in station_agg.iterrows():
        sname = row["station"]
        if sname not in labeled_ids:
            continue
        folium.Marker(
            location=[row["lat"], row["lon"]],
            icon=folium.DivIcon(
                html=(
                    f"<div style='font-size:9px;font-weight:700;"
                    f"font-family:\"Helvetica Neue\",Arial,sans-serif;"
                    f"color:#fff;white-space:nowrap;pointer-events:none;"
                    f"text-shadow:0 0 4px #000,0 0 4px #000,0 0 4px #000;"
                    f"padding:1px 3px;border-radius:3px;"
                    f"background:rgba(0,0,0,0.45)'>"
                    f"{label_map.get(sname, sname)}</div>"
                ),
                icon_size=(0, 0), icon_anchor=(0, 0),
            ),
        ).add_to(m2)
    st_folium(m2, width=None, height=480, returned_objects=[], key="map_heat")

    # ── MAP 3: 3D Hexbin (pydeck) ─────────────────────────────────────────────
    st.markdown(
        "<div style='display:flex;align-items:center;gap:14px;margin:28px 0 10px;"
        "padding:12px 16px;background:linear-gradient(90deg,#1e293b 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #a78bfa'>"
        "<div style='width:26px;height:26px;background:#a78bfa22;border:1px solid #a78bfa55;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#a78bfa;flex-shrink:0'>3</div>"
        "<div>"
        "<div style='font-size:9px;color:#a78bfa;font-weight:700;letter-spacing:1.5px'>MAPA 3</div>"
        "<div style='font-size:15px;color:#f1f5f9;font-weight:600;margin-top:1px'>Concentració 3D per zones</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    pts_3d = df_f[["lat", "lon"]].dropna()
    if len(pts_3d) > 0:
        hex_layer = pdk.Layer(
            "HexagonLayer",
            data=pts_3d,
            get_position="[lon, lat]",
            radius=3000,
            elevation_scale=12,
            elevation_range=[0, 2500],
            pickable=True,
            extruded=True,
            coverage=1.0,
        )
        scatter_3d = pdk.Layer(
            "ScatterplotLayer",
            data=station_agg[["station", "lat", "lon", "n_tweets", "line"]],
            get_position="[lon, lat]",
            get_radius=1800,
            get_fill_color=[255, 255, 255, 140],
            get_line_color=[255, 255, 255, 220],
            line_width_min_pixels=1,
            stroked=True,
            pickable=True,
        )
        view_3d = pdk.ViewState(latitude=41.65, longitude=1.8, zoom=7, pitch=48, bearing=10)
        st.pydeck_chart(pdk.Deck(
            layers=[hex_layer, scatter_3d],
            initial_view_state=view_3d,
            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
            tooltip={
                "html": (
                    "<div style='background:#0f172a;padding:8px 12px;border-radius:6px;"
                    "border:1px solid #334155;font-family:sans-serif'>"
                    "<div style='color:#7dd3fc;font-weight:700;font-size:13px'>{station}</div>"
                    "<div style='color:#94a3b8;font-size:11px'>Línia {line}</div>"
                    "<div style='color:#f1f5f9;font-size:12px;margin-top:3px'>"
                    "{n_tweets} tweets · {count} punts en aquesta zona</div>"
                    "</div>"
                ),
                "style": {"backgroundColor": "transparent", "border": "none"},
            },
        ), key="map_3d")
    else:
        st.info("Sense dades per als filtres seleccionats.")

    # ── MAP 4: Clusters ───────────────────────────────────────────────────────
    st.markdown(
        "<div style='display:flex;align-items:center;gap:14px;margin:28px 0 10px;"
        "padding:12px 16px;background:linear-gradient(90deg,#1e293b 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #34d399'>"
        "<div style='width:26px;height:26px;background:#34d39922;border:1px solid #34d39955;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#34d399;flex-shrink:0'>4</div>"
        "<div>"
        "<div style='font-size:9px;color:#34d399;font-weight:700;letter-spacing:1.5px'>MAPA 4</div>"
        "<div style='font-size:15px;color:#f1f5f9;font-weight:600;margin-top:1px'>Agrupació per clusters</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    m4 = folium.Map(location=[41.65, 1.8], zoom_start=8, tiles="CartoDB positron")
    for line in active_lines:
        if line not in stations_raw:
            continue
        color  = LINE_COLORS.get(line, DEFAULT_COLOR)
        coords = [[s["lat"], s["lon"]] for s in stations_raw[line]]
        folium.PolyLine(coords, color=color, weight=3, opacity=0.5).add_to(m4)
    cluster_group = MarkerCluster(name="Estacions").add_to(m4)
    for _, row in station_agg.iterrows():
        color = LINE_COLORS.get(row["line"], DEFAULT_COLOR)
        folium.Marker(
            location=[row["lat"], row["lon"]],
            tooltip=f"{row['station']} · {row['n_tweets']} tweets",
            popup=folium.Popup(
                f"<b>{row['station']}</b><br>Linia: {row['line']}<br>"
                f"{row['n_tweets']} tweets", max_width=200
            ),
            icon=folium.Icon(color="lightgray", icon_color=color, icon="train",
                             prefix="fa"),
        ).add_to(cluster_group)
    st_folium(m4, width=None, height=480, returned_objects=[], key="map_cluster")

    # Taula
    st.divider()
    with st.expander("Veure tweets amb estacio detectada"):
        cols_t = ["timestamp", "tweet_text", "stations_list", "lines_list", "idioma", "caracter"]
        cols_ok = [c for c in cols_t if c in df.columns]
        df_taula = apply_filters(df, fil_lines, fil_idiomes, fil_caracters,
                                 date_start_str, date_end_str, use_lines_list=True)
        df_taula = df_taula[df_taula["stations_list"] != ""]
        st.dataframe(df_taula[cols_ok].sort_values("timestamp", ascending=False),
                     use_container_width=True, height=280)


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: ANALISI TEMPORAL
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Analisi temporal":

    st.title("Analisi temporal")

    df_t = apply_filters(df, fil_lines, fil_idiomes, fil_caracters,
                         date_start_str, date_end_str, use_lines_list=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tweets filtrats",     f"{len(df_t):,}")
    m2.metric("Dies amb activitat",  df_t["date"].nunique())
    m3.metric("Mesos amb activitat", df_t["month"].nunique())
    m4.metric("Tweets totals",       f"{len(df):,}")
    st.divider()

    # ── Grafic diari ──────────────────────────────────────────────────────────
    st.subheader("Volum diari de tweets")
    months_available = ["Tots els mesos"] + sorted(df_t["month"].dropna().unique().tolist())
    sel_month = st.selectbox("Mes a visualitzar", options=months_available,
                             index=0, key="sel_month_daily")

    if len(df_t) > 0:
        df_daily_src = (df_t[df_t["month"] == sel_month]
                        if sel_month != "Tots els mesos" else df_t)
        daily     = df_daily_src.groupby("date").size().reset_index(name="n_tweets")
        daily["date"] = pd.to_datetime(daily["date"])
        daily     = daily.sort_values("date")
        top3_days = daily.nlargest(3, "n_tweets")

        fig_d = go.Figure()
        fig_d.add_trace(go.Scatter(
            x=daily["date"], y=daily["n_tweets"],
            mode="lines+markers", name="Tweets/dia",
            line=dict(color="#1E40AF", width=2), marker=dict(size=5),
        ))
        fig_d.add_trace(go.Scatter(
            x=top3_days["date"], y=top3_days["n_tweets"],
            mode="markers+text", name="Top 3 dies",
            marker=dict(size=14, color="#DC143C", symbol="star"),
            text=[f"#{i+1}: {n}" for i, n in enumerate(top3_days["n_tweets"])],
            textposition="top center",
        ))
        scope = f"— {sel_month}" if sel_month != "Tots els mesos" else ""
        fig_d.update_layout(
            title=f"Tweets per dia {scope}", xaxis_title="Data", yaxis_title="Tweets",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02), height=360,
        )
        st.plotly_chart(fig_d, use_container_width=True)

        top3_show = top3_days.copy()
        top3_show["date"] = top3_show["date"].dt.strftime("%d/%m/%Y")
        st.markdown("**Top 3 dies del periode seleccionat:**")
        st.dataframe(top3_show.rename(columns={"date": "Data", "n_tweets": "Tweets"}),
                     use_container_width=True, hide_index=True)
    else:
        st.info("No hi ha dades per als filtres seleccionats.")

    st.divider()

    # ── Comparativa mensual ───────────────────────────────────────────────────
    st.subheader("Comparativa mensual (top 3 en vermell)")
    if len(df_t) > 0:
        monthly     = df_t.groupby("month").size().reset_index(name="n_tweets").sort_values("month")
        top3_months = set(monthly.nlargest(3, "n_tweets")["month"])
        bar_colors  = ["#DC143C" if m in top3_months else "#3B82F6" for m in monthly["month"]]
        fig_m = go.Figure(go.Bar(
            x=monthly["month"], y=monthly["n_tweets"],
            marker_color=bar_colors,
            hovertemplate="%{x}: %{y} tweets<extra></extra>",
        ))
        fig_m.update_layout(
            xaxis_title="Mes", yaxis_title="Tweets", height=350,
            annotations=[dict(x=0.99, y=0.99, xref="paper", yref="paper",
                              text="Vermell = top 3 mesos   Blau = resta",
                              showarrow=False, font=dict(size=11),
                              bgcolor="white", bordercolor="#ccc", borderwidth=1)],
        )
        st.plotly_chart(fig_m, use_container_width=True)

    st.divider()

    # ── Hora del dia per caracter ─────────────────────────────────────────────
    st.subheader("Activitat per hora del dia per caracter")
    st.caption("Distribucio de tweets per hora i tipus")
    if len(df_t) > 0:
        cartypes   = df_t["caracter"].unique()
        hourly_car = df_t.groupby(["hour", "caracter"]).size().reset_index(name="n")
        full_idx   = pd.MultiIndex.from_product([range(24), cartypes],
                                                names=["hour", "caracter"])
        hourly_car = (hourly_car.set_index(["hour", "caracter"])
                                .reindex(full_idx, fill_value=0).reset_index())
        fig_h = px.bar(hourly_car, x="hour", y="n", color="caracter",
                       barmode="stack", color_discrete_map=CARACTER_COLORS,
                       labels={"hour": "Hora del dia", "n": "Tweets", "caracter": "Caracter"})
        fig_h.update_layout(
            xaxis=dict(tickmode="linear", tick0=0, dtick=1), height=340,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_h, use_container_width=True)

    st.divider()

    # ── Top 10 dies ───────────────────────────────────────────────────────────
    st.subheader("Top 10 dies amb mes activitat")
    if len(df_t) > 0:
        top10 = (
            df_t.groupby("date")
            .agg(
                n_tweets  =("tweet_id", "count"),
                car_pred  =("caracter", caracter_predominant),
                estacions =("stations_list", lambda x: ", ".join(
                    sorted({s for v in x if v for s in str(v).split("|") if s})[:4]
                )),
            )
            .reset_index()
            .sort_values("n_tweets", ascending=False)
            .head(10)
        )
        top10["date"] = pd.to_datetime(top10["date"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            top10.rename(columns={"date": "Data", "n_tweets": "Tweets",
                                  "car_pred": "Caracter predominant",
                                  "estacions": "Estacions principals"}),
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: ANALISI PER LINIES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Analisi per linies":

    st.title("Analisi per linies")

    df_l = apply_filters(df_exp, fil_lines, fil_idiomes, fil_caracters,
                         date_start_str, date_end_str)

    st.subheader("Quines linies reben mes tweets?")
    if len(df_l) > 0:
        line_counts = (
            df_l.groupby("line")["tweet_id"].nunique()
            .reset_index(name="n_tweets")
            .sort_values("n_tweets", ascending=True)
        )
        line_counts["color"] = line_counts["line"].map(LINE_COLORS).fillna(DEFAULT_COLOR)
        fig_lines = go.Figure(go.Bar(
            x=line_counts["n_tweets"], y=line_counts["line"],
            orientation="h",
            marker_color=line_counts["color"].tolist(),
            text=line_counts["n_tweets"], textposition="outside",
        ))
        fig_lines.update_layout(xaxis_title="Tweets unics", yaxis_title="Linia",
                                height=350, margin=dict(l=60, r=80))
        st.plotly_chart(fig_lines, use_container_width=True)
    else:
        st.info("No hi ha dades per als filtres seleccionats.")

    st.divider()

    st.subheader("Distribucio de caracter per estacio")
    st.caption("Selecciona una linia per veure les seves estacions")

    sel_line_est = st.pills("Linia a analitzar", options=ALL_LINES,
                             selection_mode="single", default="R1", key="lin_sel_line")

    if sel_line_est and len(df_l) > 0:
        df_line = df_l[df_l["line"] == sel_line_est]
        if len(df_line) == 0:
            st.info(f"Cap tweet per a la linia {sel_line_est} amb els filtres actuals.")
        else:
            est_car = (df_line.groupby(["station", "caracter"])["tweet_id"]
                       .nunique().reset_index(name="n"))
            totals  = est_car.groupby("station")["n"].sum().reset_index(name="total")
            est_car = est_car.merge(totals, on="station")
            est_car["pct"] = (est_car["n"] / est_car["total"] * 100).round(1)
            order   = totals.sort_values("total", ascending=True)["station"].tolist()

            fig_est = px.bar(
                est_car, x="pct", y="station", color="caracter",
                orientation="h", barmode="stack",
                color_discrete_map=CARACTER_COLORS,
                labels={"pct": "% tweets", "station": "Estacio", "caracter": "Caracter"},
                category_orders={"station": order},
                custom_data=["n", "total"],
            )
            fig_est.update_traces(
                hovertemplate="<b>%{y}</b><br>%{x:.1f}%"
                              " (%{customdata[0]} de %{customdata[1]})<extra>%{fullData.name}</extra>"
            )
            fig_est.update_layout(
                xaxis_title="% tweets", yaxis_title="",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                height=max(300, len(order) * 28 + 100),
            )
            st.plotly_chart(fig_est, use_container_width=True)

            with st.expander("Taula de dades"):
                pivot = est_car.pivot_table(
                    index="station", columns="caracter", values="n", fill_value=0
                )
                pivot["Total"] = pivot.sum(axis=1)
                st.dataframe(pivot.sort_values("Total", ascending=False),
                             use_container_width=True)
    else:
        st.info("Selecciona una linia per veure les estacions.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: ANALISI D'INCIDENCIES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Analisi d'incidencies":

    st.title("Analisi d'incidencies")
    st.caption("Els filtres de linia, idioma i caracter no s'apliquen a aquesta pagina "
               "(el CSV d'incidencies no te aquestes columnes). Si s'aplica el rang de dates.")

    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        sel_tipos = st.pills("Tipus d'incident", options=ALL_TIPOS,
                             selection_mode="multi", default=ALL_TIPOS, key="inc_tipos")
    with ic2:
        conf_opts = ["Totes", "Alta (>= 0.88)", "Mitja (0.75 - 0.85)", "Baixa (<= 0.75)"]
        sel_conf  = st.selectbox("Confianca", conf_opts, index=0, key="inc_conf")
    with ic3:
        # Filtre de mes dins del rang de dates global
        inc_months_filtered = [m for m in INC_MONTHS
                               if (date_start_str or "0") <= m <= (date_end_str or "z")]
        if not inc_months_filtered:
            inc_months_filtered = INC_MONTHS
        sel_mes = st.selectbox("Mes", inc_months_filtered,
                               index=len(inc_months_filtered) - 1, key="inc_mes")
    st.divider()

    # Aplicar filtres
    tipos_actius = sel_tipos if sel_tipos else ALL_TIPOS
    df_i = df_inc[df_inc["tipo_incidencia"].isin(tipos_actius)]
    if date_start_str:
        df_i = df_i[df_i["date"] >= date_start_str]
    if date_end_str:
        df_i = df_i[df_i["date"] <= date_end_str]
    if sel_conf == "Alta (>= 0.88)":
        df_i = df_i[df_i["confianza"] >= 0.88]
    elif sel_conf == "Mitja (0.75 - 0.85)":
        df_i = df_i[df_i["confianza"].between(0.75, 0.85)]
    elif sel_conf == "Baixa (<= 0.75)":
        df_i = df_i[df_i["confianza"] <= 0.75]

    df_mes_inc = df_i[df_i["month"] == sel_mes] if sel_mes else df_i.iloc[:0]

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Tweets incident (mes)", len(df_mes_inc))
    mc2.metric("Dies amb activitat", df_mes_inc["date"].nunique())
    mc3.metric("Tipus mes frequent",
               df_mes_inc["tipo_incidencia"].mode().iloc[0] if len(df_mes_inc) > 0 else "—")
    mc4.metric("Total incidents (dataset)", len(df_i))
    st.divider()

    st.subheader(f"Volum diari d'incidents — {sel_mes}")
    if len(df_mes_inc) > 0:
        daily_tipo = (df_mes_inc.groupby(["date", "tipo_incidencia"])
                      .size().reset_index(name="n"))
        fig_inc = px.bar(
            daily_tipo, x="date", y="n", color="tipo_incidencia",
            barmode="stack", color_discrete_map=TIPO_COLORS,
            labels={"date": "Dia", "n": "Tweets", "tipo_incidencia": "Tipus"},
        )
        fig_inc.update_layout(
            xaxis=dict(tickformat="%d/%m", tickangle=-45),
            legend=dict(orientation="h", yanchor="bottom", y=1.02), height=400,
        )
        st.plotly_chart(fig_inc, use_container_width=True)
    else:
        st.info("Sense dades per al mes i filtres seleccionats.")

    st.divider()

    st.subheader("Distribucio per tipus (periode complet)")
    if len(df_i) > 0:
        tipo_total = (df_i.groupby("tipo_incidencia").size()
                      .reset_index(name="n").sort_values("n", ascending=True))
        tipo_total["color"] = tipo_total["tipo_incidencia"].map(TIPO_COLORS).fillna(DEFAULT_COLOR)
        fig_tipo = go.Figure(go.Bar(
            x=tipo_total["n"], y=tipo_total["tipo_incidencia"],
            orientation="h",
            marker_color=tipo_total["color"].tolist(),
            text=tipo_total["n"], textposition="outside",
        ))
        fig_tipo.update_layout(
            xaxis_title="Tweets", yaxis_title="",
            height=max(250, len(tipo_total) * 40 + 80),
            margin=dict(l=120, r=80),
        )
        st.plotly_chart(fig_tipo, use_container_width=True)

    st.divider()
    with st.expander("Veure tweets del mes seleccionat"):
        cols_inc = ["date", "tweet_text", "tipo_incidencia", "confianza", "metodo"]
        st.dataframe(df_mes_inc[cols_inc].sort_values("date", ascending=False),
                     use_container_width=True, height=280)
