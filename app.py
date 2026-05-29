"""
TFG — Rodalies de Catalunya: Detecció d'incidències via Twitter
App de visualització amb Streamlit
"""

import os
import datetime
from io import StringIO
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
import json

# Data minima de les dades (exclou anys anteriors amb molt pocs tweets)
DATA_START = "2025-01-01"

# ── Configuració ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Rodalies TFG",
    layout="wide",
)

# ── Colors oficials Rodalies de Catalunya ─────────────────────────────────────
LINE_COLORS = {
    "R1":  "#87CEEB",
    "R2":  "#4CAF50",
    "R2N": "#90EE90",
    "R2S": "#006400",
    "R3":  "#DC143C",
    "R4":  "#00008B",
    "R7":  "#8B008B",
    "R8":  "#FF69B4",
}
CARACTER_COLORS = {
    "informatiu": "#3B82F6",
    "queixa":     "#DC143C",
    "mixt":       "#F59E0B",
}
DEFAULT_COLOR = "#6B7280"

PATHS = {
    "csv":     r"C:\MARINA\Universitat\TFG - Visualització\Fonts\classificacio_estacions_ubicacions.csv",
    "json":    r"C:\MARINA\Universitat\TFG - Visualització\Fonts\stations_info.json",
    "csv_inc": r"C:\MARINA\Universitat\TFG - Visualització\Fonts\tweets_incidencias_final_juny.csv",
}

TIPO_COLORS = {
    "demora":         "#F59E0B",
    "averia":         "#DC143C",
    "obras":          "#6366F1",
    "parada":         "#10B981",
    "arrollamiento":  "#7C3AED",
    "huelga":         "#EC4899",
    "sin_incidencia": "#9CA3AF",
}
ALL_TIPOS = ["demora", "averia", "obras", "parada", "arrollamiento", "huelga"]

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
    return lookup, raw


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
    # Data com a string "YYYY-MM-DD" per sobreviure la serialitzacio JSON
    df["date"]  = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["month"] = df["timestamp"].dt.to_period("M").astype(str)
    df["hour"]  = df["timestamp"].dt.hour
    df["lines_list"]    = df["lines_list"].fillna("")
    df["stations_list"] = df["stations_list"].fillna("")
    df["caracter"]      = df["caracter"].fillna("indeterminat")

    # Filtrar dates anteriors al inici significatiu de les dades
    df = df[df["date"] >= DATA_START].copy()
    return df


@st.cache_data
def build_expanded(df_json, lookup_json, file_mtime):
    """Una fila per cada (tweet x estacio mencionada)."""
    lookup = json.loads(lookup_json)
    # convert_dates=False evita que pandas converteixi strings de data a Timestamp
    df = pd.read_json(StringIO(df_json), convert_dates=False)
    rows   = []
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
                    "date":       str(row["date"]),   # sempre string
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
    """Carrega el CSV d'incidencies (sense capçalera). _file_mtime_inc = cache key."""
    cols = ["id", "timestamp", "tweet_text", "tipo_incidencia",
            "confianza", "es_incidencia", "metodo"]
    df_i = pd.read_csv(PATHS["csv_inc"], encoding="utf-8",
                       low_memory=False, header=0, names=cols)
    df_i["timestamp"] = pd.to_datetime(df_i["timestamp"], errors="coerce")
    df_i["date"]      = df_i["timestamp"].dt.strftime("%Y-%m-%d")
    df_i["month"]     = df_i["timestamp"].dt.to_period("M").astype(str)
    df_i["hour"]      = df_i["timestamp"].dt.hour
    df_i["confianza"] = pd.to_numeric(df_i["confianza"], errors="coerce")

    # Deduplicar: el CSV conté ~12k files duplicades (dos lots de processament).
    # Per als 930 casos amb valors DIFERENT, preferim llm_confirm > rules > cache > rules_duda_no_ollama.
    metodo_rank = {"llm_confirm": 0, "rules": 1, "cache": 2, "rules_duda_no_ollama": 3, "empty": 4}
    df_i["_rank"] = df_i["metodo"].map(metodo_rank).fillna(9)
    df_i = (df_i.sort_values("_rank")
                .drop_duplicates(subset=["id"], keep="first")
                .drop(columns="_rank"))

    return df_i[df_i["date"] >= DATA_START].reset_index(drop=True)


