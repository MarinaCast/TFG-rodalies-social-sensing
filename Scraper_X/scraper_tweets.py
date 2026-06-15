from playwright.sync_api import sync_playwright
import pandas as pd
import time
from datetime import datetime, timedelta
import os
import subprocess
from zoneinfo import ZoneInfo

#QUERIES = {"rodalies": 20, "R1 retard": 3, "R2 retard": 3, "R3 retard": 3, "R4 retard": 3, "R7 retard": 3, "R8 retard": 3, "R1 retraso": 3, "R2 retraso": 3, "R3 retraso": 3, "R4 retraso": 3, "R7 retraso": 3, "R8 retraso": 3}
QUERIES = {"rodalies": 10, "R1 retard": 1, "R2 retard": 1, "R3 retard": 1, "R4 retard": 1, "R7 retard": 1, "R8 retard": 1, "R1 retraso": 1, "R2 retraso": 1, "R3 retraso": 1, "R4 retraso": 1, "R7 retraso": 1, "R8 retraso": 1}
#QUERIES = {"rodalies": 2}
BASE_URL = "https://nitter.privacyredirect.com/search?f=tweets&q={query}"
LOG_FILE = "log_execucions1.txt"
#CSV_FILE = "/mnt/vmdata/twinnets-nets/tweets/tweets_data.csv"
CSV_FILE = "all_tweets.csv"

def orderCSV():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        df["datetime"] = pd.to_datetime(df["date"] + " " + df["hora"], errors="coerce")
        df = df.dropna(subset=["datetime"])
        df = df.sort_values(by="datetime", ascending=False)
        df.to_csv(CSV_FILE, index=False, encoding="utf-8")
        print(f"[INFO] CSV ordenat per data i hora: {CSV_FILE}")
    else:
        print("[ERROR] El fitxer CSV no existeix.")

def run_csv2json(max_retries=2):
    """Executa csv2json.py amb reintents des del mateix directori del projecte."""
    cmd = ["python3", "csv2json.py"]
    attempt = 1
    while attempt <= max_retries:
        print(f"[INFO] Executant csv2json.py (intent {attempt}/{max_retries})...")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            print("[OK] csv2json.py ha finalitzat correctament.")
            return True
        print(f"[ERROR] csv2json.py ha fallat (returncode {result.returncode}).")
        attempt += 1
    print(f"[ERROR] Han fallat {max_retries} intents per a csv2json.py.")
    return False

def parse_datetime(raw_text):
    try:
        return datetime.strptime(raw_text, "%Y-%m-%d %H:%M")
    except:
        pass
    try:
        return datetime.strptime(raw_text.replace("·", "").strip(), "%b %d, %Y %I:%M %p UTC")
    except:
        return None

def scrape_nitter_page(page, query, latest_datetime, max_pages=5):
    query_encoded = query.replace(" ", "+")
    url = BASE_URL.format(query=query_encoded)
    print(f"[INFO] Scrapejant: {url}")
    page.goto(url)
    page.wait_for_load_state("networkidle")
    time.sleep(10)

    all_data = []
    links = []
    current_page = 1
    today = datetime.today().date()

    while current_page <= max_pages:
        print(f"[INFO] Processant pàgina {current_page}")
        tweets = page.query_selector_all("div.timeline-item")
        print(f"[INFO] Tuits trobats: {len(tweets)}")
        for tweet in tweets:
            try:
                content_raw = tweet.query_selector("div.tweet-content").inner_text().strip()
                content = content_raw.replace("\n", " ")
                user = tweet.query_selector("a.username").inner_text().strip()
                time_tag = tweet.query_selector("span.tweet-date > a")

                raw_datetime = ""
                if time_tag:
                    raw_datetime = time_tag.get_attribute("title") or time_tag.inner_text().strip()

                dt = parse_datetime(raw_datetime)
                # Convertir de UTC a hora local de España (UTC+1 en invierno, UTC+2 en verano)
                if dt:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Madrid"))
                    dt = dt.replace(tzinfo=None)  # Quitar timezone info para mantener compatibilidad
                if latest_datetime and dt <= latest_datetime:
                    print(f"[INFO] Tuit descartat. {dt} més tard que: {latest_datetime}")
                    continue

                hora = dt.strftime("%H:%M") if dt else ""
                date = dt.date().isoformat() if dt else ""
                link = "https://nitter.poast.org" + time_tag.get_attribute("href") if time_tag else ""
                if link not in links:
                    links.append(link)
                else:
                    print(f"[INFO] Tuit duplicat trobat: {link}, saltant.")
                    continue
                all_data.append({
                    "hora": hora,
                    "date": date,
                    "query": query,
                    "user": user,
                    "content": content,
                    "link": link,
                    "raw_datetime": raw_datetime
                })
            except Exception:
                continue

        # Look for the next page link
        next_link = page.query_selector("div.show-more > a")
        if not next_link:
            break

        
        next_button = page.locator("a:has-text('Load more')")
        if not next_button or not next_button.is_visible():
            break
        next_button.click()
        page.wait_for_load_state("networkidle")
        time.sleep(10)
        current_page += 1

    return all_data

def main():
    while True:
        existing_links = set()
        if os.path.exists(CSV_FILE):
            df_existing = pd.read_csv(CSV_FILE)
            existing_links = set(df_existing["link"])
            # Convertir columnas de fecha y hora a datetime
            df_existing["datetime"] = pd.to_datetime(df_existing["date"] + " " + df_existing["hora"], errors="coerce")
            df_existing = df_existing.dropna(subset=["datetime"])
            if not df_existing.empty:
                latest_datetime = df_existing["datetime"].max()
                print(f"[INFO] Última data registrada: {latest_datetime}")
        else:
            df_existing = pd.DataFrame()
            latest_datetime = None

        all_data = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ca,en;q=0.9",
                    "Referer": "https://google.com",
                    "Connection": "keep-alive",
                    "DNT": "1"
                }
            )
            page = context.new_page()

            for query, max_pages in QUERIES.items():
                tweets = scrape_nitter_page(page, query, latest_datetime=latest_datetime, max_pages=max_pages)
                for tweet in tweets:
                    if tweet["link"] not in existing_links:
                        all_data.append(tweet)
                time.sleep(10)

            browser.close()

        if all_data:
            df_new = pd.DataFrame(all_data)
            df_total = pd.concat([df_existing, df_new], ignore_index=True)
            df_total.to_csv(CSV_FILE, index=False, encoding="utf-8")
            print(f"[INFO] S'han afegit {len(df_new)} tuits nous.")
        else:
            print("[INFO] No s'han trobat tuits nous.")

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Executat correctament. Tuits nous: {len(all_data)}\n")
        orderCSV()

        run_csv2json(max_retries=2)

        time.sleep(1800)  # Espera 30 minutos antes de la siguiente ejecución


if __name__ == "__main__":
    main()