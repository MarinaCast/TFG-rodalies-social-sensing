"""
Demo recording script — grava un vídeo de l'app Streamlit navegant sola.
Resultat: video/demo.webm  (convertible a MP4 amb ffmpeg o VLC)

Executa amb:  python record_demo.py
L'app ha d'estar corrent a http://localhost:8503
"""

from playwright.sync_api import sync_playwright
import time, os

URL  = "http://localhost:8503"
OUT  = "video"
os.makedirs(OUT, exist_ok=True)

def smooth_scroll(page, px=600, steps=8, delay=80):
    for _ in range(steps):
        page.evaluate(f"window.scrollBy(0, {px // steps})")
        time.sleep(delay / 1000)

def scroll_to_top(page):
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.4)

def nav_to(page, label):
    page.locator(f"text={label}").first.click()
    time.sleep(2.5)
    scroll_to_top(page)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=60)
    ctx = browser.new_context(
        record_video_dir=OUT,
        viewport={"width": 1440, "height": 860},
    )
    page = ctx.new_page()

    print("Obrint l'app...")
    page.goto(URL, wait_until="networkidle", timeout=30000)
    time.sleep(3)

    # ── INICI ────────────────────────────────────────────────────────
    print("Pàgina Inici...")
    scroll_to_top(page)
    time.sleep(1.5)
    smooth_scroll(page, px=500, steps=10, delay=100)
    time.sleep(1)
    smooth_scroll(page, px=600, steps=10, delay=100)
    time.sleep(1.5)
    scroll_to_top(page)
    time.sleep(1)

    # ── MAPA GEOGRÀFIC ────────────────────────────────────────────────
    print("Pàgina Mapa...")
    nav_to(page, "Mapa geografic")
    time.sleep(2)
    smooth_scroll(page, px=700, steps=12, delay=110)   # veure mapa 1
    time.sleep(3)
    smooth_scroll(page, px=300, steps=8, delay=100)    # baixar a llegenda
    time.sleep(1.5)
    # Expandir llegenda
    try:
        page.locator("text=Linies actives").first.click()
        time.sleep(1.5)
    except Exception:
        pass
    smooth_scroll(page, px=800, steps=14, delay=100)   # mapa 2 calor
    time.sleep(3)
    smooth_scroll(page, px=800, steps=14, delay=100)   # mapa 3D
    time.sleep(3)
    smooth_scroll(page, px=600, steps=10, delay=100)   # mapa clusters
    time.sleep(2.5)
    scroll_to_top(page)
    time.sleep(1)

    # Canviar filtre d'etiquetes a "Top N"
    try:
        page.locator("text=Top N estacions").first.click()
        time.sleep(2)
        smooth_scroll(page, px=700, steps=12, delay=110)
        time.sleep(2)
        scroll_to_top(page)
        time.sleep(1)
    except Exception:
        pass

    # ── ANALISI TEMPORAL ─────────────────────────────────────────────
    print("Pàgina Anàlisi temporal...")
    nav_to(page, "Analisi temporal")
    smooth_scroll(page, px=600, steps=12, delay=110)
    time.sleep(2)
    smooth_scroll(page, px=600, steps=12, delay=110)
    time.sleep(2)
    scroll_to_top(page)
    time.sleep(1)

    # ── ANALISI PER LINIES ───────────────────────────────────────────
    print("Pàgina Anàlisi per línies...")
    nav_to(page, "Analisi per linies")
    smooth_scroll(page, px=500, steps=10, delay=110)
    time.sleep(2)
    smooth_scroll(page, px=500, steps=10, delay=110)
    time.sleep(2)
    scroll_to_top(page)
    time.sleep(1)

    # ── ANALISI D'INCIDENCIES ────────────────────────────────────────
    print("Pàgina Anàlisi d'incidències...")
    nav_to(page, "Analisi d'incidencies")
    smooth_scroll(page, px=600, steps=12, delay=110)
    time.sleep(2)
    smooth_scroll(page, px=500, steps=10, delay=110)
    time.sleep(2)
    scroll_to_top(page)
    time.sleep(1)

    # ── TORNAR A INICI ───────────────────────────────────────────────
    print("Tornant a Inici...")
    nav_to(page, "Inici")
    time.sleep(2)

    print("Tancant i guardant vídeo...")
    ctx.close()
    browser.close()

    # Renombrar el fitxer generat
    files = sorted(
        [f for f in os.listdir(OUT) if f.endswith(".webm")],
        key=lambda f: os.path.getmtime(os.path.join(OUT, f)),
        reverse=True,
    )
    if files:
        src = os.path.join(OUT, files[0])
        dst = os.path.join(OUT, "demo.webm")
        if src != dst:
            os.replace(src, dst)
        print(f"\nVídeo guardat a: {dst}")
        size_mb = os.path.getsize(dst) / 1024 / 1024
        print(f"Mida: {size_mb:.1f} MB")
        print("\nPer convertir a MP4 (si tens ffmpeg):")
        print(f"  ffmpeg -i {dst} -c:v libx264 video/demo.mp4")
    else:
        print("No s'ha trobat cap vídeo.")