# ── Carrega inicial ───────────────────────────────────────────────────────────
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
ALL_DATES     = sorted(df["date"].dropna().unique())   # strings "YYYY-MM-DD"
ALL_MONTHS    = sorted(df["month"].dropna().unique())
INC_MONTHS    = sorted(df_inc["month"].dropna().unique())

# Dates com a datetime.date per als widgets de calendari
ALL_DATES_DT = [datetime.date.fromisoformat(d) for d in ALL_DATES if d and d != "NaT"]

# ══════════════════════════════════════════════════════════════════════════════
# CAPCALERA
# ══════════════════════════════════════════════════════════════════════════════
st.title("Rodalies de Catalunya — Deteccio d'incidencies via Twitter")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tweets al dataset", len(df))
c2.metric("Tweets amb estacio",
          int((df["n_stations"] > 0).sum()) if "n_stations" in df.columns
          else df_exp["tweet_id"].nunique())
c3.metric("Estacions detectades", df_exp["station"].nunique() if len(df_exp) else 0)
c4.metric("Dies amb dades", df["date"].nunique())

# ── 4 TABS ────────────────────────────────────────────────────────────────────
tab_mapa, tab_temporal, tab_linies, tab_inc = st.tabs([
    "Mapa d'estacions",
    "Analisi temporal",
    "Analisi per linies",
    "Analisi d'incidencies",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — MAPA
# ══════════════════════════════════════════════════════════════════════════════
with tab_mapa:

    # ── Filtres ───────────────────────────────────────────────────────────────
    st.markdown("### Filtres")
    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        sel_lines = st.pills("Linia", options=ALL_LINES,
                             selection_mode="multi", default=ALL_LINES, key="map_lines")
    with fcol2:
        sel_idiomes = st.pills("Idioma", options=ALL_IDIOMES,
                               selection_mode="multi", default=list(ALL_IDIOMES), key="map_idiomes")
    with fcol3:
        sel_caracters = st.pills("Caracter", options=ALL_CARACTERS,
                                 selection_mode="multi", default=list(ALL_CARACTERS), key="map_caracters")

    # Filtre per dia — calendari
    dcol1, dcol2 = st.columns([1, 3])
    with dcol1:
        sel_date = st.date_input(
            "Filtrar per dia (opcional)",
            value=None,
            min_value=ALL_DATES_DT[0]  if ALL_DATES_DT else None,
            max_value=ALL_DATES_DT[-1] if ALL_DATES_DT else None,
            help="Deixa en blanc per veure tots els dies",
            key="map_date",
        )

    st.divider()

    # ── Filtres aplicats ──────────────────────────────────────────────────────
    df_f = df_exp.copy()
    if sel_lines:
        df_f = df_f[df_f["line"].isin(sel_lines)]
    if sel_idiomes:
        df_f = df_f[df_f["idioma"].isin(sel_idiomes)]
    if sel_caracters:
        df_f = df_f[df_f["caracter"].isin(sel_caracters)]
    if sel_date is not None:
        # Comparacio robusta: convertir a string YYYY-MM-DD sigui quin sigui el tipus
        sel_date_str = str(sel_date)[:10]
        df_f = df_f[df_f["date"].astype(str).str[:10] == sel_date_str]

    station_agg = (
        df_f.groupby(["station", "lat", "lon", "line"])
        .agg(n_tweets=("tweet_id", "nunique"),
             tweets=("tweet_text", list),
             timestamps=("timestamp", list))
        .reset_index()
    )

    if sel_date is not None:
        st.info(f"Mostrant {len(station_agg)} estacions per al dia {sel_date.strftime('%d/%m/%Y')} "
                f"({df_f['tweet_id'].nunique()} tweets)")

    # ── Mapa + llegenda lateral ───────────────────────────────────────────────
    map_col, leg_col = st.columns([3, 1])

    with map_col:
        m = folium.Map(location=[41.65, 1.8], zoom_start=8, tiles="CartoDB positron")

        # Linies del tren
        active_lines = sel_lines if sel_lines else ALL_LINES
        for line in active_lines:
            if line not in stations_raw:
                continue
            color     = LINE_COLORS.get(line, DEFAULT_COLOR)
            sorted_st = sorted(stations_raw[line], key=lambda s: s["index"])
            coords    = [[s["lat"], s["lon"]] for s in sorted_st]
            folium.PolyLine(coords, color=color, weight=4,
                            opacity=0.65, tooltip=f"Linia {line}").add_to(m)

        # Cercles + etiquetes per estacio
        max_n = station_agg["n_tweets"].max() if len(station_agg) > 0 else 1
        for _, row in station_agg.iterrows():
            color  = LINE_COLORS.get(row["line"], DEFAULT_COLOR)
            n      = row["n_tweets"]
            radius = 8 + (n / max_n) * 22
            lat, lon = row["lat"], row["lon"]
            name   = row["station"]

            items_html = "".join(
                f"<li style='margin-bottom:5px'><small><b>{str(ts)[:16]}</b><br>"
                f"{str(tw)[:130]}{'...' if len(str(tw))>130 else ''}</small></li>"
                for tw, ts in zip(row["tweets"][:5], row["timestamps"][:5])
            )
            more = f"<small><i>+ {n-5} tweets mes...</i></small>" if n > 5 else ""
            popup_html = f"""
            <div style='width:290px;font-family:sans-serif'>
              <h4 style='margin:0;color:{color}'>{name}</h4>
              <p style='margin:4px 0'><b>Linia:</b> {row['line'] or 'N/D'}
                 &nbsp;|&nbsp; <b>{n} tweet{'s' if n>1 else ''}</b></p>
              <hr style='margin:6px 0'>
              <ul style='padding-left:14px;margin:0'>{items_html}</ul>{more}
            </div>"""

            folium.CircleMarker(
                location=[lat, lon], radius=radius,
                color="white", fill=True, fill_color=color,
                fill_opacity=0.9, weight=2,
                popup=folium.Popup(popup_html, max_width=310),
                tooltip=f"{name} · {n} tweets · {row['line'] or 'N/D'}",
            ).add_to(m)

            # Nom de l'estacio
            folium.Marker(
                location=[lat, lon],
                icon=folium.DivIcon(
                    html=f"""<div style="font-size:9.5px;font-weight:600;
                        font-family:'Helvetica Neue',Arial,sans-serif;color:#1a1a1a;
                        white-space:nowrap;pointer-events:none;
                        text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,
                                    -1px 1px 0 #fff,1px 1px 0 #fff,0 0 3px #fff;
                        margin-top:{int(radius)+4}px;
                        margin-left:{int(radius)+4}px;">{name}</div>""",
                    icon_size=(0, 0), icon_anchor=(0, 0),
                ),
            ).add_to(m)

        st_folium(m, width=None, height=620, returned_objects=[])

    with leg_col:
        st.markdown("### Linies")

        line_tweet_counts = {}
        if len(df_exp) > 0:
            ltd = df_exp.copy()
            if sel_lines:
                ltd = ltd[ltd["line"].isin(sel_lines)]
            if sel_date is not None:
                ltd = ltd[ltd["date"] == str(sel_date)]
            line_tweet_counts = ltd.groupby("line")["tweet_id"].nunique().to_dict()

        for line in active_lines:
            color  = LINE_COLORS.get(line, DEFAULT_COLOR)
            n_tw   = line_tweet_counts.get(line, 0)
            st_list = stations_raw.get(line, [])
            sorted_sts = sorted(st_list, key=lambda s: s["index"])

            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin-top:8px'>"
                f"<div style='width:18px;height:8px;background:{color};"
                f"border-radius:2px;flex-shrink:0'></div>"
                f"<b style='font-size:14px'>{line}</b>"
                f"<span style='color:#666;font-size:12px'>({n_tw} tweets)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            with st.expander(f"Estacions ({len(sorted_sts)})", expanded=False):
                for s in sorted_sts:
                    st.markdown(
                        f"<div style='font-size:11px;padding:1px 0;color:#333'>· {s['name']}</div>",
                        unsafe_allow_html=True,
                    )

    # Taula tweets
    st.divider()
    with st.expander("Veure tweets amb estacio detectada"):
        cols = ["timestamp", "tweet_text", "stations_list", "lines_list", "idioma", "caracter"]
        cols_ok = [c for c in cols if c in df.columns]
        df_taula = df.copy()
        if sel_idiomes:
            df_taula = df_taula[df_taula["idioma"].isin(sel_idiomes)]
        if sel_caracters:
            df_taula = df_taula[df_taula["caracter"].isin(sel_caracters)]
        if sel_date is not None:
            df_taula = df_taula[df_taula["date"] == str(sel_date)]
        df_taula = df_taula[df_taula["stations_list"] != ""]
        st.dataframe(df_taula[cols_ok].sort_values("timestamp", ascending=False),
                     use_container_width=True, height=280)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ANALISI TEMPORAL
# ══════════════════════════════════════════════════════════════════════════════
with tab_temporal:

    st.markdown("### Filtres")
    tcol1, tcol2, tcol3 = st.columns(3)
    with tcol1:
        t_lines = st.pills("Linia", options=ALL_LINES,
                           selection_mode="multi", default=ALL_LINES, key="temp_lines")
    with tcol2:
        t_idiomes = st.pills("Idioma", options=ALL_IDIOMES,
                             selection_mode="multi", default=list(ALL_IDIOMES), key="temp_idiomes")
    with tcol3:
        t_caracters = st.pills("Caracter", options=ALL_CARACTERS,
                               selection_mode="multi", default=list(ALL_CARACTERS), key="temp_caracters")
    st.divider()

    df_t = df.copy()
    if t_lines:
        df_t = df_t[df_t["lines_list"].apply(
            lambda x: any(l in str(x).split("|") for l in t_lines)
        )]
    if t_idiomes:
        df_t = df_t[df_t["idioma"].isin(t_idiomes)]
    if t_caracters:
        df_t = df_t[df_t["caracter"].isin(t_caracters)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tweets filtrats", len(df_t))
    m2.metric("Dies amb activitat", df_t["date"].nunique())
    m3.metric("Mesos amb activitat", df_t["month"].nunique())
    m4.metric("Tweets totals", len(df))

    st.divider()

    # ── Grafic diari amb selector de mes ──────────────────────────────────────
    st.subheader("Volum diari de tweets")

    sel_month = st.selectbox(
        "Mes a visualitzar",
        options=["Tots els mesos"] + list(ALL_MONTHS),
        index=0,
        key="sel_month_daily",
    )

    if len(df_t) > 0:
        df_daily_src = df_t[df_t["month"] == sel_month] if sel_month != "Tots els mesos" else df_t

        daily = df_daily_src.groupby("date").size().reset_index(name="n_tweets")
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.sort_values("date")
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
            title=f"Tweets per dia {scope}",
            xaxis_title="Data", yaxis_title="Tweets",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            height=360,
        )
        st.plotly_chart(fig_d, use_container_width=True)

        st.markdown("**Top 3 dies del periode seleccionat:**")
        top3_show = top3_days.copy()
        top3_show["date"] = top3_show["date"].dt.strftime("%d/%m/%Y")
        st.dataframe(top3_show.rename(columns={"date": "Data", "n_tweets": "Tweets"}),
                     use_container_width=True, hide_index=True)
    else:
        st.info("No hi ha dades per als filtres seleccionats.")

    st.divider()

    # ── Comparativa mensual — top 3 en vermell ────────────────────────────────
    st.subheader("Comparativa mensual (top 3 en vermell)")

    if len(df_t) > 0:
        monthly = df_t.groupby("month").size().reset_index(name="n_tweets").sort_values("month")
        top3_months = set(monthly.nlargest(3, "n_tweets")["month"])
        bar_colors  = ["#DC143C" if m in top3_months else "#3B82F6"
                       for m in monthly["month"]]

        fig_m = go.Figure(go.Bar(
            x=monthly["month"], y=monthly["n_tweets"],
            marker_color=bar_colors,
            hovertemplate="%{x}: %{y} tweets<extra></extra>",
        ))
        fig_m.update_layout(
            xaxis_title="Mes", yaxis_title="Tweets", height=350,
            annotations=[dict(
                x=0.99, y=0.99, xref="paper", yref="paper",
                text="Vermell = top 3 mesos   Blau = resta",
                showarrow=False, font=dict(size=11),
                bgcolor="white", bordercolor="#ccc", borderwidth=1,
            )],
        )
        st.plotly_chart(fig_m, use_container_width=True)

    st.divider()

    # ── Tweets per hora del dia (stacked per caracter) ────────────────────────
    st.subheader("Activitat per hora del dia per caracter")
    st.caption("Distribucio de tots els tweets per hora i tipus de tweet")

    if len(df_t) > 0:
        cartypes = df_t["caracter"].unique()
        hourly_car = df_t.groupby(["hour", "caracter"]).size().reset_index(name="n")
        full_idx = pd.MultiIndex.from_product([range(24), cartypes], names=["hour", "caracter"])
        hourly_car = (hourly_car.set_index(["hour", "caracter"])
                                .reindex(full_idx, fill_value=0)
                                .reset_index())

        fig_h = px.bar(
            hourly_car, x="hour", y="n", color="caracter",
            barmode="stack",
            color_discrete_map=CARACTER_COLORS,
            labels={"hour": "Hora del dia", "n": "Tweets", "caracter": "Caracter"},
        )
        fig_h.update_layout(
            xaxis=dict(tickmode="linear", tick0=0, dtick=1),
            height=340,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_h, use_container_width=True)

    st.divider()

    # ── Top 10 dies globals ───────────────────────────────────────────────────
    st.subheader("Top 10 dies amb mes activitat (global)")

    if len(df_t) > 0:
        def car_pred(series):
            return series.value_counts().index[0] if len(series) > 0 else "—"

        top10 = (
            df_t.groupby("date")
            .agg(
                n_tweets=("tweet_id", "count"),
                car_pred=("caracter", car_pred),
                estacions=("stations_list", lambda x: ", ".join(
                    sorted(set(s for v in x if v for s in str(v).split("|") if s))[:4]
                )),
            )
            .reset_index()
            .sort_values("n_tweets", ascending=False)
            .head(10)
        )
        top10["date"] = pd.to_datetime(top10["date"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            top10.rename(columns={
                "date": "Data", "n_tweets": "Tweets",
                "car_pred": "Caracter predominant",
                "estacions": "Estacions principals",
            }),
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ANALISI PER LINIES
# ══════════════════════════════════════════════════════════════════════════════
with tab_linies:

    st.markdown("### Filtres")
    lcol1, lcol2 = st.columns(2)
    with lcol1:
        l_idiomes = st.pills("Idioma", options=ALL_IDIOMES,
                             selection_mode="multi", default=list(ALL_IDIOMES), key="lin_idiomes")
    with lcol2:
        l_caracters = st.pills("Caracter", options=ALL_CARACTERS,
                               selection_mode="multi", default=list(ALL_CARACTERS), key="lin_caracters")
    st.divider()

    df_l = df_exp.copy()
    if l_idiomes:
        df_l = df_l[df_l["idioma"].isin(l_idiomes)]
    if l_caracters:
        df_l = df_l[df_l["caracter"].isin(l_caracters)]

    # ── Tweets per linia ──────────────────────────────────────────────────────
    st.subheader("Quines linies reben mes tweets?")

    if len(df_l) > 0:
        line_counts = (
            df_l.groupby("line")["tweet_id"].nunique()
            .reset_index(name="n_tweets")
            .sort_values("n_tweets", ascending=True)
        )
        line_counts["color"] = line_counts["line"].map(LINE_COLORS).fillna(DEFAULT_COLOR)

        fig_lines = go.Figure(go.Bar(
            x=line_counts["n_tweets"],
            y=line_counts["line"],
            orientation="h",
            marker_color=line_counts["color"].tolist(),
            text=line_counts["n_tweets"],
            textposition="outside",
        ))
        fig_lines.update_layout(
            xaxis_title="Tweets unics", yaxis_title="Linia",
            height=350, margin=dict(l=60, r=80),
        )
        st.plotly_chart(fig_lines, use_container_width=True)
    else:
        st.info("No hi ha dades per als filtres seleccionats.")

    st.divider()

    # ── Per estacio: % de cada caracter ──────────────────────────────────────
    st.subheader("Distribucio de caracter per estacio")
    st.caption("Selecciona una linia per veure les seves estacions")

    sel_line_est = st.pills(
        "Linia a analitzar",
        options=ALL_LINES,
        selection_mode="single",
        default="R1",
        key="lin_sel_line",
    )

    if sel_line_est and len(df_l) > 0:
        df_line = df_l[df_l["line"] == sel_line_est].copy()

        if len(df_line) == 0:
            st.info(f"Cap tweet per a la linia {sel_line_est} amb els filtres actuals.")
        else:
            est_car = (
                df_line.groupby(["station", "caracter"])["tweet_id"]
                .nunique()
                .reset_index(name="n")
            )
            totals  = est_car.groupby("station")["n"].sum().reset_index(name="total")
            est_car = est_car.merge(totals, on="station")
            est_car["pct"] = (est_car["n"] / est_car["total"] * 100).round(1)
            order = totals.sort_values("total", ascending=True)["station"].tolist()

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
                pivot = pivot.sort_values("Total", ascending=False)
                st.dataframe(pivot, use_container_width=True)
    else:
        st.info("Selecciona una linia per veure les estacions.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — ANALISI D'INCIDENCIES
# ══════════════════════════════════════════════════════════════════════════════
with tab_inc:

    st.markdown("### Filtres")
    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        sel_tipos = st.pills(
            "Tipus d'incident", options=ALL_TIPOS,
            selection_mode="multi", default=ALL_TIPOS, key="inc_tipos",
        )
    with ic2:
        conf_opts = ["Totes", "Alta (>= 0.88)", "Mitja (0.75 - 0.85)", "Baixa (<= 0.75)"]
        sel_conf  = st.selectbox("Confianca", conf_opts, index=0, key="inc_conf")
    with ic3:
        sel_mes = st.selectbox("Mes", INC_MONTHS, index=len(INC_MONTHS) - 1,
                               key="inc_mes")
    st.divider()

    # ── Aplicar filtres ───────────────────────────────────────────────────────
    tipos_actius = sel_tipos if sel_tipos else ALL_TIPOS
    df_i = df_inc[df_inc["tipo_incidencia"].isin(tipos_actius)]

    if sel_conf == "Alta (>= 0.88)":
        df_i = df_i[df_i["confianza"] >= 0.88]
    elif sel_conf == "Mitja (0.75 - 0.85)":
        df_i = df_i[df_i["confianza"].between(0.75, 0.85)]
    elif sel_conf == "Baixa (<= 0.75)":
        df_i = df_i[df_i["confianza"] <= 0.75]

    df_mes_inc = df_i[df_i["month"] == sel_mes] if sel_mes else df_i.iloc[:0]

    # ── Metriques del mes ─────────────────────────────────────────────────────
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Tweets incident (mes)", len(df_mes_inc))
    mc2.metric("Dies amb activitat", df_mes_inc["date"].nunique())
    mc3.metric(
        "Tipus mes frequent",
        df_mes_inc["tipo_incidencia"].mode().iloc[0] if len(df_mes_inc) > 0 else "—",
    )
    mc4.metric("Total incidents (dataset)", len(df_i))

    st.divider()

    # ── Grafic principal: volum diari per tipo (stacked) ──────────────────────
    st.subheader(f"Volum diari d'incidents — {sel_mes}")
    if len(df_mes_inc) > 0:
        daily_tipo = (
            df_mes_inc.groupby(["date", "tipo_incidencia"])
            .size().reset_index(name="n")
        )
        fig_inc = px.bar(
            daily_tipo, x="date", y="n", color="tipo_incidencia",
            barmode="stack", color_discrete_map=TIPO_COLORS,
            labels={"date": "Dia", "n": "Tweets", "tipo_incidencia": "Tipus"},
        )
        fig_inc.update_layout(
            xaxis=dict(tickformat="%d/%m", tickangle=-45),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            height=400,
        )
        st.plotly_chart(fig_inc, use_container_width=True)
    else:
        st.info("Sense dades per al mes i filtres seleccionats.")

    st.divider()

    # ── Grafic resum: total per tipo (periode complet) ────────────────────────
    st.subheader("Distribucio per tipus (periode complet)")
    if len(df_i) > 0:
        tipo_total = (
            df_i.groupby("tipo_incidencia").size()
            .reset_index(name="n")
            .sort_values("n", ascending=True)
        )
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

    # ── Taula de tweets del mes ───────────────────────────────────────────────
    with st.expander("Veure tweets del mes seleccionat"):
        cols_inc = ["date", "tweet_text", "tipo_incidencia", "confianza", "metodo"]
        st.dataframe(
            df_mes_inc[cols_inc].sort_values("date", ascending=False),
            use_container_width=True, height=280,
        )
