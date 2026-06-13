"""
TFG — Rodalies de Catalunya: Detecció precoç d'incidències via Twitter
App de visualització amb Streamlit
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
import plotly.io as pio
import pydeck as pdk
import json

pio.templates.default = "plotly_white"

DATA_START = "2025-08-01"
CAL_MIN    = datetime.date(2025, 8, 1)
CAL_MAX    = datetime.date(2026, 6, 30)

LINE_COLORS = {
    "R1": "#87CEEB", "R2": "#4CAF50", "R2N": "#90EE90", "R2S": "#006400",
    "R3": "#DC143C", "R4": "#00008B", "R7": "#8B008B", "R8": "#FF69B4",
}
CARACTER_COLORS = {"informatiu": "#3B82F6", "queixa": "#DC143C", "indefinit": "#F59E0B"}
TIPO_COLORS = {
    "demora": "#F59E0B", "averia": "#DC143C", "obras": "#6366F1",
    "parada": "#10B981", "arrollamiento": "#7C3AED", "huelga": "#EC4899",
    "sin_incidencia": "#9CA3AF",
}
DEFAULT_COLOR = "#6B7280"
ALL_TIPOS = ["demora", "averia", "obras", "parada", "arrollamiento", "huelga"]

PATHS = {
    "csv":        r"C:\MARINA\Universitat\TFG - Visualització\Fonts\classificacio_estacions_ubicacions.csv",
    "json":       r"C:\MARINA\Universitat\TFG - Visualització\Fonts\stations_info.json",
    "json2":      r"C:\MARINA\Universitat\TFG - Visualització\Fonts\stations_info-2.json",
    "json_dir":   r"C:\MARINA\Universitat\TFG - Visualització\Fonts\stations_json",
    "csv_stations": r"C:\MARINA\Universitat\TFG - Visualització\Fonts\stations.csv",
    "csv_inc":    r"C:\MARINA\Universitat\TFG - Visualització\Fonts\tweets_incidencias.csv",
    "csv_master": r"C:\MARINA\Universitat\TFG - Visualització\Fonts\tweets_merged.csv",
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
    import glob
    combined = {}

    # Font principal: stations_info.json (coordenades oficials de totes les línies)
    if os.path.exists(PATHS["json"]):
        with open(PATHS["json"], encoding="utf-8") as f:
            combined.update(json.load(f))

    # Supplement: fitxers individuals per línies no cobertes per json2
    for filepath in sorted(glob.glob(os.path.join(PATHS["json_dir"], "*_stations.json"))):
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        for line, stations in data.items():
            if line not in combined:
                combined[line] = stations

    lookup = {}
    for line, stations in combined.items():
        for s in stations:
            name = s["name"]
            if name not in lookup:
                lookup[name] = {"lat": s["lat"], "lon": s["lon"], "lines": []}
            if line not in lookup[name]["lines"]:
                lookup[name]["lines"].append(line)

    raw_sorted = {
        line: sorted(sts, key=lambda s: s["index"])
        for line, sts in combined.items()
    }
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
    df["caracter"] = df["caracter"].fillna("indefinit").replace({"mixt": "indefinit"})
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
    return df_i.reset_index(drop=True)


@st.cache_data
def load_master(_mtime_m):
    dm = pd.read_csv(PATHS["csv_master"], encoding="utf-8", low_memory=False)
    dm["datetime"] = pd.to_datetime(
        dm["date"].astype(str) + " " + dm["hora"].astype(str), errors="coerce"
    )
    return dm


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

df_master  = load_master(os.path.getmtime(PATHS["csv_master"]))

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
# HELPERS PER CASOS D'ESTUDI
# ══════════════════════════════════════════════════════════════════════════════
def _tweet_card(row, border_color, show_confianza=False):
    conf_txt = (f" · conf. {row.get('confianza', 0):.2f}"
                if show_confianza and pd.notna(row.get("confianza")) else "")
    tipus_val = str(row.get("tipus_incident", ""))
    tipus_txt = (
        f" &nbsp;<span style='background:{TIPO_COLORS.get(tipus_val, DEFAULT_COLOR)}33;"
        f"color:{TIPO_COLORS.get(tipus_val, DEFAULT_COLOR)};font-weight:700;"
        f"font-size:11px;padding:1px 7px;border-radius:10px'>{tipus_val}</span>"
        if pd.notna(row.get("tipus_incident")) and tipus_val not in ("sin_incidencia", "nan", "")
        else ""
    )
    return (
        f"<div style='padding:12px 16px;margin-bottom:8px;background:#f8fafc;"
        f"border-radius:8px;border-left:4px solid {border_color};"
        f"border:1px solid #e2e8f0;border-left:4px solid {border_color}'>"
        f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:6px'>"
        f"<span style='font-size:14px;font-weight:700;color:#0f172a'>"
        f"{str(row.get('hora',''))[:5]}</span>"
        f"<span style='font-size:12px;color:#64748b'>{row.get('user','')}{conf_txt}</span>"
        f"{tipus_txt}</div>"
        f"<div style='font-size:13px;color:#334155;line-height:1.6'>"
        f"{str(row.get('tweet_text',''))[:350]}</div>"
        f"</div>"
    )


def _delta_badge(mins):
    if mins <= 0:
        return ""
    h, m = divmod(int(mins), 60)
    txt   = f"{h}h {m}min" if h > 0 else f"{m}min"
    color = "#DC143C" if mins >= 60 else ("#F59E0B" if mins >= 30 else "#10B981")
    return (
        f"<div style='display:inline-flex;align-items:center;gap:8px;"
        f"background:{color}22;border:1px solid {color}55;border-radius:20px;"
        f"padding:4px 14px;margin:10px 0'>"
        f"<span style='font-size:13px;font-weight:700;color:{color}'>"
        f"Detecció anticipada: {txt} abans</span></div>"
    )


def _render_cas_estudi(dia, titol, descripcio_html, bloc_especial=None,
                        excloure_linies=None, linia_rename_display=None,
                        linies_extra_usuari=None, evidencia_override=None):
    st.title(titol)
    st.markdown(
        f"<p style='color:#475569;font-size:0.95rem;margin:-8px 0 20px;line-height:1.7'>"
        f"{descripcio_html}</p>",
        unsafe_allow_html=True,
    )

    df_dia = df_master[df_master["date"] == dia].copy()

    es_oficial = df_dia["user"].str.lower().str.match(
        r"@rodalies$|@rod\w+cat|@inforodali|@emergenci|"
        r"@3catinfo|@btvnoticies|@elnacionalcat|@adif|@renfe|@inforenfe|@radiosabd",
        na=False,
    )
    df_usr = df_dia[~es_oficial].copy()
    df_ofi = df_dia[es_oficial].copy()


    INC_KWS = (r"incid[eè]|interromp|tall|retard|demora|no circula|"
               r"afectaci|aturad|suprim|alternatiu|arbre|mur|caiguda|temporal")

    linies_actives = df_dia["linia"].dropna().value_counts().index.tolist()
    if excloure_linies:
        linies_actives = [l for l in linies_actives if l not in excloure_linies]
    df_ofi_all = df_ofi.sort_values("hora")

    def _disp(l):
        return (linia_rename_display or {}).get(l, l)

    # ── Pre-càlcul detecció anticipada per línia ──────────────────────────────
    LINE_ACCOUNT = {
        "R1": "rod1cat", "R2": "rod2cat", "R2N": "rod2nordcat", "R2S": "rod2sudcat",
        "R3": "rod3cat", "R4": "rod4cat", "R7": "rod7cat", "R8": "rod8cat",
    }

    def _det(linia):
        # Tweets d'usuari: línia assignada O mencions al text
        df_l_u_dir = df_usr[df_usr["linia"] == linia]
        df_l_u_text = df_usr[df_usr["tweet_text"].str.contains(linia, case=False, na=False)]
        df_l_u = pd.concat([df_l_u_dir, df_l_u_text]).drop_duplicates(subset=["tweet_id"]).sort_values("hora")

        # Tweets oficials: línia assignada O mencions al text
        df_l_o_dir = df_ofi[df_ofi["linia"] == linia]
        df_l_o_text = df_ofi[df_ofi["tweet_text"].str.contains(linia, case=False, na=False)]
        df_l_o = pd.concat([df_l_o_dir, df_l_o_text]).drop_duplicates(subset=["tweet_id"])

        # Compte oficial específic de la línia (ex: @rod1cat per R1)
        rod_acc = LINE_ACCOUNT.get(linia)
        df_rod = (df_ofi_all[df_ofi_all["user"].str.lower()
                             .str.contains(rod_acc, na=False)]
                  if rod_acc else pd.DataFrame())

        # Tots els oficials que mencionen la línia al text
        df_mencio = df_ofi_all[
            df_ofi_all["tweet_text"].str.contains(linia, case=False, na=False)
        ]

        # Unió: línia assignada + compte específic + mencions al text
        cand = pd.concat([df_l_o, df_rod, df_mencio]) \
                 .drop_duplicates(subset=["tweet_text"]) \
                 .sort_values("hora")

        # hora_of: primer tweet oficial qualsevol (per a display de comun. oficials)
        primer_of = cand.iloc[0] if len(cand) > 0 else None
        hora_of   = primer_of["hora"][:5] if primer_of is not None else "99:99"

        # hora_of_inc: primer tweet oficial AMB incident real
        # Buscar per keywords en text O per tipus_incident classificat
        has_kws = cand["tweet_text"].str.lower().str.contains(INC_KWS, na=False, regex=True)
        has_tipo = (cand["tipus_incident"].notna() &
                    ~cand["tipus_incident"].isin(["sin_incidencia", "nan", ""]))
        cand_inc = cand[has_kws | has_tipo]
        primer_of_inc = cand_inc.iloc[0] if len(cand_inc) > 0 else None
        hora_of_inc   = primer_of_inc["hora"][:5] if primer_of_inc is not None else "99:99"

        # pre_of i delta_min calculats sobre hora_of_inc
        pre_of    = df_l_u[df_l_u["hora"] < hora_of_inc]
        delta_min = None
        if len(pre_of) > 0 and primer_of_inc is not None:
            try:
                t1 = pd.Timestamp(f"{dia} {pre_of.iloc[0]['hora'][:5]}")
                t2 = pd.Timestamp(f"{dia} {hora_of_inc}")
                dm = (t2 - t1).total_seconds() / 60
                if dm > 0:
                    delta_min = dm
            except Exception:
                pass
        return {"df_l_u": df_l_u,
                "primer_of": primer_of, "hora_of": hora_of,
                "primer_of_inc": primer_of_inc, "hora_of_inc": hora_of_inc,
                "pre_of": pre_of, "delta_min": delta_min, "cand": cand}

    detection = {l: _det(l) for l in linies_actives}

    # ── Mètriques principals ──────────────────────────────────────────────────
    is_q_all = (
        ((df_dia["caracter"] == "queixa") if "caracter" in df_dia.columns
         else pd.Series(False, index=df_dia.index)) |
        (df_dia["tipus_incident"].notna() &
         ~df_dia["tipus_incident"].isin(["sin_incidencia", "nan", ""]))
    )
    n_incidents = int(is_q_all.sum())
    all_deltas  = [det["delta_min"] for det in detection.values() if det["delta_min"]]
    max_delta   = max(all_deltas) if all_deltas else None
    pre_conf_all = pd.concat(
        [det["pre_of"]["confianza"] for det in detection.values()
         if len(det["pre_of"]) > 0 and "confianza" in det["pre_of"].columns],
        ignore_index=True,
    ).dropna()
    pct_high = float((pre_conf_all > 0.80).mean() * 100) if len(pre_conf_all) > 0 else None

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(
            f"<div>"
            f"<div style='font-size:10px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;font-weight:700'>Tweets del dia</div>"
            f"<div style='font-size:18px;font-weight:400;color:#334155'>{len(df_dia):,}</div>"
            f"</div>", unsafe_allow_html=True)
    with m2:
        st.markdown(
            f"<div>"
            f"<div style='font-size:10px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;font-weight:700'>Tweets incident</div>"
            f"<div style='font-size:18px;font-weight:400;color:#334155'>{n_incidents:,}</div>"
            f"</div>", unsafe_allow_html=True)
    with m3:
        st.markdown(
            f"<div>"
            f"<div style='font-size:10px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;font-weight:700'>Línies</div>"
            f"<div style='font-size:18px;font-weight:400;color:#334155'>{df_dia['linia'].dropna().nunique()}</div>"
            f"</div>", unsafe_allow_html=True)
    with m4:
        if max_delta:
            hd, md = divmod(int(max_delta), 60)
            delta_txt = f"{hd}h {md}min" if hd > 0 else f"{md}min"
        else:
            delta_txt = "—"
        st.markdown(
            f"<div>"
            f"<div style='font-size:10px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;font-weight:700'>Màx aventatge</div>"
            f"<div style='font-size:18px;font-weight:400;color:#334155'>{delta_txt}</div>"
            f"</div>", unsafe_allow_html=True)
    with m5:
        pct_txt = f"{pct_high:.0f}%" if pct_high is not None else "—"
        st.markdown(
            f"<div>"
            f"<div style='font-size:10px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;font-weight:700'>% conf > 0.80</div>"
            f"<div style='font-size:18px;font-weight:400;color:#334155'>{pct_txt}</div>"
            f"</div>", unsafe_allow_html=True)
    st.divider()

    # ── Timeline Gantt + Ranking ──────────────────────────────────────────────
    col_gantt, col_rank = st.columns([3, 2])

    def _h(hora_str):
        try:
            h, m = str(hora_str)[:5].split(":")
            return int(h) + int(m) / 60
        except Exception:
            return None

    with col_gantt:
        st.markdown(
            "<div style='font-size:11px;font-weight:700;color:#475569;"
            "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
            "Timeline: primer tweet usuari vs avís oficial</div>",
            unsafe_allow_html=True,
        )
        gantt_traces = []
        gantt_ann    = []
        linies_gantt = []
        for linia in linies_actives:
            det        = detection[linia]
            dlinia     = _disp(linia)
            n_pre_g    = len(det["pre_of"])
            h_usr_s    = det["pre_of"].iloc[0]["hora"][:5] if n_pre_g > 0 else None
            h_ofi_s    = det["hora_of_inc"] if det["hora_of_inc"] != "99:99" else None
            if h_usr_s is None and h_ofi_s is None:
                continue
            linies_gantt.append(dlinia)
            lcolor  = LINE_COLORS.get(linia, DEFAULT_COLOR)
            h_usr_f = _h(h_usr_s)
            h_ofi_f = _h(h_ofi_s)
            first_l = (dlinia == linies_gantt[0])
            if h_usr_f is not None and h_ofi_f is not None:
                gantt_traces.append(go.Scatter(
                    x=[h_usr_f, h_ofi_f], y=[dlinia, dlinia],
                    mode="lines", line=dict(color=lcolor, width=2),
                    showlegend=False, hoverinfo="skip",
                ))
                if det["delta_min"]:
                    hh, mm = divmod(int(det["delta_min"]), 60)
                    lbl = f"+{hh}h {mm}min" if hh > 0 else f"+{mm}min"
                    gantt_ann.append(dict(
                        x=(h_usr_f + h_ofi_f) / 2, y=dlinia,
                        text=lbl, showarrow=False,
                        font=dict(size=9, color="#475569"), yshift=13,
                    ))
            if h_usr_f is not None:
                gantt_traces.append(go.Scatter(
                    x=[h_usr_f], y=[dlinia],
                    mode="markers+text",
                    marker=dict(color="#7dd3fc", size=11),
                    text=[h_usr_s], textposition="bottom center",
                    textfont=dict(size=8, color="#7dd3fc"),
                    name="Primer tweet usuari", legendgroup="usr",
                    showlegend=first_l,
                    hovertemplate=f"<b>{dlinia}</b> usuari: {h_usr_s}<extra></extra>",
                ))
            if h_ofi_f is not None:
                gantt_traces.append(go.Scatter(
                    x=[h_ofi_f], y=[dlinia],
                    mode="markers+text",
                    marker=dict(color="#f87171", size=11),
                    text=[h_ofi_s], textposition="bottom center",
                    textfont=dict(size=8, color="#f87171"),
                    name="Primer avís oficial", legendgroup="ofi",
                    showlegend=first_l,
                    hovertemplate=f"<b>{dlinia}</b> oficial: {h_ofi_s}<extra></extra>",
                ))
        # Extra: línies amb detecció d'usuari però sense resposta oficial
        for linia_ex in (linies_extra_usuari or []):
            if linia_ex in detection:
                det_ex   = detection[linia_ex]
                df_lu_ex = det_ex["df_l_u"]
                if len(df_lu_ex) > 0:
                    h_usr_s_ex = df_lu_ex.iloc[0]["hora"][:5]
                    h_usr_f_ex = _h(h_usr_s_ex)
                    if h_usr_f_ex is not None:
                        linies_gantt.append(linia_ex)
                        gantt_traces.append(go.Scatter(
                            x=[h_usr_f_ex], y=[linia_ex],
                            mode="markers+text",
                            marker=dict(color="#7dd3fc", size=11),
                            text=[h_usr_s_ex], textposition="bottom center",
                            textfont=dict(size=8, color="#7dd3fc"),
                            name="Primer tweet usuari", legendgroup="usr",
                            showlegend=False,
                            hovertemplate=f"<b>{linia_ex}</b> usuari: {h_usr_s_ex}"
                                          f" (sense avís oficial)<extra></extra>",
                        ))
        fig_gantt = go.Figure(data=gantt_traces)
        fig_gantt.update_layout(
            height=max(200, len(linies_gantt) * 52 + 80),
            margin=dict(l=20, r=20, t=20, b=50),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155", size=10),
            xaxis=dict(title="Hora del dia", range=[0, 24], dtick=2,
                       showgrid=True, gridcolor="#e2e8f0"),
            yaxis=dict(showgrid=False),
            legend=dict(orientation="h", y=1.08),
            annotations=gantt_ann,
        )
        st.plotly_chart(fig_gantt, use_container_width=True, key=f"ce_gantt_{dia}")

    with col_rank:
        st.markdown(
            "<div style='font-size:11px;font-weight:700;color:#475569;"
            "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
            "Rànquing: avantatge temporal (minuts)</div>",
            unsafe_allow_html=True,
        )
        rank_data = sorted(
            [(l, det["delta_min"]) for l, det in detection.items()
             if det["delta_min"] and det["delta_min"] > 0],
            key=lambda x: x[1], reverse=True,
        )
        if rank_data:
            rk_l, rk_d = zip(*rank_data)
            rk_c   = [LINE_COLORS.get(l, DEFAULT_COLOR) for l in rk_l]
            rk_t   = [f"+{int(d//60)}h {int(d%60)}min" if d >= 60 else f"+{int(d)}min"
                      for d in rk_d]
            rk_l_d = [_disp(l) for l in rk_l]
            fig_rank = go.Figure(go.Bar(
                x=list(rk_d), y=rk_l_d, orientation="h",
                marker_color=rk_c, text=rk_t, textposition="outside",
                hovertemplate="<b>%{y}</b>: %{x:.0f} min<extra></extra>",
            ))
            fig_rank.update_layout(
                height=max(200, len(rank_data) * 52 + 80),
                margin=dict(l=20, r=80, t=20, b=50),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#334155", size=10),
                xaxis=dict(showgrid=True, gridcolor="#e2e8f0", title="min"),
                yaxis=dict(showgrid=False),
            )
            st.plotly_chart(fig_rank, use_container_width=True, key=f"ce_rank_{dia}")
        else:
            st.caption("Cap avantatge temporal detectat.")

    st.divider()

    # ── Taula d'evidència semafòrica ──────────────────────────────────────────
    st.markdown(
        "<div style='font-size:11px;font-weight:700;color:#475569;"
        "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
        "Taula d'evidència per línia</div>",
        unsafe_allow_html=True,
    )
    if evidencia_override is not None:
        evid_rows = list(evidencia_override)
    else:
        evid_rows = []
        for linia in linies_actives:
            det     = detection[linia]
            n_pre_e = len(det["pre_of"])
            has_ofi = det["hora_of_inc"] != "99:99"
            delta_e = det["delta_min"]
            pre_c_e = (det["pre_of"]["confianza"].dropna()
                       if "confianza" in det["pre_of"].columns else pd.Series())
            conf_pre = f"{pre_c_e.mean():.3f}" if len(pre_c_e) > 0 else "—"
            pct_80_e = f"{(pre_c_e > 0.80).mean()*100:.0f}%" if len(pre_c_e) > 0 else "—"
            if n_pre_e > 0 and has_ofi and delta_e and delta_e > 0:
                estat = "🟢 Detecció precoç"
            elif n_pre_e > 0 and not has_ofi:
                estat = "🟡 Senyal social sense avís oficial"
            elif n_pre_e == 0 and has_ofi:
                estat = "⬜ Sense detecció social prèvia"
            else:
                estat = "⬜ Sense dades suficients"
            h_usr_e = det["pre_of"].iloc[0]["hora"][:5] if n_pre_e > 0 else "—"
            h_ofi_e = det["hora_of_inc"] if has_ofi else "—"
            if delta_e:
                hh_e, mm_e = divmod(int(delta_e), 60)
                delta_str_e = f"+{hh_e}h {mm_e}min" if hh_e > 0 else f"+{mm_e}min"
            else:
                delta_str_e = "—"
            evid_rows.append({
                "Línia":         _disp(linia),
                "Primer usuari": h_usr_e,
                "Primer oficial":h_ofi_e,
                "Avantatge":     delta_str_e,
                "n pre":         n_pre_e,
                "Conf. pre":     conf_pre,
                "% conf > 0.80": pct_80_e,
                "Estat":         estat,
            })
        # Extra: línies sense resposta oficial
        for linia_ex in (linies_extra_usuari or []):
            if linia_ex in detection:
                det_ex   = detection[linia_ex]
                df_lu_ex = det_ex["df_l_u"]
                h_usr_ex = df_lu_ex.iloc[0]["hora"][:5] if len(df_lu_ex) > 0 else "—"
                evid_rows.append({
                    "Línia":         linia_ex,
                    "Primer usuari": h_usr_ex,
                    "Primer oficial":"—",
                    "Avantatge":     "—",
                    "n pre":         len(df_lu_ex),
                    "Conf. pre":     "—",
                    "% conf > 0.80": "—",
                    "Estat":         "🟡 Senyal social sense avís oficial",
                })
    st.dataframe(pd.DataFrame(evid_rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── Corba acumulada de tweets d'incident ──────────────────────────────────
    st.markdown(
        "<div style='font-size:11px;font-weight:700;color:#475569;"
        "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
        "Corba acumulada de tweets d'incident (amb llindar oficial)</div>",
        unsafe_allow_html=True,
    )
    sel_curve = st.pills("Línies", linies_actives, selection_mode="multi",
                          default=linies_actives[:min(2, len(linies_actives))],
                          key=f"ce_curve_{dia}")
    if sel_curve:
        fig_cum = go.Figure()
        for linia in sel_curve:
            det    = detection[linia]
            df_lu3 = det["df_l_u"]
            is_q3  = ((df_lu3["caracter"] == "queixa") if "caracter" in df_lu3.columns
                      else pd.Series(False, index=df_lu3.index))
            is_i3  = (df_lu3["tipus_incident"].notna() &
                      ~df_lu3["tipus_incident"].isin(["sin_incidencia", "nan", ""]))
            df_r3  = df_lu3[is_q3 | is_i3].dropna(subset=["hora"]).sort_values("hora")
            if len(df_r3) == 0:
                continue
            lcolor = LINE_COLORS.get(linia, DEFAULT_COLOR)
            hours3 = df_r3["hora"].apply(lambda h: _h(str(h)[:5]) or 0)
            fig_cum.add_trace(go.Scatter(
                x=list(hours3), y=list(range(1, len(df_r3) + 1)),
                mode="lines+markers", name=linia,
                line=dict(color=lcolor, width=2), marker=dict(size=4),
                hovertemplate=f"<b>{linia}</b> %{{x:.1f}}h → %{{y}} tweets<extra></extra>",
            ))
            h_ofi3 = det["hora_of_inc"]
            if h_ofi3 != "99:99":
                fig_cum.add_vline(
                    x=_h(h_ofi3), line_dash="dash",
                    line_color=lcolor, line_width=1.5, opacity=0.7,
                    annotation_text=f"Oficial {linia} {h_ofi3}",
                    annotation_font_color=lcolor, annotation_font_size=8,
                    annotation_position="top right",
                )
        fig_cum.update_layout(
            height=300, margin=dict(l=40, r=20, t=30, b=40),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155", size=10),
            xaxis=dict(title="Hora", showgrid=True, gridcolor="#e2e8f0", dtick=2, range=[0, 24]),
            yaxis=dict(title="Tweets acumulats", showgrid=True, gridcolor="#e2e8f0"),
            legend=dict(orientation="h", y=1.08),
        )
        st.plotly_chart(fig_cum, use_container_width=True, key=f"ce_cum_{dia}")

    st.divider()

    # ── Validació estadística complementària ─────────────────────────────────
    # Càlcul sempre (fora de l'expander; Streamlit no pot diferir còmput)
    try:
        from scipy.stats import mannwhitneyu as _mwu
        _scipy_ok = True
    except ImportError:
        _scipy_ok = False

    N_MIN = 5

    def _cliffs_delta(a, b):
        a, b = list(a), list(b)
        gt = sum(1 for x in a for y in b if x > y)
        lt = sum(1 for x in a for y in b if x < y)
        return (gt - lt) / (len(a) * len(b)) if a and b else None

    def _cliff_label(d):
        if d is None:
            return "—"
        ad = abs(d)
        if ad < 0.147:
            return f"{d:+.3f} (negligible)"
        if ad < 0.33:
            return f"{d:+.3f} (petit)"
        if ad < 0.474:
            return f"{d:+.3f} (mig)"
        return f"{d:+.3f} (gran)"

    stat_rows = []
    box_data  = []
    for linia in linies_actives:
        det    = detection[linia]
        df_lu  = det["df_l_u"]
        hor_of = det["hora_of_inc"]
        is_q2  = ((df_lu["caracter"] == "queixa") if "caracter" in df_lu.columns
                  else pd.Series(False, index=df_lu.index))
        is_i2  = (df_lu["tipus_incident"].notna() &
                  ~df_lu["tipus_incident"].isin(["sin_incidencia", "nan", ""]))
        df_r2  = df_lu[is_q2 | is_i2].dropna(subset=["hora", "confianza"])
        if len(df_r2) == 0:
            continue

        pre_c  = (df_r2[df_r2["hora"] < hor_of]["confianza"]
                  if hor_of != "99:99" else pd.Series(dtype=float))
        post_c = (df_r2[df_r2["hora"] >= hor_of]["confianza"]
                  if hor_of != "99:99" else df_r2["confianza"])

        for v in pre_c:
            box_data.append({"Línia": linia, "Grup": "Pre-oficial", "confianza": v})
        for v in post_c:
            box_data.append({"Línia": linia, "Grup": "Post-oficial", "confianza": v})

        pval  = None
        cliff = None
        if _scipy_ok and len(pre_c) >= N_MIN and len(post_c) >= N_MIN:
            try:
                _, pval = _mwu(pre_c, post_c, alternative="two-sided")
                cliff   = _cliffs_delta(pre_c, post_c)
            except Exception:
                pass

        pct_high = float((pre_c > 0.80).mean() * 100) if len(pre_c) > 0 else None
        stat_rows.append({
            "_linia":       linia,
            "_pval":        pval,
            "Línia":        linia,
            "n pre":        len(pre_c),
            "Mit. pre":     round(float(pre_c.mean()), 3)   if len(pre_c) > 0 else None,
            "Med. pre":     round(float(pre_c.median()), 3) if len(pre_c) > 0 else None,
            "n post":       len(post_c),
            "Mit. post":    round(float(post_c.mean()), 3)  if len(post_c) > 0 else None,
            "Med. post":    round(float(post_c.median()), 3)if len(post_c) > 0 else None,
            "% pre > 0.80": round(pct_high, 1) if pct_high is not None else None,
            "p (BH)":       pval,
            "Cliff δ":      cliff,
        })

    # Benjamini-Hochberg correction
    valid_idx = [i for i, r in enumerate(stat_rows) if r["_pval"] is not None]
    if valid_idx:
        raw_pvals = [stat_rows[i]["_pval"] for i in valid_idx]
        m = len(raw_pvals)
        order = sorted(range(m), key=lambda k: raw_pvals[k])
        bh = [None] * m
        for rank, k in enumerate(order):
            bh[k] = raw_pvals[k] * m / (rank + 1)
        cur_min = 1.0
        for k in reversed(order):
            cur_min = min(cur_min, bh[k])
            bh[k] = cur_min
        for rank_i, stat_i in enumerate(valid_idx):
            stat_rows[stat_i]["p (BH)"] = min(bh[rank_i], 1.0)

    # Display: tot dins l'expander
    with st.expander("Validació estadística complementària · Mann-Whitney U + Cliff's δ"):
        st.caption(
            "El test es calcula únicament quan hi ha ≥ 5 tweets tant en el grup pre-oficial "
            "com en el post-oficial. En aquest cas d'estudi, diverses línies no compleixen "
            "aquest llindar; l'anàlisi estadística s'interpreta com a complementària i no com "
            "a evidència principal. La confiança reflecteix la sortida del classificador "
            "d'incidents, no una validació externa de la veracitat dels tweets."
        )
        if stat_rows:
            def _fmt(v, decimals=3):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return "—"
                return f"{v:.{decimals}f}"

            def _fmt_p(p):
                if p is None or (isinstance(p, float) and pd.isna(p)):
                    return f"— (n < {N_MIN})"
                s = f"{p:.4f}"
                if p < 0.001: return f"{s} ✓✓✓"
                if p < 0.01:  return f"{s} ✓✓"
                if p < 0.05:  return f"{s} ✓"
                return s

            st.markdown(
                "<div style='font-size:11px;font-weight:700;color:#475569;"
                "text-transform:uppercase;letter-spacing:1px;margin:4px 0 10px'>"
                "Mann-Whitney U + Cliff's δ · confiança pre vs post avís oficial "
                "(correcció Benjamini-Hochberg)</div>",
                unsafe_allow_html=True,
            )
            disp_cols = ["Línia", "n pre", "Mit. pre", "Med. pre",
                         "n post", "Mit. post", "Med. post",
                         "% pre > 0.80", "p (BH)", "Cliff δ"]
            df_disp = pd.DataFrame(stat_rows)[disp_cols].copy()
            df_disp["Mit. pre"]  = df_disp["Mit. pre"].apply(_fmt)
            df_disp["Med. pre"]  = df_disp["Med. pre"].apply(_fmt)
            df_disp["Mit. post"] = df_disp["Mit. post"].apply(_fmt)
            df_disp["Med. post"] = df_disp["Med. post"].apply(_fmt)
            df_disp["% pre > 0.80"] = df_disp["% pre > 0.80"].apply(
                lambda v: f"{v:.1f}%" if (v is not None and not (isinstance(v, float) and pd.isna(v))) else "—")
            df_disp["p (BH)"]  = df_disp["p (BH)"].apply(_fmt_p)
            df_disp["Cliff δ"] = df_disp["Cliff δ"].apply(_cliff_label)
            st.dataframe(df_disp, use_container_width=True, hide_index=True)
            st.caption(
                f"✓ p < 0.05 · ✓✓ p < 0.01 · ✓✓✓ p < 0.001 (p-valors corregits BH). "
                f"Test calculat només si n ≥ {N_MIN} en cada grup. "
                "Cliff's δ: |δ| < 0.147 negligible · 0.147-0.33 petit · 0.33-0.474 mig · ≥ 0.474 gran."
            )

            if box_data:
                df_box = pd.DataFrame(box_data)
                linies_box = [r["Línia"] for r in stat_rows]
                fig_box = go.Figure()
                pre_shown  = False
                post_shown = False
                for lin in linies_box:
                    lc = LINE_COLORS.get(lin, DEFAULT_COLOR)
                    for grup, color, shown_flag in [
                        ("Pre-oficial",  "#7dd3fc", pre_shown),
                        ("Post-oficial", "#f87171", post_shown),
                    ]:
                        vals = df_box[(df_box["Línia"] == lin) &
                                      (df_box["Grup"] == grup)]["confianza"].tolist()
                        if not vals:
                            continue
                        show_leg = not (pre_shown if grup == "Pre-oficial" else post_shown)
                        fig_box.add_trace(go.Box(
                            y=vals,
                            x=[lin] * len(vals),
                            name=grup,
                            legendgroup=grup,
                            marker_color=color,
                            boxpoints="all", jitter=0.4, pointpos=0,
                            marker=dict(size=5, opacity=0.55),
                            line=dict(width=1.5),
                            showlegend=show_leg,
                            offsetgroup=grup,
                        ))
                        if grup == "Pre-oficial":
                            pre_shown = True
                        else:
                            post_shown = True
                fig_box.update_layout(
                    height=320,
                    margin=dict(l=40, r=20, t=30, b=40),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#334155", size=11),
                    yaxis=dict(title="Confiança", range=[0.65, 1.02],
                               showgrid=True, gridcolor="#e2e8f0"),
                    xaxis=dict(showgrid=False),
                    boxmode="group",
                    legend=dict(orientation="h", y=1.08),
                    title=dict(
                        text="Distribució de confiança per línia: pre-oficial vs post-oficial",
                        font=dict(size=11, color="#64748b"), x=0,
                    ),
                )
                st.plotly_chart(fig_box, use_container_width=True,
                                key=f"ce_box_{dia}")

    st.divider()

    # ── Detall per línia ──────────────────────────────────────────────────────
    for linia in linies_actives:
        lcolor    = LINE_COLORS.get(linia, DEFAULT_COLOR)
        df_l      = df_dia[df_dia["linia"] == linia]
        det       = detection[linia]
        df_l_u    = det["df_l_u"]
        primer_of     = det["primer_of_inc"]   # primer avís d'incident (no rutinari)
        hora_of       = det["hora_of_inc"]
        pre_of        = det["pre_of"]
        delta_min = det["delta_min"]
        cand_ofi  = det["cand"].sort_values("hora") if len(det["cand"]) > 0 else det["cand"]

        # Header: nom línia + avantatge inline
        if delta_min:
            h, m = divmod(int(delta_min), 60)
            dt_txt = f"{h}h {m}min" if h > 0 else f"{m}min"
            dcolor = "#DC143C" if delta_min >= 60 else ("#F59E0B" if delta_min >= 30 else "#10B981")
            adv_badge = (
                f"<span style='margin-left:auto;background:{dcolor}22;"
                f"border:1px solid {dcolor}55;border-radius:20px;padding:3px 12px;"
                f"font-size:13px;font-weight:700;color:{dcolor}'>"
                f"{dt_txt} d'avantatge</span>"
            )
        else:
            adv_badge = ""

        st.markdown(
            f"<div style='display:flex;align-items:center;gap:12px;margin:24px 0 10px;"
            f"padding:10px 16px;background:linear-gradient(90deg,{lcolor}22 0%,transparent 100%);"
            f"border-radius:8px;border-left:3px solid {lcolor}'>"
            f"<span style='font-size:18px;font-weight:800;color:#0f172a'>Línia {_disp(linia)}</span>"
            f"<span style='font-size:12px;color:#64748b'>"
            f"{len(df_l)} tweets · {len(pre_of)} usuaris anticipats</span>"
            f"{adv_badge}</div>",
            unsafe_allow_html=True,
        )

        col_tl, col_detail = st.columns([1, 2])

        with col_tl:
            # Mini-timeline: tweets d'usuari per hora + línia vertical oficial
            if len(df_l_u) > 0:
                df_h = df_l_u.copy()
                df_h["h"] = df_h["hora"].str[:2].apply(
                    lambda x: int(x) if str(x).isdigit() else -1)
                hourly = (df_h[df_h["h"] >= 0]
                          .groupby("h").size().reset_index(name="n"))
                # Confiança mitjana per hora
                if "confianza" in df_h.columns:
                    hconf = (df_h[df_h["h"] >= 0]
                             .groupby("h")["confianza"].mean()
                             .reset_index(name="conf"))
                    hourly = hourly.merge(hconf, on="h", how="left")
                else:
                    hourly["conf"] = None

                ofi_h = (int(hora_of[:2])
                         if hora_of != "99:99" and hora_of[:2].isdigit() else None)
                bar_colors = [
                    "#DC143C" if (ofi_h is not None and h >= ofi_h) else lcolor
                    for h in hourly["h"]
                ]
                fig_tl = go.Figure(go.Bar(
                    x=hourly["h"], y=hourly["n"],
                    marker_color=bar_colors,
                    hovertemplate="Hora %{x}h: %{y} tw<extra></extra>",
                    name="tweets",
                ))
                # Línia de confiança mitjana (eix dret)
                if hourly["conf"].notna().any():
                    fig_tl.add_trace(go.Scatter(
                        x=hourly["h"], y=hourly["conf"],
                        mode="lines+markers",
                        name="conf. mitjana",
                        line=dict(color="#F59E0B", width=1.5, dash="dot"),
                        marker=dict(size=4, color="#F59E0B"),
                        yaxis="y2",
                        hovertemplate="Hora %{x}h: conf. %{y:.2f}<extra></extra>",
                    ))
                if ofi_h is not None:
                    fig_tl.add_vline(
                        x=ofi_h - 0.5, line_dash="dash",
                        line_color="#DC143C", line_width=2,
                        annotation_text="↑ oficial",
                        annotation_font_color="#DC143C",
                        annotation_font_size=9,
                        annotation_position="top right",
                    )
                fig_tl.update_layout(
                    height=185,
                    margin=dict(l=24, r=36, t=28, b=28),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#334155", size=10),
                    xaxis=dict(showgrid=False, title="hora", dtick=2),
                    yaxis=dict(showgrid=True, gridcolor="#e2e8f0", title="tw"),
                    yaxis2=dict(
                        overlaying="y", side="right",
                        range=[0.70, 1.02], showgrid=False,
                        tickformat=".2f",
                        title=dict(text="conf.", font=dict(size=9, color="#F59E0B")),
                        tickfont=dict(size=8, color="#F59E0B"),
                    ),
                    legend=dict(orientation="h", y=1.12, font=dict(size=8)),
                    title=dict(text="Tweets usuaris/hora · confiança",
                               font=dict(size=10, color="#64748b"), x=0),
                )
                st.plotly_chart(fig_tl, use_container_width=True,
                                key=f"ce_tl_{dia}_{linia}")

            # Tipus d'incident (mini llista de text, no gràfic)
            tc = (df_l["tipus_incident"].dropna()
                  .replace("sin_incidencia", pd.NA).dropna()
                  .value_counts())
            if len(tc) > 0:
                items = "".join(
                    f"<div style='display:flex;justify-content:space-between;"
                    f"padding:2px 0;border-bottom:1px solid #e2e8f0'>"
                    f"<span style='font-size:11px;color:{TIPO_COLORS.get(t, DEFAULT_COLOR)}'>"
                    f"● {t}</span>"
                    f"<span style='font-size:11px;font-weight:700;color:#475569'>{n}</span></div>"
                    for t, n in tc.items()
                )
                st.markdown(
                    f"<div style='margin-top:8px;padding:8px 10px;background:#f8fafc;"
                    f"border-radius:6px;border:1px solid #e2e8f0'>"
                    f"<div style='font-size:9px;color:#64748b;text-transform:uppercase;"
                    f"letter-spacing:1px;margin-bottom:5px'>Tipus d'incident</div>"
                    f"{items}</div>",
                    unsafe_allow_html=True,
                )

        with col_detail:
            if delta_min:
                st.markdown(_delta_badge(delta_min), unsafe_allow_html=True)

            # Tweets rellevants (queixes + incidents), tot el dia
            is_q = (df_l_u["caracter"] == "queixa") if "caracter" in df_l_u.columns \
                   else pd.Series(False, index=df_l_u.index)
            is_i = df_l_u["tipus_incident"].notna() & \
                   ~df_l_u["tipus_incident"].isin(["sin_incidencia", "nan", ""])
            df_rel = df_l_u[is_q | is_i].dropna(subset=["hora"]).sort_values("hora").reset_index(drop=True)

            # Totes les comunicacions oficials (tots els canals @rod*cat, @rodalies, etc.)
            ofi_sorted = (cand_ofi.sort_values("hora").reset_index(drop=True)
                          if len(cand_ofi) > 0 else pd.DataFrame())

            if len(df_rel) == 0:
                st.caption("Cap tweet de queixa o incident classificat per a aquesta línia.")
            else:
                # ── Clustering per gaps de temps (incidents separats al llarg del dia)
                GAP_MIN = 120
                clusters = []
                grp = [0]
                for i in range(1, len(df_rel)):
                    try:
                        t1 = pd.Timestamp(f"{dia} {df_rel.iloc[i-1]['hora'][:5]}")
                        t2 = pd.Timestamp(f"{dia} {df_rel.iloc[i]['hora'][:5]}")
                        gap = (t2 - t1).total_seconds() / 60
                    except Exception:
                        gap = 0
                    if gap <= GAP_MIN:
                        grp.append(i)
                    else:
                        clusters.append(df_rel.iloc[grp].reset_index(drop=True))
                        grp = [i]
                clusters.append(df_rel.iloc[grp].reset_index(drop=True))

                n_rel  = len(df_rel)
                n_pre  = len(df_rel[df_rel["hora"] < hora_of]) if hora_of != "99:99" else n_rel
                conf_m = df_rel["confianza"].dropna().mean() if "confianza" in df_rel.columns else None
                conf_txt = f" · conf. {conf_m:.2f}" if conf_m is not None else ""
                st.markdown(
                    f"<div style='font-size:12px;color:#475569;margin-bottom:10px;line-height:1.7'>"
                    f"<b style='color:#0f172a'>{n_rel} tweets rellevants</b>{conf_txt} · "
                    f"<b style='color:{lcolor}'>{len(clusters)} incident"
                    f"{'s' if len(clusters)>1 else ''}</b><br>"
                    f"<span style='color:{lcolor}'>{n_pre} anteriors al primer avís oficial</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                used_ofi = set()
                for ci, cl in enumerate(clusters):
                    t_s = str(cl.iloc[0]["hora"])[:5]
                    t_e = str(cl.iloc[-1]["hora"])[:5]
                    n_cl = len(cl)

                    # Confiança mitjana del cluster
                    conf_cl = (cl["confianza"].dropna().mean()
                               if "confianza" in cl.columns else None)
                    if conf_cl is not None:
                        cc = ("#10B981" if conf_cl >= 0.90
                              else ("#F59E0B" if conf_cl >= 0.80 else "#F97316"))
                        conf_badge = (
                            f"<span style='margin-left:auto;font-size:11px;"
                            f"font-weight:700;color:{cc}'>conf. {conf_cl:.2f}</span>"
                        )
                    else:
                        conf_badge = ""

                    # Header de l'incident
                    st.markdown(
                        f"<div style='margin:14px 0 5px;padding:6px 12px;"
                        f"background:{lcolor}18;border-radius:6px;"
                        f"border-left:3px solid {lcolor};"
                        f"display:flex;align-items:center'>"
                        f"<span style='font-size:12px;font-weight:800;color:{lcolor}'>"
                        f"Incident #{ci+1}</span>"
                        f"<span style='font-size:11px;color:#64748b'>"
                        f" · {t_s} – {t_e} · {n_cl} tweets</span>"
                        f"{conf_badge}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    # Tweets del cluster
                    cards = "".join(
                        _tweet_card(r, lcolor, show_confianza=True)
                        for _, r in cl.iterrows()
                    )
                    st.markdown(cards, unsafe_allow_html=True)

                    # Comunicació oficial posterior a l'inici del cluster
                    if len(ofi_sorted) > 0:
                        matching = ofi_sorted[
                            (ofi_sorted["hora"] >= t_s) &
                            (~ofi_sorted.index.isin(used_ofi))
                        ]
                        if len(matching) > 0:
                            st.markdown(
                                "<div style='margin:5px 0 3px;font-size:10px;"
                                "font-weight:700;color:#DC143C;"
                                "text-transform:uppercase;letter-spacing:1px'>"
                                "↓ Comunicació oficial</div>",
                                unsafe_allow_html=True,
                            )
                            for idx, r_ofi in matching.iterrows():
                                st.markdown(_tweet_card(r_ofi, "#DC143C"),
                                            unsafe_allow_html=True)
                                used_ofi.add(idx)
                        else:
                            st.markdown(
                                "<div style='font-size:11px;color:#475569;"
                                "font-style:italic;margin:5px 0;padding:6px 10px;"
                                "background:#f1f5f9;border-radius:6px;"
                                "border-left:2px solid #cbd5e1'>"
                                "Sense comunicació oficial posterior per a aquest incident."
                                "</div>",
                                unsafe_allow_html=True,
                            )

                # Comunicacions oficials no associades a cap cluster
                if len(ofi_sorted) > 0:
                    remaining = ofi_sorted[~ofi_sorted.index.isin(used_ofi)]
                    if len(remaining) > 0:
                        st.markdown(
                            f"<div style='margin-top:14px;font-size:11px;font-weight:700;"
                            f"color:#475569;text-transform:uppercase;letter-spacing:1px;"
                            f"margin-bottom:4px'>Altres comunicacions oficials ({len(remaining)})</div>",
                            unsafe_allow_html=True,
                        )
                        for _, r_ofi in remaining.iterrows():
                            st.markdown(_tweet_card(r_ofi, "#DC143C"), unsafe_allow_html=True)
                elif len(ofi_sorted) == 0:
                    st.markdown(
                        "<div style='color:#64748b;font-size:13px;font-style:italic;"
                        "margin-top:12px'>"
                        "Cap comunicació oficial trobada per a aquesta línia aquell dia."
                        "</div>",
                        unsafe_allow_html=True,
                    )

    st.divider()

    if bloc_especial:
        be     = bloc_especial
        bcolor = be.get("color", "#f59e0b")
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:12px;margin:24px 0 12px;"
            f"padding:10px 16px;background:linear-gradient(90deg,{bcolor}22 0%,transparent 100%);"
            f"border-radius:8px;border-left:3px solid {bcolor}'>"
            f"<span style='font-size:18px;font-weight:800;color:#0f172a'>{be['titol']}</span>"
            f"<span style='font-size:12px;color:#64748b'>{be['subtitol']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        hora_limit = be.get("hora_limit", "23:59")
        df_be  = df_dia[
            df_dia["tweet_text"].str.lower().str.contains(
                be["kws_regex"], na=False, regex=True)
        ].sort_values("hora")
        df_be_u = df_be[~es_oficial.reindex(df_be.index, fill_value=False)]
        df_be_o = df_be[es_oficial.reindex(df_be.index, fill_value=False)]

        if be.get("delta_mins") is not None:
            st.markdown(_delta_badge(be["delta_mins"]), unsafe_allow_html=True)
        else:
            df_be_u_hl = df_be_u[df_be_u["hora"] <= hora_limit].sort_values("hora")
            df_be_o_s  = df_be_o.sort_values("hora")
            if len(df_be_u_hl) > 0 and len(df_be_o_s) > 0:
                try:
                    t1 = pd.Timestamp(f"{dia} {df_be_u_hl.iloc[0]['hora'][:5]}")
                    t2 = pd.Timestamp(f"{dia} {df_be_o_s.iloc[0]['hora'][:5]}")
                    delta_min = (t2 - t1).total_seconds() / 60
                    if delta_min > 0:
                        st.markdown(_delta_badge(delta_min), unsafe_allow_html=True)
                except Exception:
                    pass

        bec1, bec2 = st.columns(2)
        with bec1:
            st.markdown(
                "<div style='font-size:11px;font-weight:700;color:#475569;"
                "text-transform:uppercase;letter-spacing:1px;margin-bottom:6px'>"
                "Usuaris detecten l'incident</div>",
                unsafe_allow_html=True,
            )
            for _, r in df_be_u[df_be_u["hora"] <= hora_limit].iterrows():
                st.markdown(_tweet_card(r, bcolor), unsafe_allow_html=True)
        with bec2:
            st.markdown(
                "<div style='font-size:11px;font-weight:700;color:#475569;"
                "text-transform:uppercase;letter-spacing:1px;margin-bottom:6px'>"
                "Comunicació oficial</div>",
                unsafe_allow_html=True,
            )
            for _, r in df_be_o[df_be_o["hora"] <= hora_limit].iterrows():
                st.markdown(_tweet_card(r, "#DC143C"), unsafe_allow_html=True)

        st.divider()

    st.subheader("Tweets d'incident sense línia assignada")
    st.caption("Tweets classificats com a incident (confiança > 0.80) però sense línia detectada")
    df_sense_linia = df_dia[
        df_dia["linia"].isna() &
        df_dia["tipus_incident"].notna() &
        (df_dia["tipus_incident"] != "sin_incidencia") &
        (pd.to_numeric(df_dia["confianza"], errors="coerce") >= 0.80)
    ].sort_values("hora")
    if len(df_sense_linia) > 0:
        for _, r in df_sense_linia.iterrows():
            tc = TIPO_COLORS.get(str(r.get("tipus_incident", "")), DEFAULT_COLOR)
            st.markdown(_tweet_card(r, tc, show_confianza=True), unsafe_allow_html=True)
    else:
        st.info("No s'han trobat tweets d'incident sense línia assignada.")


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG + CSS
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Anàlisi X · Rodalies", layout="wide", page_icon="🚆")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ══ BASE ══════════════════════════════════════════════════════ */
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
.stApp { background: #ffffff !important; }
.main  { background: #ffffff !important; }
.main .block-container {
    padding-top: 2.5rem !important;
    padding-bottom: 5rem !important;
    max-width: 1400px !important;
}
p, li { line-height: 1.75 !important; color: #1e293b !important; font-size: 15px !important; }
hr    { border-color: #e2e8f0 !important; opacity: 1 !important; }

/* ══ CAPTIONS I TEXT SECUNDARI ════════════════════════════════ */
[data-testid="stCaptionContainer"] p { color: #64748b !important; font-size: 13px !important; }
[data-testid="stMarkdownContainer"] p { color: #1e293b !important; font-size: 15px !important; }
[data-testid="stText"] { color: #1e293b !important; }

/* ══ SIDEBAR ═══════════════════════════════════════════════════ */
[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 60%, #e8edf2 100%) !important;
    border-right: 1px solid #e2e8f0 !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] div { color: #334155 !important; }

/* ══ TITOLS ════════════════════════════════════════════════════ */
h1 {
    font-size: 2.4rem !important;
    font-weight: 800 !important;
    letter-spacing: -1px !important;
    color: #0f172a !important;
}
h2 {
    font-size: 1.25rem !important;
    font-weight: 700 !important;
    color: #0f172a !important;
    border-left: 3px solid #0284c7 !important;
    padding-left: 10px !important;
    margin-top: 1.4rem !important;
}
h3 { color: #1e293b !important; font-weight: 600 !important; font-size: 1.05rem !important; }

/* ══ METRIC CARDS ══════════════════════════════════════════════ */
[data-testid="metric-container"] {
    background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%) !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
    padding: 20px 24px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
    transition: all 0.2s ease !important;
}
[data-testid="metric-container"]:hover {
    border-color: #0284c7 !important;
    box-shadow: 0 4px 16px rgba(2,132,199,0.12) !important;
    transform: translateY(-1px) !important;
}
[data-testid="stMetricLabel"] > div { color: #64748b !important; font-size: 13px !important; text-transform: uppercase !important; letter-spacing: 0.8px !important; font-weight: 600 !important; }
[data-testid="stMetricValue"] > div { color: #0f172a !important; font-size: 2.2rem !important; font-weight: 800 !important; letter-spacing: -1px !important; }
[data-testid="stMetricDelta"] svg   { display: none !important; }

/* ══ EXPANDERS ═════════════════════════════════════════════════ */
[data-testid="stExpander"] {
    background: #f8fafc !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    color: #475569 !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 10px 16px !important;
}
[data-testid="stExpander"] summary:hover { color: #0f172a !important; }

/* ══ INFO / ALERT ══════════════════════════════════════════════ */
[data-testid="stInfo"] {
    background: #eff6ff !important;
    border: none !important;
    border-left: 3px solid #3b82f6 !important;
    border-radius: 8px !important;
    color: #1e40af !important;
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
    color: #475569 !important;
    transition: background 0.15s, color 0.15s !important;
    width: 100% !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: rgba(0,0,0,0.05) !important;
    color: #0f172a !important;
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
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 7px !important;
    padding: 5px 14px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #334155 !important;
    transition: all 0.15s ease !important;
    cursor: pointer !important;
}
[role="radiogroup"] label:hover {
    border-color: #0284c7 !important;
    color: #0284c7 !important;
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
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 8px !important;
    color: #0f172a !important;
    font-size: 13px !important;
}
[data-testid="stSelectbox"] > div > div:hover,
[data-testid="stDateInput"] > div > div > input:focus,
[data-testid="stNumberInput"] > div > div > input:focus {
    border-color: #0284c7 !important;
}

/* ══ DATAFRAME ═════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* ══ DIVIDER ═══════════════════════════════════════════════════ */
[data-testid="stDivider"] { background: #e2e8f0 !important; }

/* ══ PLOTLY — TEXTOS SVG ═══════════════════════════════════════ */
.js-plotly-plot .plotly text { fill: #1e293b !important; }
.js-plotly-plot .plotly .gtitle text { fill: #0f172a !important; }

/* ══ PILLS (st.pills widget) ═══════════════════════════════════ */
[data-testid="stPills"] button {
    background: #f1f5f9 !important;
    color: #334155 !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 20px !important;
}
[data-testid="stPills"] button:hover {
    background: #e2e8f0 !important;
    border-color: #0284c7 !important;
    color: #0284c7 !important;
}
[data-testid="stPills"] button[aria-pressed="true"],
[data-testid="stPills"] button[kind="pills"][data-active="true"],
[data-testid="stPills"] button[class*="active"] {
    background: #0284c7 !important;
    color: #ffffff !important;
    border-color: #0284c7 !important;
}

/* ══ HERO ══════════════════════════════════════════════════════ */
.hero-wrap  { display:flex; align-items:center; gap:24px; padding:32px 0 16px; }
.hero-title { font-size:2.4rem; font-weight:800; color:#0f172a; margin:0; line-height:1.15; letter-spacing:-1px; }
.hero-sub   { font-size:1rem; color:#475569; margin:6px 0 0; line-height:1.6; }
.hero-badge {
    display:inline-flex; align-items:center; gap:8px;
    background:linear-gradient(135deg,#eff6ff,#f0f9ff); border:1px solid #bae6fd;
    border-radius:20px; padding:5px 14px; font-size:12px; color:#0284c7;
    font-weight:600; margin-top:14px; box-shadow:0 2px 8px rgba(0,0,0,0.06);
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
        f'<div><div style="font-size:16px;font-weight:700;color:#0f172a">Anàlisi X · Rodalies</div>'
        f'<div style="font-size:11px;color:#64748b">Detecció d\'incidències</div></div></div>',
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Pàgina",
        ["Inici", "Mapa geogràfic", "Anàlisi temporal",
         "Anàlisi per línies", "Anàlisi d'incidències",
         "Incidències per línia", "20 Gen — Cas d'Estudi",
         "9 Feb — Cas d'Estudi",
         "13 Feb — Cas d'Estudi"],
        label_visibility="collapsed",
        key="nav_page",
    )

    st.markdown(
        "<div style='margin:6px 0 10px;border-top:1px solid #e2e8f0'></div>"
        "<div style='font-size:13px;font-weight:700;color:#64748b;"
        "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:14px'>"
        "Filtres globals</div>",
        unsafe_allow_html=True,
    )

    fil_lines     = st.pills("Línia",    ALL_LINES,     selection_mode="multi",
                              default=ALL_LINES,          key="fil_lines")
    fil_idiomes   = st.pills("Idioma",   ALL_IDIOMES,   selection_mode="multi",
                              default=list(ALL_IDIOMES),  key="fil_idiomes")
    fil_caracters = st.pills("Caràcter", ALL_CARACTERS, selection_mode="multi",
                              default=list(ALL_CARACTERS), key="fil_caracters")

    rb_col, date_col = st.columns([1, 5])
    with rb_col:
        st.markdown(
            "<div style='margin-top:28px'></div>"
            "<style>[data-testid='stSidebar'] [data-testid='stButton']:last-of-type button {"
            "display:flex !important;align-items:center !important;"
            "justify-content:center !important;font-size:18px !important;"
            "padding:0 !important;height:38px !important;}</style>",
            unsafe_allow_html=True,
        )
        if st.button("↺", key="reset_dates", help="Restablir al període complet",
                     use_container_width=True):
            st.session_state["fil_dates"] = (CAL_MIN, CAL_MAX)
    with date_col:
        fil_dates = st.date_input(
            "Període de temps",
            value=st.session_state.get("fil_dates", (CAL_MIN, CAL_MAX)),
            min_value=CAL_MIN,
            max_value=CAL_MAX,
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
        "<div style='margin-top:32px;padding-top:14px;border-top:1px solid #e2e8f0;"
        "text-align:center;font-size:10px;color:#64748b;line-height:1.6'>"
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
        f'<div style="margin-top:14px;font-size:14px;color:#475569;font-weight:500">'
        f'by <span style="color:#0f172a;font-weight:700">Marina Castellano</span>'
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
    with c1:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Tweets al dataset</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{len(df):,}</div>"
            f"</div>", unsafe_allow_html=True)
    with c2:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Tweets amb estació</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{df_exp['tweet_id'].nunique():,}</div>"
            f"</div>", unsafe_allow_html=True)
    with c3:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Estacions detectades</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{df_exp['station'].nunique() if len(df_exp) else 0}</div>"
            f"</div>", unsafe_allow_html=True)
    with c4:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Dies amb dades</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{df['date'].nunique()}</div>"
            f"</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("Incidències detectades (període complet)")

    inc_total = df_inc[df_inc["tipo_incidencia"].isin(ALL_TIPOS)]
    pct_inc   = round(len(inc_total) / len(df_inc) * 100, 1) if len(df_inc) > 0 else 0

    i1, i2, i3, i4 = st.columns(4)
    with i1:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Tweets d'incident</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{len(inc_total):,}</div>"
            f"</div>", unsafe_allow_html=True)
    with i2:
        tipo_frec = (inc_total["tipo_incidencia"].mode().iloc[0]
                     if len(inc_total) > 0 else "—")
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Tipus més freqüent</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{tipo_frec}</div>"
            f"</div>", unsafe_allow_html=True)
    with i3:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Mesos amb incidents</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{inc_total['month'].nunique()}</div>"
            f"</div>", unsafe_allow_html=True)
    with i4:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>% sobre total</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{pct_inc}%</div>"
            f"</div>", unsafe_allow_html=True)

    st.divider()

    # Grafic rapid: distribucio per tipus (landing page preview)
    if len(inc_total) > 0:
        tcol1, tcol2 = st.columns(2)

        with tcol1:
            st.markdown("**Distribució per tipus d'incidència**")
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
                font=dict(color="#334155"),
            )
            st.plotly_chart(fig_t, use_container_width=True)

        with tcol2:
            st.markdown("**Evolució mensual d'incidents**")
            inc_monthly = (inc_total[inc_total["date"] >= DATA_START]
                           .groupby("month").size()
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
                font=dict(color="#334155"),
            )
            st.plotly_chart(fig_im, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: MAPA GEOGRAFIC
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Mapa geogràfic":

    st.title("Mapa geogràfic")
    st.markdown(
        "<p style='color:#475569;font-size:0.95rem;margin:-8px 0 24px;line-height:1.7'>"
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
    lc1, lc2 = st.columns([2, 1])
    with lc1:
        label_mode = st.radio(
            "Etiquetes estacions",
            ["Noms complets", "Codi de línia"],
            horizontal=True, key="label_mode",
        )
    with lc2:
        use_top_n_map = st.toggle("Limitar a Top N", value=False, key="topn_map_toggle")
    top_n_map = 10
    if use_top_n_map:
        top_n_map = st.number_input(
            "N estacions (per tweets)", min_value=1,
            max_value=50, value=10, step=1, key="top_n_map_val",
        )
    if use_top_n_map:
        top_rows    = station_agg.nlargest(int(top_n_map), "n_tweets")
        labeled_ids = set(top_rows["station"])
        label_map   = {r["station"]: (r["station"] if label_mode == "Noms complets" else r["line"])
                       for _, r in top_rows.iterrows()}
    else:
        labeled_ids = set(station_agg["station"])
        label_map   = {r["station"]: (r["station"] if label_mode == "Noms complets" else r["line"])
                       for _, r in station_agg.iterrows()}

    # ── MAP 1: Punts (amplada completa) ──────────────────────────────────────
    st.markdown(
        "<div style='display:flex;align-items:center;gap:14px;margin:0 0 10px;"
        "padding:12px 16px;background:linear-gradient(90deg,#f0f9ff 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #7dd3fc'>"
        "<div style='width:26px;height:26px;background:#7dd3fc22;border:1px solid #7dd3fc55;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#0284c7;flex-shrink:0'>1</div>"
        "<div>"
        "<div style='font-size:9px;color:#0284c7;font-weight:700;letter-spacing:1.5px'>MAPA 1</div>"
        "<div style='font-size:15px;color:#0f172a;font-weight:600;margin-top:1px'>Distribució per estació</div>"
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
                        opacity=0.65, tooltip=f"Línia {line}").add_to(m1)

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
        more = (f"<div style='font-size:11px;color:#475569;text-align:center;"
                f"padding-top:4px'>+ {n-5} tweets més...</div>") if n > 5 else ""
        popup_html = (
            f"<div style='width:300px;font-family:sans-serif'>"
            f"<div style='font-weight:700;font-size:14px;color:{color};"
            f"margin-bottom:4px'>{name}</div>"
            f"<div style='font-size:11px;color:#64748b;margin-bottom:8px'>"
            f"Línia {row['line'] or 'N/D'} &nbsp;·&nbsp; {n} tweet{'s' if n > 1 else ''}</div>"
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
        f'<span style="font-size:11px;color:#334155;font-family:sans-serif">{l}</span>'
        f'</div>'
        for l in active_lines
    )
    folium.Element(
        f'<div style="position:fixed;bottom:24px;left:16px;z-index:9999;'
        f'background:rgba(8,14,26,0.88);backdrop-filter:blur(6px);'
        f'border:1px solid rgba(51,65,85,0.8);border-radius:10px;'
        f'padding:12px 16px;box-shadow:0 4px 24px rgba(0,0,0,0.5);">'
        f'<div style="font-size:11px;font-weight:700;color:#475569;'
        f'letter-spacing:1px;text-transform:uppercase;margin-bottom:9px;'
        f'font-family:sans-serif">Línies</div>'
        f'{legend_items_html}</div>'
    ).add_to(m1.get_root().html)

    st_folium(m1, width=None, height=650, returned_objects=[], key="map_pts")

    # ── Llegenda (expander sota mapa 1) ───────────────────────────────────────
    with st.expander("Línies actives — veure estacions"):
        leg_cols = st.columns(min(len(active_lines), 4))
        for i, line in enumerate(active_lines):
            color  = LINE_COLORS.get(line, DEFAULT_COLOR)
            n_tw   = line_tweet_counts.get(line, 0)
            sts    = stations_raw.get(line, [])
            st_items = "".join(
                f"<div style='font-size:10.5px;color:#334155;padding:2px 0 2px 10px;"
                f"border-left:2px solid {color}55;margin:2px 0'>· {s['name']}</div>"
                for s in sts
            )
            with leg_cols[i % len(leg_cols)]:
                st.markdown(
                    f"<div style='margin-bottom:10px'>"
                    f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>"
                    f"<div style='width:18px;height:6px;background:{color};border-radius:3px'></div>"
                    f"<span style='font-weight:700;font-size:13px;color:#0f172a'>{line}</span>"
                    f"<span style='color:#64748b;font-size:11px'>{n_tw} tw</span></div>"
                    f"{st_items}</div>",
                    unsafe_allow_html=True,
                )

    # ── MAP 2: Heatmap ────────────────────────────────────────────────────────
    st.markdown(
        "<div style='display:flex;align-items:center;gap:14px;margin:28px 0 10px;"
        "padding:12px 16px;background:linear-gradient(90deg,#f0f9ff 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #fb923c'>"
        "<div style='width:26px;height:26px;background:#fb923c22;border:1px solid #fb923c55;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#ea580c;flex-shrink:0'>2</div>"
        "<div>"
        "<div style='font-size:9px;color:#ea580c;font-weight:700;letter-spacing:1.5px'>MAPA 2</div>"
        "<div style='font-size:15px;color:#0f172a;font-weight:600;margin-top:1px'>Mapa de calor — densitat de tweets</div>"
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
        "padding:12px 16px;background:linear-gradient(90deg,#f0f9ff 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #a78bfa'>"
        "<div style='width:26px;height:26px;background:#a78bfa22;border:1px solid #a78bfa55;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#6d28d9;flex-shrink:0'>3</div>"
        "<div>"
        "<div style='font-size:9px;color:#6d28d9;font-weight:700;letter-spacing:1.5px'>MAPA 3</div>"
        "<div style='font-size:15px;color:#0f172a;font-weight:600;margin-top:1px'>Concentració 3D per zones</div>"
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
                    "<div style='background:#ffffff;padding:8px 12px;border-radius:6px;"
                    "border:1px solid #e2e8f0;font-family:sans-serif;box-shadow:0 2px 8px rgba(0,0,0,0.12)'>"
                    "<div style='color:#0284c7;font-weight:700;font-size:13px'>{station}</div>"
                    "<div style='color:#64748b;font-size:11px'>Línia {line}</div>"
                    "<div style='color:#0f172a;font-size:12px;margin-top:3px'>"
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
        "padding:12px 16px;background:linear-gradient(90deg,#f0f9ff 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #34d399'>"
        "<div style='width:26px;height:26px;background:#34d39922;border:1px solid #34d39955;"
        "border-radius:6px;display:flex;align-items:center;justify-content:center;"
        "font-size:12px;font-weight:700;color:#059669;flex-shrink:0'>4</div>"
        "<div>"
        "<div style='font-size:9px;color:#059669;font-weight:700;letter-spacing:1.5px'>MAPA 4</div>"
        "<div style='font-size:15px;color:#0f172a;font-weight:600;margin-top:1px'>Agrupació per clusters</div>"
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
                f"<b>{row['station']}</b><br>Línia: {row['line']}<br>"
                f"{row['n_tweets']} tweets", max_width=200
            ),
            icon=folium.Icon(color="lightgray", icon_color=color, icon="train",
                             prefix="fa"),
        ).add_to(cluster_group)
    st_folium(m4, width=None, height=480, returned_objects=[], key="map_cluster")

    # Taula
    st.divider()
    with st.expander("Veure tweets amb estació detectada"):
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
elif page == "Anàlisi temporal":

    st.title("Anàlisi temporal")

    tc1, tc2 = st.columns([3, 1])
    with tc1:
        top_n_enabled_t = st.toggle("Filtrar per Top N dies més actius",
                                     value=False, key="topn_enabled_temporal")
    top_n_t = 10
    if top_n_enabled_t:
        with tc2:
            top_n_t = st.number_input("N dies", min_value=3, max_value=60,
                                       value=10, step=1, key="topn_val_temporal")

    # df_t_base = tot el rang sense Top N (per a hora i comparativa mensual)
    df_t_base = apply_filters(df, fil_lines, fil_idiomes, fil_caracters,
                               date_start_str, date_end_str, use_lines_list=True)
    if top_n_enabled_t and len(df_t_base) > 0:
        top_dates_t = df_t_base.groupby("date").size().nlargest(int(top_n_t)).index
        df_t = df_t_base[df_t_base["date"].isin(top_dates_t)]
    else:
        df_t = df_t_base

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Tweets filtrats</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{len(df_t):,}</div>"
            f"</div>", unsafe_allow_html=True)
    with m2:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Dies amb activitat</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{df_t['date'].nunique()}</div>"
            f"</div>", unsafe_allow_html=True)
    with m3:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Mesos amb activitat</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{df_t_base['month'].nunique()}</div>"
            f"</div>", unsafe_allow_html=True)
    with m4:
        st.markdown(
            f"<div>"
            f"<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:700'>Tweets totals</div>"
            f"<div style='font-size:20px;font-weight:400;color:#334155'>{len(df):,}</div>"
            f"</div>", unsafe_allow_html=True)
    st.divider()

    # ── Donut distribució per caràcter ────────────────────────────────────────
    st.subheader("Distribució per tipus de tweet")
    if len(df_t) > 0:
        car_counts = df_t["caracter"].value_counts().reset_index()
        car_counts.columns = ["caracter", "n"]
        fig_donut = go.Figure(go.Pie(
            labels=car_counts["caracter"],
            values=car_counts["n"],
            hole=0.55,
            marker=dict(colors=[CARACTER_COLORS.get(c, DEFAULT_COLOR)
                                 for c in car_counts["caracter"]]),
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} tweets (%{percent})<extra></extra>",
        ))
        fig_donut.update_layout(
            height=320,
            margin=dict(t=20, b=60),
            showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.05),
            annotations=[dict(text=f"{len(df_t):,}<br><span style='font-size:11px'>tweets</span>",
                              x=0.5, y=0.5, font_size=16, showarrow=False,
                              font_color="#0f172a")],
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155"),
        )
        st.plotly_chart(fig_donut, use_container_width=True)

        # Cards de tweets de mostra (un per caracter, ordenats per tipus)
        n_show = min(int(top_n_t) if top_n_enabled_t else 6, len(df_t))
        sample = (df_t[["tweet_text", "caracter", "date"]]
                  .dropna(subset=["tweet_text"])
                  .sort_values("caracter")
                  .head(n_show))
        for _, r in sample.iterrows():
            col_c = CARACTER_COLORS.get(str(r["caracter"]), DEFAULT_COLOR)
            st.markdown(
                f"<div style='padding:8px 14px;margin-bottom:5px;background:#f8fafc;"
                f"border-radius:6px;border-left:3px solid {col_c};border:1px solid #e2e8f0;border-left:3px solid {col_c}'>"
                f"<span style='font-size:10px;color:{col_c};font-weight:700;"
                f"text-transform:uppercase'>{r['caracter']}</span> "
                f"<span style='font-size:10px;color:#64748b'>{r['date']}</span><br>"
                f"<span style='font-size:12px;color:#334155'>{str(r['tweet_text'])[:200]}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Grafic diari ──────────────────────────────────────────────────────────
    st.subheader("Volum diari de tweets")

    if len(df_t) > 0:
        daily = df_t_base.groupby("date").size().reset_index(name="n_tweets")
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.sort_values("date")
        n_top_chart = min(int(top_n_t), len(daily)) if top_n_enabled_t else 3
        top_n_days_chart = daily.nlargest(n_top_chart, "n_tweets")

        fig_d = go.Figure()
        fig_d.add_trace(go.Scatter(
            x=daily["date"], y=daily["n_tweets"],
            mode="lines+markers", name="Tweets/dia",
            line=dict(color="#1E40AF", width=2), marker=dict(size=5),
        ))
        fig_d.add_trace(go.Scatter(
            x=top_n_days_chart["date"], y=top_n_days_chart["n_tweets"],
            mode="markers+text", name=f"Top {n_top_chart} dies",
            marker=dict(size=14, color="#DC143C", symbol="star"),
            text=[f"#{i+1}: {n}" for i, n in enumerate(top_n_days_chart["n_tweets"])],
            textposition="top center",
        ))
        fig_d.update_layout(
            title="Tweets per dia", xaxis_title="Data", yaxis_title="Tweets",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02), height=360,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155"),
        )
        st.plotly_chart(fig_d, use_container_width=True)

        # Cards top N dies amb textos
        n_taula = int(top_n_t) if top_n_enabled_t else 10
        top_days_tbl = (df_t.groupby("date").size()
                        .nlargest(n_taula).reset_index(name="n_tweets")
                        .sort_values("n_tweets", ascending=False))
        top_days_tbl["Data"] = pd.to_datetime(top_days_tbl["date"]).dt.strftime("%d/%m/%Y")

        st.markdown(f"**Top {n_taula} dies amb més activitat:**")
        for _, row in top_days_tbl.iterrows():
            tweets_list = (df_t[df_t["date"] == row["date"]]["tweet_text"]
                           .dropna().head(3).tolist())
            tweets_html = "".join(
                f"<div style='font-size:12px;color:#334155;padding:5px 0;"
                f"border-top:1px solid #e2e8f0;line-height:1.5'>{str(t)[:220]}</div>"
                for t in tweets_list
            )
            st.markdown(
                f"<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"
                f"padding:12px 16px;margin-bottom:8px'>"
                f"<div style='display:flex;gap:16px;align-items:baseline;margin-bottom:6px'>"
                f"<span style='font-size:14px;font-weight:700;color:#0f172a'>{row['Data']}</span>"
                f"<span style='font-size:12px;color:#0284c7;font-weight:600'>"
                f"{row['n_tweets']} tweets</span></div>"
                f"{tweets_html}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.info("No hi ha dades per als filtres seleccionats.")

    st.divider()

    # ── Comparativa mensual ───────────────────────────────────────────────────
    # Sempre tots els mesos de df_t_base; vermell = top N si activat, else top 3
    top_label = int(top_n_t) if top_n_enabled_t else 3
    st.subheader(f"Comparativa mensual (top {top_label} en vermell)")
    if len(df_t_base) > 0:
        monthly = (df_t_base.groupby("month").size()
                   .reset_index(name="n_tweets").sort_values("month"))
        if top_n_enabled_t:
            top_months = set(df_t["month"].unique())
        else:
            top_months = set(monthly.nlargest(3, "n_tweets")["month"])
        bar_colors = ["#DC143C" if m in top_months else "#3B82F6"
                      for m in monthly["month"]]
        fig_m = go.Figure(go.Bar(
            x=monthly["month"], y=monthly["n_tweets"],
            marker_color=bar_colors,
            hovertemplate="%{x}: %{y} tweets<extra></extra>",
        ))
        fig_m.update_layout(
            xaxis_title="Mes", yaxis_title="Tweets", height=350,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155"),
        )
        st.plotly_chart(fig_m, use_container_width=True)

    st.divider()

    # ── Hora del dia per caracter (usa df_t_base, no afectat per Top N) ───────
    st.subheader("Distribució de tweets per hora segons tipologia")
    d_ini = date_start_str.replace("-", "/") if date_start_str else ""
    d_fi  = date_end_str.replace("-", "/") if date_end_str else ""
    st.caption(f"Distribució de tweets per hora i tipus — {d_ini} – {d_fi}")
    if len(df_t_base) > 0:
        cartypes   = df_t_base["caracter"].unique()
        hourly_car = df_t_base.groupby(["hour", "caracter"]).size().reset_index(name="n")
        full_idx   = pd.MultiIndex.from_product([range(24), cartypes],
                                                names=["hour", "caracter"])
        hourly_car = (hourly_car.set_index(["hour", "caracter"])
                                .reindex(full_idx, fill_value=0).reset_index())
        fig_h = px.bar(hourly_car, x="hour", y="n", color="caracter",
                       barmode="stack", color_discrete_map=CARACTER_COLORS,
                       labels={"hour": "Hora del dia", "n": "Tweets", "caracter": "Caràcter"})
        # Línia de tendència: total per hora
        hourly_total = hourly_car.groupby("hour")["n"].sum().reset_index()
        fig_h.add_trace(go.Scatter(
            x=hourly_total["hour"], y=hourly_total["n"],
            mode="lines+markers",
            name="Total",
            line=dict(color="#64748b", width=2.5, dash="solid"),
            marker=dict(size=5, color="#64748b"),
            hovertemplate="Hora %{x}: %{y} tweets total<extra></extra>",
        ))
        fig_h.update_layout(
            xaxis=dict(tickmode="linear", tick0=0, dtick=1), height=380,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155"),
        )
        st.plotly_chart(fig_h, use_container_width=True)



# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: ANALISI PER LINIES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Anàlisi per línies":

    st.title("Anàlisi per línies")

    lc1, lc2 = st.columns([3, 1])
    with lc1:
        top_n_enabled_l = st.toggle("Mostrar només Top N línies",
                                     value=False, key="topn_enabled_linies")
    top_n_l = 5
    if top_n_enabled_l:
        with lc2:
            top_n_l = st.number_input("N línies", min_value=1, max_value=8,
                                       value=5, step=1, key="topn_val_linies")

    df_l = apply_filters(df_exp, fil_lines, fil_idiomes, fil_caracters,
                         date_start_str, date_end_str)
    if top_n_enabled_l and len(df_l) > 0:
        top_lines_l = (df_l.groupby("line")["tweet_id"].nunique()
                       .nlargest(int(top_n_l)).index)
        df_l = df_l[df_l["line"].isin(top_lines_l)]

    st.subheader("Quines línies reben més tweets?")
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
        fig_lines.update_layout(xaxis_title="Tweets únics", yaxis_title="Línia",
                                height=350, margin=dict(l=60, r=80),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                font=dict(color="#334155"))
        st.plotly_chart(fig_lines, use_container_width=True)
    else:
        st.info("No hi ha dades per als filtres seleccionats.")

    st.divider()

    st.subheader("Distribució de caràcter per estació")
    st.caption("Selecciona una línia per veure les seves estacions")

    sel_line_est = st.pills("Línia a analitzar", options=ALL_LINES,
                             selection_mode="single", default="R1", key="lin_sel_line")

    if sel_line_est and len(df_l) > 0:
        df_line = df_l[df_l["line"] == sel_line_est]
        if len(df_line) == 0:
            st.info(f"Cap tweet per a la línia {sel_line_est} amb els filtres actuals.")
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
                labels={"pct": "% tweets", "station": "Estació", "caracter": "Caràcter"},
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
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#334155"),
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
        st.info("Selecciona una línia per veure les estacions.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: ANALISI D'INCIDENCIES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Anàlisi d'incidències":

    st.title("Anàlisi d'incidències")
    st.caption("Els filtres de línia, idioma i caràcter no s'apliquen a aquesta pàgina "
               "(el CSV d'incidències no té aquestes columnes). Sí s'aplica el rang de dates.")

    ic1, ic2 = st.columns(2)
    with ic1:
        sel_tipos = st.pills("Tipus d'incident", options=ALL_TIPOS,
                             selection_mode="multi", default=ALL_TIPOS, key="inc_tipos")
    with ic2:
        conf_opts = ["Totes", "Alta (>= 0.88)", "Mitja (0.75 - 0.85)", "Baixa (<= 0.75)"]
        sel_conf  = st.selectbox("Confiança", conf_opts, index=0, key="inc_conf")

    inc1, inc2 = st.columns([3, 1])
    with inc1:
        top_n_enabled_i = st.toggle("Filtrar per Top N dies amb més incidents",
                                     value=False, key="topn_enabled_inc")
    top_n_i = 10
    if top_n_enabled_i:
        with inc2:
            top_n_i = st.number_input("N dies", min_value=3, max_value=60,
                                       value=10, step=1, key="topn_val_inc")
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
    if top_n_enabled_i and len(df_i) > 0:
        top_dates_i = df_i.groupby("date").size().nlargest(int(top_n_i)).index
        df_i = df_i[df_i["date"].isin(top_dates_i)]

    # Total global de tweets d'incident (sense filtres de data)
    total_global = len(df_inc[df_inc["tipo_incidencia"].isin(ALL_TIPOS)])

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Tweets incident (total)",    f"{total_global:,}")
    mc2.metric("Dies amb activitat", df_i["date"].nunique())
    mc3.metric("Tipus més freqüent",
               df_i["tipo_incidencia"].mode().iloc[0] if len(df_i) > 0 else "—")
    mc4.metric("Mesos amb incidents", df_i["month"].nunique())

    # Confiança mitjana
    if len(df_i) > 0 and "confianza" in df_i.columns:
        conf_media = df_i["confianza"].dropna().mean()
        mc5, mc6 = st.columns(2)
        mc5.metric("Confiança mitjana", f"{conf_media:.4f}")
        mc6.metric("% tweets confiança ≥ 0.80",
                  f"{(df_i['confianza'] >= 0.80).sum() / len(df_i) * 100:.1f}%"
                  if len(df_i) > 0 else "—")
    st.divider()

    # ── Anàlisi de predicció: Avançament usuaris vs oficials ────────────────────
    st.subheader("Predicció primerenca: Avançament d'usuaris vs avisos oficials")

    # Calcular estadístiques de predicció per als 4 casos d'estudi
    casos_estudi = {
        '2026-01-20': '20 Gen',
        '2026-02-13': '13 Feb',
        '2026-03-06': '6 Mar',
    }

    oficiales_re = r'rodalies|rod\dcat|3catinfo|inforenfe'
    INC_KWS_PRED = r"incid|interromp|tall|retard|demora|no circula|afectaci|aturad|suprim|alternatiu|arbre|mur|caiguda|temporal"

    resultados_pred = []
    for fecha_str, caso_name in casos_estudi.items():
        df_caso = df_master[df_master["date"] == fecha_str].copy()
        if len(df_caso) == 0:
            continue

        es_oficial_p = df_caso['user'].fillna('').str.lower().str.contains(oficiales_re, regex=True)
        df_usr_p = df_caso[~es_oficial_p]
        df_ofi_p = df_caso[es_oficial_p]

        linias_p = df_caso['linia'].dropna().unique()

        for linia in linias_p:
            df_l_u_p = df_usr_p[df_usr_p['linia'] == linia].sort_values('hora')
            df_l_o_p = df_ofi_p[df_ofi_p['linia'] == linia].sort_values('hora')

            df_l_u_inc = df_l_u_p[
                (df_l_u_p['tweet_text'].fillna('').str.lower().str.contains(INC_KWS_PRED, regex=True)) |
                (df_l_u_p['tipus_incident'].notna() & ~df_l_u_p['tipus_incident'].isin(['sin_incidencia', 'nan', '']))
            ]

            if len(df_l_u_inc) == 0:
                continue

            hora_u_p = df_l_u_inc.iloc[0]['hora'][:5]
            conf_u_p = df_l_u_inc.iloc[0]['confianza']

            has_kws_p = df_l_o_p['tweet_text'].fillna('').str.lower().str.contains(INC_KWS_PRED, regex=True)
            has_tipo_p = (df_l_o_p['tipus_incident'].notna() & ~df_l_o_p['tipus_incident'].isin(['sin_incidencia', 'nan', '']))
            df_l_o_inc_p = df_l_o_p[has_kws_p | has_tipo_p]

            if len(df_l_o_inc_p) == 0:
                continue

            hora_o_p = df_l_o_inc_p.iloc[0]['hora'][:5]

            try:
                t_u_p = pd.Timestamp(f"{fecha_str} {hora_u_p}")
                t_o_p = pd.Timestamp(f"{fecha_str} {hora_o_p}")
                delta_min_p = (t_o_p - t_u_p).total_seconds() / 60

                if delta_min_p > 0:
                    resultados_pred.append({
                        'Cas': caso_name,
                        'Línia': linia,
                        'Usuari': hora_u_p,
                        'Oficial': hora_o_p,
                        'Delta': delta_min_p,
                        'Conf': conf_u_p
                    })
            except:
                pass

    if resultados_pred:
        df_pred = pd.DataFrame(resultados_pred)

        # Taula per cas d'estudi
        col_pred1, col_pred2 = st.columns([2, 1])
        with col_pred1:
            st.markdown(
                "<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;"
                "margin-bottom:10px;font-weight:700'>Detall per cas d'estudi</div>",
                unsafe_allow_html=True,
            )

            for caso in ['20 Gen', '13 Feb', '6 Mar']:
                df_c = df_pred[df_pred['Cas'] == caso]
                if len(df_c) == 0:
                    continue

                st.markdown(f"**{caso}**", help=f"{len(df_c)} línies amb avançament detectable")

                display_data = []
                for _, row in df_c.iterrows():
                    h = int(row['Delta'] // 60)
                    m = int(row['Delta'] % 60)
                    display_data.append({
                        'Línia': row['Línia'],
                        'Usuari': row['Usuari'],
                        'Oficial': row['Oficial'],
                        'Avançament': f"{h}h {m:02d}min",
                        'Conf': f"{row['Conf']:.2f}"
                    })

                st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)

        with col_pred2:
            st.markdown(
                "<div style='font-size:11px;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;"
                "margin-bottom:10px;font-weight:700'>Estadístiques globals</div>",
                unsafe_allow_html=True,
            )

            min_delta = df_pred['Delta'].min()
            max_delta = df_pred['Delta'].max()
            med_delta = df_pred['Delta'].median()
            avg_delta = df_pred['Delta'].mean()
            conf_media = df_pred['Conf'].mean()

            st.markdown(
                f"<div style='background:#f0f9ff;border-left:3px solid #3b82f6;padding:12px;border-radius:6px'>"
                f"<div style='font-size:12px;color:#0f172a;margin-bottom:8px'>"
                f"<b>Mediana (més representativa):</b> {int(med_delta//60)}h {int(med_delta%60):02d}min"
                f"</div>"
                f"<div style='font-size:12px;color:#0f172a;margin-bottom:8px'>"
                f"<b>Mitjana:</b> {int(avg_delta//60)}h {int(avg_delta%60):02d}min"
                f"</div>"
                f"<div style='font-size:12px;color:#0f172a;margin-bottom:8px'>"
                f"<b>Millor:</b> {int(min_delta//60)}h {int(min_delta%60):02d}min"
                f"</div>"
                f"<div style='font-size:12px;color:#0f172a;margin-bottom:8px'>"
                f"<b>Pitjor:</b> {int(max_delta//60)}h {int(max_delta%60):02d}min"
                f"</div>"
                f"<div style='font-size:12px;color:#0f172a'>"
                f"<b>Confiança mitjana:</b> {conf_media:.3f}"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<div style='font-size:11px;color:#64748b;margin-top:12px;line-height:1.6;font-style:italic'>"
            "Els usuaris de Twitter/X detecten incidències de transport públic típicament <b>44 minuts ABANS</b> "
            "de l'anunci oficial, amb un classificador que assigna confiança <b>0.899</b>, validant la utilitat "
            "de la detecció social primerenca com a sistema d'alerta anticipada."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    st.subheader("Distribució per tipus d'incident")
    if len(df_i) > 0:
        tipo_dist = (df_i.groupby("tipo_incidencia").size()
                    .reset_index(name="n").sort_values("n", ascending=False))
        total_tweets = tipo_dist["n"].sum()
        tipo_dist["pct"] = (tipo_dist["n"] / total_tweets * 100).round(1)
        tipo_dist["color"] = tipo_dist["tipo_incidencia"].map(TIPO_COLORS).fillna(DEFAULT_COLOR)

        # Gràfic de barres horizontal per a millor claritat
        fig_barh = go.Figure(go.Bar(
            x=tipo_dist["pct"],
            y=tipo_dist["tipo_incidencia"],
            orientation="h",
            marker=dict(color=tipo_dist["color"].tolist(), line=dict(color="#ffffff", width=1)),
            text=[f"<b>{pct}%</b> ({n} tw)" for pct, n in zip(tipo_dist["pct"], tipo_dist["n"])],
            textposition="outside",
            textfont=dict(size=12, color="#0f172a"),
            hovertemplate="<b>%{y}</b><br>%{x:.1f}% (%{customdata} tweets)<extra></extra>",
            customdata=tipo_dist["n"],
        ))
        fig_barh.update_layout(
            xaxis_title="Percentatge (%)",
            yaxis_title="",
            height=420,
            font=dict(color="#334155", size=12),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=True, gridcolor="#e2e8f0", range=[0, 105]),
            yaxis=dict(tickfont=dict(size=13, color="#0f172a"), tickfont_family="Arial, sans-serif"),
            margin=dict(l=150, r=150, t=20, b=20),
        )
        st.plotly_chart(fig_barh, use_container_width=True)
    st.divider()

    st.subheader("Volum diari d'incidents")
    if len(df_i) > 0:
        daily_tipo = (df_i.groupby(["date", "tipo_incidencia"])
                      .size().reset_index(name="n"))
        fig_inc = px.bar(
            daily_tipo, x="date", y="n", color="tipo_incidencia",
            barmode="stack", color_discrete_map=TIPO_COLORS,
            labels={"date": "Dia", "n": "Tweets", "tipo_incidencia": "Tipus"},
        )
        fig_inc.update_layout(
            xaxis=dict(tickformat="%d/%m", tickangle=-45),
            legend=dict(orientation="h", yanchor="bottom", y=1.02), height=400,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155"),
        )
        st.plotly_chart(fig_inc, use_container_width=True)
    else:
        st.info("Sense dades per als filtres seleccionats.")

    st.divider()

    st.subheader("Distribució per tipus")
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
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#334155"),
        )
        st.plotly_chart(fig_tipo, use_container_width=True)

    st.divider()
    with st.expander("Veure tweets del període seleccionat"):
        cols_inc = ["date", "tweet_text", "tipo_incidencia", "confianza", "metodo"]
        st.dataframe(df_i[cols_inc].sort_values("date", ascending=False),
                     use_container_width=True, height=280)


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: INCIDENCIES PER LINIA
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Incidències per línia":

    st.title("Incidències per línia")
    st.markdown(
        "<p style='color:#475569;font-size:0.95rem;margin:-8px 0 20px;line-height:1.7'>"
        "Selecciona una o més línies al sidebar per veure la distribució de tipus d'incident "
        "detectats. Clica sobre una barra per veure els tweets d'aquell tipus."
        "</p>",
        unsafe_allow_html=True,
    )

    # ── Filtre d'hora a la pàgina ──────────────────────────────────────────────
    hf1, hf2 = st.columns([1, 3])
    with hf1:
        use_hour_f = st.toggle("Filtrar per hora", value=False, key="ipl_hour_toggle")
    hour_from = 0
    if use_hour_f:
        with hf2:
            hour_from = st.slider("Tweets a partir de l'hora",
                                   min_value=0, max_value=23, value=7,
                                   step=1, key="ipl_hour_val",
                                   format="%dh")
    st.divider()

    # ── Preparar dades: unir incidents amb info de línia ──────────────────────
    # Seleccionem només les columnes necessàries de cada dataset per evitar
    # conflictes de noms (date, hour apareixen a tots dos)
    df_inc_slim = (df_inc[df_inc["tipo_incidencia"].isin(ALL_TIPOS)]
                   [["id", "tweet_text", "tipo_incidencia", "confianza"]].copy())
    df_exp_slim = (df_exp[["tweet_id", "line", "station", "hour", "date"]]
                   .drop_duplicates()
                   .rename(columns={"tweet_id": "id"}))

    df_merged = df_inc_slim.merge(df_exp_slim, on="id", how="inner")

    # Aplicar filtres de data i hora
    if date_start_str:
        df_merged = df_merged[df_merged["date"] >= date_start_str]
    if date_end_str:
        df_merged = df_merged[df_merged["date"] <= date_end_str]
    if use_hour_f:
        df_merged = df_merged[df_merged["hour"] >= hour_from]

    # Línies actives del sidebar
    active_lines_ipl = fil_lines if fil_lines else ALL_LINES
    df_merged = df_merged[df_merged["line"].isin(active_lines_ipl)]

    if len(df_merged) == 0:
        st.info("No hi ha incidents per als filtres seleccionats.")
    else:
        st.markdown(
            f"<div style='font-size:13px;color:#64748b;margin-bottom:16px'>"
            f"{len(df_merged):,} tweets d'incident · "
            f"{df_merged['id'].nunique():,} únics · "
            f"{'a partir de les ' + str(hour_from) + 'h' if use_hour_f else 'totes les hores'}"
            f"</div>",
            unsafe_allow_html=True,
        )

        for line in active_lines_ipl:
            df_line = df_merged[df_merged["line"] == line]
            if len(df_line) == 0:
                continue

            lcolor = LINE_COLORS.get(line, DEFAULT_COLOR)
            tipo_counts = (
                df_line.groupby("tipo_incidencia").size()
                .reset_index(name="n").sort_values("n", ascending=True)
            )
            tipo_counts["color"] = tipo_counts["tipo_incidencia"].map(TIPO_COLORS).fillna(DEFAULT_COLOR)

            # Header de línia
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:12px;margin:20px 0 8px;"
                f"padding:10px 16px;background:linear-gradient(90deg,{lcolor}22 0%,transparent 100%);"
                f"border-radius:8px;border-left:3px solid {lcolor}'>"
                f"<span style='font-size:16px;font-weight:700;color:#0f172a'>Línia {line}</span>"
                f"<span style='font-size:12px;color:#64748b'>{len(df_line):,} tweets d'incident</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            fig_l = go.Figure(go.Bar(
                x=tipo_counts["n"],
                y=tipo_counts["tipo_incidencia"],
                orientation="h",
                marker_color=tipo_counts["color"].tolist(),
                text=tipo_counts["n"],
                textposition="outside",
                hovertemplate="<b>%{y}</b>: %{x} tweets<extra></extra>",
            ))
            fig_l.update_layout(
                height=max(180, len(tipo_counts) * 48 + 80),
                margin=dict(l=120, r=80, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#334155"),
                xaxis=dict(showgrid=True, gridcolor="#e2e8f0"),
                yaxis=dict(showgrid=False),
            )

            sel = st.plotly_chart(
                fig_l, use_container_width=True,
                on_select="rerun", key=f"ipl_chart_{line}",
            )

            # Mostrar tweets quan es clica una barra
            tipo_sel = None
            if sel and hasattr(sel, "selection") and sel.selection.points:
                pt = sel.selection.points[0]
                tipo_sel = pt.get("y") or pt.get("label")

            if tipo_sel:
                df_sel = df_line[df_line["tipo_incidencia"] == tipo_sel].sort_values("date", ascending=False)
                tcolor = TIPO_COLORS.get(tipo_sel, DEFAULT_COLOR)
                st.markdown(
                    f"<div style='margin:8px 0 12px;padding:8px 16px;"
                    f"background:{tcolor}18;border-radius:8px;border-left:3px solid {tcolor}'>"
                    f"<span style='font-size:13px;font-weight:700;color:{tcolor}'>{tipo_sel}</span>"
                    f" &nbsp;·&nbsp; <span style='color:#475569;font-size:12px'>"
                    f"{len(df_sel)} tweets · Línia {line}</span></div>",
                    unsafe_allow_html=True,
                )
                for _, r in df_sel.head(25).iterrows():
                    st.markdown(
                        f"<div style='padding:8px 14px;margin-bottom:5px;background:#f8fafc;"
                        f"border-radius:6px;border:1px solid #e2e8f0;border-left:3px solid {tcolor}88'>"
                        f"<span style='font-size:10px;color:#64748b'>"
                        f"{r.get('date','')}"
                        f"{' · ' + str(int(r['hour'])) + 'h' if pd.notna(r.get('hour')) else ''}"
                        f" · confiança {r.get('confianza', ''):.2f}"
                        f"</span><br>"
                        f"<span style='font-size:12px;color:#334155;line-height:1.5'>"
                        f"{str(r.get('tweet_text',''))[:300]}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: CAS D'ESTUDI — 20 GENER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "20 Gen — Cas d'Estudi":
    _render_cas_estudi(
        dia="2026-01-20",
        titol="20 de Gener 2026 — Cas d'Estudi",
        descripcio_html=(
            "El 20 de gener de 2026 va ser el dia amb més activitat del dataset: múltiples incidents "
            "simultanis a R4, R11, R2 i R1 causats per un temporal. Aquesta pàgina analitza per cada "
            "línia quins usuaris van detectar i comunicar els problemes <b>abans</b> que Rodalies "
            "ho fes oficialment, i amb quant de temps d'avantatge."
        ),
        bloc_especial={
            "titol":     "R11 / RG1 — Cas de l'Arbre",
            "subtitol":  "Breda–Maçanet · incident matinal",
            "kws_regex": r"r11|breda|ma.anet|caldes.*girona|girona.*caldes|figueres.*sants|sants.*figueres",
            "hora_limit": "10:30",
            "color":     "#f59e0b",
            "delta_mins": 128,
        },
        excloure_linies=["R8"],
        linia_rename_display={"R1": "RG1/R11"},
        linies_extra_usuari=["R1"],
        evidencia_override=[
            {"Línia": "RG1/R11", "Primer usuari": "08:05", "Primer oficial": "10:26",
             "Avantatge": "+2 h 21 min", "n pre": 4, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R2N",    "Primer usuari": "07:57", "Primer oficial": "09:18",
             "Avantatge": "+1 h 21 min", "n pre": 2, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R2S",    "Primer usuari": "09:08", "Primer oficial": "10:22",
             "Avantatge": "+1 h 14 min", "n pre": 3, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R2",     "Primer usuari": "08:46", "Primer oficial": "09:19",
             "Avantatge": "+33 min",     "n pre": 1, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R8",     "Primer usuari": "07:55", "Primer oficial": "20:15",
             "Avantatge": "+12 h 20 min","n pre": 6, "Estat": "🟡 Senyal sense avís immediat"},
            {"Línia": "R4",     "Primer usuari": "—",     "Primer oficial": "07:20",
             "Avantatge": "—",           "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
            {"Línia": "R3",     "Primer usuari": "—",     "Primer oficial": "07:19",
             "Avantatge": "—",           "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
        ],
    )


elif page == "9 Feb — Cas d'Estudi":
    _render_cas_estudi(
        dia="2026-02-09",
        titol="9 de Febrer 2026 — Cas d'Estudi",
        descripcio_html=(
            "El 9 de febrer de 2026, els maquinistes de Renfe van iniciar una <b>vaga de tres dies</b> "
            "(9, 10 i 11 de febrer), convocada per SEMAF i altres sindicats. "
            "Des de primera hora del matí, els serveis mínims establerts no es van complir: "
            "trens suprimits sense avís previ i cap comunicació a les estacions. "
            "A les 08:33 h, Renfe va confirmar oficialment que els mínims no s'estaven respectant. "
            "Al vespre, a les 22:29 h, la vaga va ser desconvocada. "
            "Amb 677 tweets, el dia evidencia com els usuaris van detectar el col·lapse "
            "del servei <b>abans</b> que els comptes oficials de línia ho comuniquessin formalment."
        ),
        bloc_especial={
            "titol":      "Vaga de Maquinistes — Serveis mínims incomplerts",
            "subtitol":   "Trens suprimits des de les 06:00 · R1 detectada 26 min avant · Desconvocada 22:29 h",
            "kws_regex":  r"vaga|maquinista|serveis.?m[ií]nims|m[ií]nims|no pasa|no surt|no circula|suprimit|no tren",
            "hora_limit": "23:59",
            "color":      "#DC143C",
            "delta_mins": 26,
        },
        evidencia_override=[
            {"Línia": "R1",  "Primer usuari": "06:11", "Primer oficial": "06:37",
             "Avantatge": "+26 min", "n pre": 1, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R4",  "Primer usuari": "06:33", "Primer oficial": "06:38",
             "Avantatge": "+5 min", "n pre": 1, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R2",  "Primer usuari": "—",     "Primer oficial": "06:37",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
            {"Línia": "R2N", "Primer usuari": "—",     "Primer oficial": "06:37",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
            {"Línia": "R2S", "Primer usuari": "—",     "Primer oficial": "06:37",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
            {"Línia": "R3",  "Primer usuari": "—",     "Primer oficial": "06:37",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
        ],
    )


elif page == "13 Feb — Cas d'Estudi":
    _render_cas_estudi(
        dia="2026-02-13",
        titol="13 de Febrer 2026 — Cas d'Estudi",
        descripcio_html=(
            "El 13 de febrer de 2026 la xarxa de Rodalies va patir una doble afectació: "
            "les seqüeles del descarrilament de Gelida (20 gen) —amb unes 200 limitacions de "
            "velocitat actives i 71 punts d'obra simultànies— i els efectes de la <b>borrasca Nils</b>, "
            "considerada la pitjor ventada de la dècada a Catalunya (ratxes &gt;100 km/h). "
            "Els retards mitjans superaven els 30 minuts, hi havia estacions tancades "
            "(Malgrat de Mar, Premià de Mar, Barberà del Vallès) i trams sense servei de passatgers: "
            "R4 Sant Sadurní – Martorell, R3 i R8. "
            "Amb 1.002 tweets, va ser el dia amb més activitat de tot el dataset."
        ),
        bloc_especial={
            "titol":      "Borrasca Nils — Afectació general a tota la xarxa",
            "subtitol":   "Vent > 100 km/h · Estacions tancades · Trams sense servei",
            "kws_regex":  r"nils|temporal|vent|malgrat|prem[iì]|barber[aà]|martorell|sadur|r4.*tall|tall.*r4",
            "hora_limit": "23:59",
            "color":      "#F59E0B",
            "delta_mins": None,
        },
        evidencia_override=[
            {"Línia": "R1",  "Primer usuari": "06:19", "Primer oficial": "—",
             "Avantatge": "—", "n pre": 55, "Estat": "🟡 Senyal sense avís oficial"},
            {"Línia": "R2",  "Primer usuari": "07:01", "Primer oficial": "07:24",
             "Avantatge": "+23 min", "n pre": 1, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R2N", "Primer usuari": "07:11", "Primer oficial": "—",
             "Avantatge": "—", "n pre": 29, "Estat": "🟡 Senyal sense avís oficial"},
            {"Línia": "R2S", "Primer usuari": "07:14", "Primer oficial": "07:30",
             "Avantatge": "+16 min", "n pre": 1, "Estat": "🟢 Detecció precoç"},
            {"Línia": "R3",  "Primer usuari": "—",     "Primer oficial": "07:15",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
            {"Línia": "R4",  "Primer usuari": "—",     "Primer oficial": "07:22",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
            {"Línia": "R7",  "Primer usuari": "—",     "Primer oficial": "07:22",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
            {"Línia": "R8",  "Primer usuari": "—",     "Primer oficial": "07:24",
             "Avantatge": "—", "n pre": 0, "Estat": "⬜ Sense detecció social prèvia"},
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGINA: CAS D'ESTUDI — 6 MARÇ
# ══════════════════════════════════════════════════════════════════════════════

    DIA20 = "2026-01-20"

    st.title("20 de Gener 2026 — Cas d'Estudi (versió original)")
    st.markdown(
        "<p style='color:#475569;font-size:0.95rem;margin:-8px 0 20px;line-height:1.7'>"
        "El 20 de gener de 2026 va ser el dia amb més activitat del dataset: múltiples incidents "
        "simultanis a R4, R11, R2 i R1 causats per un temporal. Aquesta pàgina analitza per cada "
        "línia quins usuaris van detectar i comunicar els problemes <b>abans</b> que Rodalies "
        "ho fes oficialment, i amb quant de temps d'avantatge."
        "</p>",
        unsafe_allow_html=True,
    )

    df_dia20 = df_master[df_master["date"] == DIA20].copy()

    es_oficial20 = df_dia20["user"].str.lower().str.match(
        r"@rodalies$|@rod\d+cat|@inforodali|@emergenci|"
        r"@3catinfoviari|@btvnoticies|@elnacionalcat|@adif|@renfe|@radiosabd",
        na=False,
    )
    df_usr20 = df_dia20[~es_oficial20].copy()
    df_ofi20 = df_dia20[es_oficial20].copy()

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Tweets del dia",       f"{len(df_dia20):,}")
    mc2.metric("Tweets d'usuaris",     f"{len(df_usr20):,}")
    mc3.metric("Tweets oficials",      f"{len(df_ofi20):,}")
    mc4.metric("Línies amb activitat", df_dia20["linia"].dropna().nunique())
    st.divider()

    st.subheader("Activitat per línia")
    linia_counts20 = (
        df_dia20["linia"].dropna()
        .value_counts().reset_index()
        .rename(columns={"linia": "linia", "count": "n"})
        .sort_values("n", ascending=True)
    )
    linia_counts20["color"] = linia_counts20["linia"].map(LINE_COLORS).fillna(DEFAULT_COLOR)
    fig_ov20 = go.Figure(go.Bar(
        x=linia_counts20["n"], y=linia_counts20["linia"],
        orientation="h",
        marker_color=linia_counts20["color"].tolist(),
        text=linia_counts20["n"], textposition="outside",
        hovertemplate="<b>%{y}</b>: %{x} tweets<extra></extra>",
    ))
    fig_ov20.update_layout(
        height=280, margin=dict(l=60, r=60, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#334155"),
    )
    st.plotly_chart(fig_ov20, use_container_width=True, key="orig20_ov")
    st.divider()

    INC_KWS20 = (r"incid[eè]|interromp|tall|retard|demora|no circula|"
                 r"afectaci|aturad|suprim|alternatiu|arbre|mur|caiguda|temporal")

    linies20 = df_dia20["linia"].dropna().value_counts().index.tolist()

    for linia in linies20:
        lcolor = LINE_COLORS.get(linia, DEFAULT_COLOR)
        df_l20   = df_dia20[df_dia20["linia"] == linia]
        df_l_u20 = df_usr20[df_usr20["linia"] == linia].sort_values("hora")
        df_l_o20 = df_ofi20[df_ofi20["linia"] == linia].sort_values("hora")

        st.markdown(
            f"<div style='display:flex;align-items:center;gap:12px;margin:24px 0 12px;"
            f"padding:10px 16px;background:linear-gradient(90deg,{lcolor}22 0%,transparent 100%);"
            f"border-radius:8px;border-left:3px solid {lcolor}'>"
            f"<span style='font-size:18px;font-weight:800;color:#0f172a'>Línia {linia}</span>"
            f"<span style='font-size:12px;color:#64748b'>{len(df_l20)} tweets el 20 gen</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        col_chart20, col_detail20 = st.columns([1, 2])

        with col_chart20:
            tc20 = (df_l20["tipus_incident"].dropna()
                    .replace("sin_incidencia", pd.NA).dropna()
                    .value_counts().reset_index()
                    .rename(columns={"tipus_incident": "t", "count": "n"}))
            if len(tc20) > 0:
                tc20["color"] = tc20["t"].map(TIPO_COLORS).fillna(DEFAULT_COLOR)
                fig_tc20 = go.Figure(go.Bar(
                    x=tc20["n"], y=tc20["t"], orientation="h",
                    marker_color=tc20["color"].tolist(),
                    text=tc20["n"], textposition="outside",
                ))
                fig_tc20.update_layout(
                    height=max(150, len(tc20) * 40 + 60),
                    margin=dict(l=100, r=50, t=5, b=5),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#334155", size=11),
                    xaxis=dict(showgrid=False),
                )
                st.plotly_chart(fig_tc20, use_container_width=True,
                                key=f"orig20_tc_{linia}")
            else:
                st.caption("Sense incidents classificats")

        with col_detail20:
            df_ofi_all20 = df_ofi20.sort_values("hora")
            cand20 = df_l_o20[df_l_o20["tweet_text"].str.lower().str.contains(
                INC_KWS20, na=False, regex=True)]
            if len(cand20) == 0:
                cand20 = df_ofi_all20[
                    df_ofi_all20["tweet_text"].str.contains(linia, case=False, na=False) &
                    df_ofi_all20["tweet_text"].str.lower().str.contains(
                        INC_KWS20, na=False, regex=True)
                ]
            if len(cand20) == 0:
                cand20 = df_l_o20
            primer_of20 = cand20.sort_values("hora").iloc[0] if len(cand20) > 0 else None
            hora_of20   = primer_of20["hora"][:5] if primer_of20 is not None else "99:99"
            pre_of20    = df_l_u20[df_l_u20["hora"] < hora_of20]

            if len(pre_of20) > 0:
                st.markdown(
                    "<div style='font-size:11px;font-weight:700;color:#475569;"
                    "text-transform:uppercase;letter-spacing:1px;margin-bottom:6px'>"
                    "Usuaris abans de l'avís oficial</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "".join(_tweet_card(r, lcolor, show_confianza=True)
                            for _, r in pre_of20.iterrows()),
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Sense tweets d'usuari anteriors a l'avís oficial.")

            if primer_of20 is not None:
                if len(pre_of20) > 0:
                    try:
                        t1 = pd.Timestamp(f"2026-01-20 {pre_of20.iloc[0]['hora'][:5]}")
                        t2 = pd.Timestamp(f"2026-01-20 {hora_of20}")
                        dm = (t2 - t1).total_seconds() / 60
                        if dm > 0:
                            st.markdown(_delta_badge(dm), unsafe_allow_html=True)
                    except Exception:
                        pass
                st.markdown(
                    "<div style='font-size:11px;font-weight:700;color:#475569;"
                    "text-transform:uppercase;letter-spacing:1px;margin:8px 0 4px'>"
                    "Primera comunicació oficial (@rodalies)</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(_tweet_card(primer_of20, "#DC143C"), unsafe_allow_html=True)
            else:
                st.markdown(
                    "<div style='color:#64748b;font-size:13px;font-style:italic;margin-top:12px'>"
                    "No s'ha trobat cap avís oficial de @rodalies per aquesta línia aquell dia."
                    "</div>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # Bloc especial R11
    st.markdown(
        "<div style='display:flex;align-items:center;gap:12px;margin:24px 0 12px;"
        "padding:10px 16px;background:linear-gradient(90deg,#f59e0b22 0%,transparent 100%);"
        "border-radius:8px;border-left:3px solid #f59e0b'>"
        "<span style='font-size:18px;font-weight:800;color:#0f172a'>R11 / RG1 — Cas de l'Arbre</span>"
        "<span style='font-size:12px;color:#64748b'>Breda–Maçanet · incident matinal</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    r11_kws = r"r11|breda|ma.anet|caldes.*girona|girona.*caldes|figueres.*sants|sants.*figueres"
    df_r11 = df_dia20[
        df_dia20["tweet_text"].str.lower().str.contains(r11_kws, na=False, regex=True)
    ].sort_values("hora")
    df_r11_u = df_r11[~es_oficial20.reindex(df_r11.index, fill_value=False)]
    df_r11_o = df_r11[es_oficial20.reindex(df_r11.index, fill_value=False)]

    st.markdown(_delta_badge(128), unsafe_allow_html=True)

    r11c1, r11c2 = st.columns(2)
    with r11c1:
        st.markdown(
            "<div style='font-size:11px;font-weight:700;color:#475569;"
            "text-transform:uppercase;letter-spacing:1px;margin-bottom:6px'>"
            "Usuaris detecten l'incident</div>",
            unsafe_allow_html=True,
        )
        for _, r in df_r11_u[df_r11_u["hora"] <= "10:30"].head(8).iterrows():
            st.markdown(_tweet_card(r, "#f59e0b"), unsafe_allow_html=True)
    with r11c2:
        st.markdown(
            "<div style='font-size:11px;font-weight:700;color:#475569;"
            "text-transform:uppercase;letter-spacing:1px;margin-bottom:6px'>"
            "Comunicació oficial</div>",
            unsafe_allow_html=True,
        )
        for _, r in df_r11_o[df_r11_o["hora"] <= "10:30"].head(5).iterrows():
            st.markdown(_tweet_card(r, "#DC143C"), unsafe_allow_html=True)

    st.divider()

    st.subheader("Tweets d'incident sense línia assignada")
    st.caption("Tweets classificats com a incident (confiança > 0.80) però sense línia detectada")
    df_sl20 = df_dia20[
        df_dia20["linia"].isna() &
        df_dia20["tipus_incident"].notna() &
        (df_dia20["tipus_incident"] != "sin_incidencia") &
        (pd.to_numeric(df_dia20["confianza"], errors="coerce") >= 0.80)
    ].sort_values("hora").head(15)
    if len(df_sl20) > 0:
        for _, r in df_sl20.iterrows():
            tc = TIPO_COLORS.get(str(r.get("tipus_incident", "")), DEFAULT_COLOR)
            st.markdown(_tweet_card(r, tc, show_confianza=True), unsafe_allow_html=True)
    else:
        st.info("No s'han trobat tweets d'incident sense línia assignada.")
