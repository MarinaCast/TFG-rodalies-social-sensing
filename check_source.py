import pandas as pd

# all_tweets.csv = dataset original
df_all = pd.read_csv(
    r'C:\MARINA\Universitat\TFG - Visualització\Fonts\all_tweets.csv',
    encoding='utf-8', low_memory=False
)
print("=== all_tweets.csv ===")
print(f"Total files: {len(df_all):,}")
print(f"Columnes: {list(df_all.columns)}")
print(f"Exemple id/key: {df_all.columns[0]} -> {df_all.iloc[0,0]}")
print()

# Identificar la columna d'ID
id_col = df_all.columns[0]
print(f"IDs unics a all_tweets: {df_all[id_col].nunique():,}")

# Comparar amb CSV principal
df_main = pd.read_csv(
    r'C:\MARINA\Universitat\TFG - Visualització\Fonts\classificacio_estacions_ubicacions.csv',
    encoding='utf-8', low_memory=False, usecols=['tweet_id']
)
main_ids = set(df_main['tweet_id'].dropna().astype(str))
all_ids  = set(df_all[id_col].dropna().astype(str))

print(f"IDs a all_tweets:   {len(all_ids):,}")
print(f"IDs al principal:   {len(main_ids):,}")
print(f"Interseccio:        {len(all_ids & main_ids):,}")
print(f"Nomes a all_tweets (no al principal): {len(all_ids - main_ids):,}")
print(f"Nomes al principal (no a all_tweets): {len(main_ids - all_ids):,}")
