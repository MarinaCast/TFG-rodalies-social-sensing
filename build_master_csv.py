"""
Genera Fonts/tweets_merged.csv
Uneix les tres fonts de dades per tweet_id:
  - all_tweets.csv      -> contingut original, usuari, hora exacta
  - classificacio_...   -> línia, estació, caràcter (informatiu/queixa/indefinit)
  - tweets_incidencias  -> tipus d'incident, confiança, mètode
"""

import pandas as pd
import re
import os

BASE = r"C:\MARINA\Universitat\TFG - Visualització\Fonts"

# ── 1. all_tweets.csv ─────────────────────────────────────────────────────────
print("Carregant all_tweets.csv...")
df_all = pd.read_csv(f"{BASE}/all_tweets.csv", encoding="utf-8", low_memory=False)
# Extreure tweet_id de la columna 'link'
# Exemple: https://nitter.poast.org/user/status/1234567890#m -> 1234567890
df_all["tweet_id"] = (
    df_all["link"]
    .astype(str)
    .str.extract(r"/status/(\d+)", expand=False)
)
df_all["datetime"] = pd.to_datetime(df_all["datetime"], errors="coerce")
df_all["date"]     = df_all["datetime"].dt.strftime("%Y-%m-%d")
df_all["hora_min"] = df_all["datetime"].dt.strftime("%H:%M")
df_all["hour"]     = df_all["datetime"].dt.hour

# tweet_id = posicio (1-indexed) = coincideix amb els altres CSVs
df_all["tweet_id"] = range(1, len(df_all) + 1)
df_all = df_all[["tweet_id","user","content","date","hora_min","hour","likes","query"]].copy()
print(f"  -> {len(df_all):,} tweets")

# ── 2. classificacio_estacions_ubicacions.csv ─────────────────────────────────
print("Carregant classificacio_estacions_ubicacions.csv...")
df_class = pd.read_csv(f"{BASE}/classificacio_estacions_ubicacions.csv",
                       encoding="utf-8", low_memory=False)
df_class["tweet_id"] = df_class["tweet_id"].astype(str)
# Seleccionar columnes útils (una fila per tweet, no per estació)
df_class["tweet_id"] = pd.to_numeric(df_class["tweet_id"], errors="coerce")
class_per_tweet = (
    df_class[["tweet_id","idioma","caracter","lines_list","stations_list"]]
    .drop_duplicates(subset=["tweet_id"])
)
# Línia principal (primera de lines_list)
class_per_tweet["linia_principal"] = (
    class_per_tweet["lines_list"]
    .astype(str)
    .str.split("|")
    .str[0]
    .str.strip()
    .replace("", pd.NA)
)
print(f"  -> {len(class_per_tweet):,} tweets únics classificats")

# ── 3. tweets_incidencias.csv ─────────────────────────────────────────────────
print("Carregant tweets_incidencias.csv...")
df_inc = pd.read_csv(f"{BASE}/tweets_incidencias.csv", encoding="utf-8",
                     low_memory=False)
df_inc.columns = ["id","timestamp_inc","tweet_text_inc",
                  "tipo_incidencia","confianza","es_incidencia","metodo"]
df_inc["tweet_id"] = df_inc["id"].astype(str)
df_inc["confianza"] = pd.to_numeric(df_inc["confianza"], errors="coerce")
df_inc["tweet_id"] = pd.to_numeric(df_inc["id"], errors="coerce")
inc_per_tweet = df_inc[["tweet_id","tipo_incidencia","confianza",
                         "es_incidencia","metodo"]].drop_duplicates(subset=["tweet_id"])
print(f"  -> {len(inc_per_tweet):,} tweets únics amb classificació d'incident")

# ── 4. Unir tot ───────────────────────────────────────────────────────────────
print("Unint les tres fonts...")
master = df_all.merge(class_per_tweet, on="tweet_id", how="left")
master = master.merge(inc_per_tweet,   on="tweet_id", how="left")

# Renombrar columnes finals
master = master.rename(columns={
    "content":           "tweet_text",
    "hora_min":          "hora",
    "linia_principal":   "linia",
    "tipo_incidencia":   "tipus_incident",
    "es_incidencia":     "es_incident",
})

# Ordre de columnes
cols = [
    "tweet_id","date","hora","hour","user",
    "tweet_text","idioma","caracter",
    "linia","lines_list","stations_list",
    "tipus_incident","confianza","es_incident","metodo",
    "likes","query",
]
master = master[[c for c in cols if c in master.columns]]

print(f"\n=== RESULTAT FINAL ===")
print(f"Total files: {len(master):,}")
print(f"Tweets amb línia:    {master['linia'].notna().sum():,}")
print(f"Tweets amb incident: {master['tipus_incident'].notna().sum():,}")
print(f"Columnes: {list(master.columns)}")

# ── 5. Guardar ────────────────────────────────────────────────────────────────
out = f"{BASE}/tweets_merged.csv"
master.to_csv(out, index=False, encoding="utf-8")
print(f"\nGuardat a: {out}")
print(f"Mida: {os.path.getsize(out)/1024/1024:.1f} MB")

# ── 6. Mostra exemple dia 20/01/2026 R4 ──────────────────────────────────────
print("\n=== Exemple: R4 el 20/01/2026 (incidents) ===")
exemple = master[
    (master["date"] == "2026-01-20") &
    (master["linia"] == "R4") &
    (master["tipus_incident"].notna()) &
    (master["tipus_incident"] != "sin_incidencia")
].sort_values("hora")
print(exemple[["hora","user","tipus_incident","confianza","tweet_text"]].head(20).to_string())
