import json
import time
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)


OUTPUT_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")
TARGET_ARTICLES = 50
HEADLESS        = False   # ← False = browser tampil di layar (visible mode)
WAIT_TIMEOUT    = 15      # detik maksimum WebDriverWait
SCROLL_PAUSE    = 1.2     # detik jeda antar scroll

PAGES_TO_SCRAPE = [
    "https://www.wired.com/",
    "https://www.wired.com/category/science/",
    "https://www.wired.com/category/business/",
    "https://www.wired.com/category/security/",
    "https://www.wired.com/category/culture/",
    "https://www.wired.com/category/gear/",
    "https://www.wired.com/category/ideas/",
    "https://www.wired.com/tag/artificial-intelligence/",
]

# Selector kartu artikel — dicoba berurutan sampai ada yang menghasilkan ≥5 elemen
CARD_SELECTORS = [
    "div.summary-item",
    "div[class*='SummaryItem']",
    "article",
    "li[class*='summary']",
]

# ─── Setup Driver ─────────────────────────────────────────────────────────────

def create_driver() -> webdriver.Chrome:
    options = Options()

    if HEADLESS:
        options.add_argument("--headless=new")
        print("  [MODE] Headless")
    else:
        print("  [MODE] Visible")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1400,900")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--allow-insecure-localhost")

    driver = webdriver.Chrome(options=options)

    # Sembunyikan tanda otomasi dari JavaScript halaman
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )

    return driver



def wait_for_page_ready(driver: webdriver.Chrome, timeout: int = WAIT_TIMEOUT) -> None:
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        print("    [WAIT] Halaman selesai dimuat")
    except TimeoutException:
        print("    [WAIT] Timeout menunggu halaman")


def wait_for_cards(driver: webdriver.Chrome, timeout: int = WAIT_TIMEOUT) -> list:
    for selector in CARD_SELECTORS:
        try:
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            cards = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(cards) >= 5:
                print(f"    [WAIT] Kartu ditemukan dengan selector '{selector}' → {len(cards)} kartu")
                return cards
        except TimeoutException:
            print(f"    [WAIT] Selector '{selector}' timeout, coba berikutnya...")
            continue

    print("    [WAIT] Semua selector timeout — gunakan fallback link")
    return []


def close_cookie_banner(driver: webdriver.Chrome) -> None:
    try:
        btn = WebDriverWait(driver, 6).until(
            EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                "button[id*='accept'], button[class*='accept'], "
                "#onetrust-accept-btn-handler, [aria-label*='Accept']"
            ))
        )
        btn.click()
        print("    [WAIT] Cookie banner ditutup")
        WebDriverWait(driver, 5).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, "#onetrust-banner-sdk"))
        )
    except TimeoutException:
        pass


def scroll_to_load(driver: webdriver.Chrome, scrolls: int = 4) -> None:
    print(f"    [WAIT] Scroll {scrolls}x untuk trigger lazy-load...")
    last_count = 0

    for i in range(scrolls):
        driver.execute_script("window.scrollBy(0, window.innerHeight * 2);")

        try:
            WebDriverWait(driver, 2).until(
                lambda d: len(d.find_elements(
                    By.CSS_SELECTOR, "div.summary-item, article"
                )) > last_count
            )
        except TimeoutException:
            pass  # Tidak ada konten baru, tetap lanjut scroll

        current_count = len(driver.find_elements(By.CSS_SELECTOR, "div.summary-item, article"))
        print(f"      Scroll {i+1}/{scrolls} — {current_count} elemen terdeteksi")
        last_count = current_count
        time.sleep(SCROLL_PAUSE)

    driver.execute_script("window.scrollTo(0, 0);")



def extract_articles_from_page(driver: webdriver.Chrome, page_url: str) -> list[dict]:
    articles: list[dict] = []
    seen_urls: set[str]  = set()

    try:
        print(f"\n  ─── Membuka: {page_url}")
        driver.get(page_url)

        # Wait 1: Tunggu halaman selesai dimuat
        wait_for_page_ready(driver)

        # Wait 2: Tutup cookie banner jika ada
        close_cookie_banner(driver)

        # Wait 3: Scroll + tunggu lazy-load
        scroll_to_load(driver)

        # Wait 4: Tunggu kartu artikel muncul di DOM
        cards = wait_for_cards(driver)

        # Fallback jika kartu tidak terdeteksi
        if not cards:
            print("    [FALLBACK] Gunakan selector link artikel langsung")
            return _extract_via_links(driver, seen_urls)

        # Parse tiap kartu
        print(f"    [PARSE] Memproses {len(cards)} kartu...")
        for idx, card in enumerate(cards, 1):
            try:
                article = parse_card(card)
                if article and article["url"] not in seen_urls and len(article["title"]) > 5:
                    seen_urls.add(article["url"])
                    articles.append(article)
                    print(f"      [{idx:02d}] ✓ {article['title'][:65]}")
            except StaleElementReferenceException:
                print(f"      [{idx:02d}] ⚠ StaleElement — elemen berubah saat dibaca, skip")
                continue
            except Exception as exc:
                print(f"      [{idx:02d}] ⚠ Error: {exc}")
                continue

    except WebDriverException as exc:
        print(f"  [ERROR] WebDriver error di {page_url}: {exc}")

    return articles


def _extract_via_links(driver: webdriver.Chrome, seen_urls: set) -> list[dict]:
    articles = []
    try:
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/story/']"))
        )
        raw_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/story/']")

        for link in raw_links:
            href  = _safe_get_attr(link, "href")
            title = link.text.strip() or _safe_get_attr(link, "aria-label")

            if not href or not title or len(title) < 5 or href in seen_urls:
                continue

            full_url = href if href.startswith("http") else f"https://www.wired.com{href}"
            seen_urls.add(full_url)
            articles.append({
                "title":       title,
                "url":         full_url,
                "description": None,
                "author":      None,
                "scraped_at":  datetime.now().isoformat(),
                "source":      "Wired.com",
            })
            print(f"      [LINK] ✓ {title[:65]}")

    except TimeoutException:
        print("    [FALLBACK] Tidak ada link /story/ dalam batas waktu")

    return articles


def parse_card(card) -> dict | None:
    # ── Title ──
    title = ""
    for sel in ["h2", "h3", "h4", "[class*='Hed']", "[class*='hed']", "[class*='title']"]:
        try:
            el    = card.find_element(By.CSS_SELECTOR, sel)
            title = el.text.strip()
            if title:
                break
        except NoSuchElementException:
            continue

    if not title:
        return None

    # ── URL ──
    url = ""
    for sel in ["a[href*='/story/']", "a[href*='wired.com']", "a"]:
        try:
            el   = card.find_element(By.CSS_SELECTOR, sel)
            href = _safe_get_attr(el, "href")
            if href and ("/story/" in href or "wired.com" in href):
                url = href if href.startswith("http") else f"https://www.wired.com{href}"
                break
        except NoSuchElementException:
            continue

    if not url:
        return None

    # ── Description ──
    description = None
    for sel in ["[class*='Dek']", "[class*='dek']", "[class*='description']", "p"]:
        try:
            el   = card.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text and text != title:
                description = text
                break
        except NoSuchElementException:
            continue

    # ── Author  ──
    author = None
    for sel in [
        "[class*='Byline']", "[class*='byline']",
        "[class*='Author']", "[class*='author']",
        "[class*='contributor']",
    ]:
        try:
            el   = card.find_element(By.CSS_SELECTOR, sel)
            text = el.get_attribute("textContent").strip()
            if text:
                author = text if text.startswith("By") else "By" + text
                break
        except NoSuchElementException:
            continue

    return {
        "title":       title,
        "url":         url,
        "description": description,
        "author":      author,
        "scraped_at":  datetime.now().isoformat(),
        "source":      "Wired.com",
    }


def _safe_get_attr(element, attr: str) -> str:
    try:
        return element.get_attribute(attr) or ""
    except Exception:
        return ""



def run_scraper() -> dict:
    session_id = f"wired_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"  Wired.com Scraper")
    print(f"  Session  : {session_id}")
    print(f"  Target   : {TARGET_ARTICLES} artikel")
    print(f"  Timeout  : {WAIT_TIMEOUT}s per elemen")

    driver       = create_driver()
    all_articles: list[dict] = []
    seen_urls:    set[str]   = set()

    try:
        for page_url in PAGES_TO_SCRAPE:
            if len(all_articles) >= TARGET_ARTICLES:
                print(f"\n  ✓ Target {TARGET_ARTICLES} artikel tercapai. Selesai.")
                break

            page_articles = extract_articles_from_page(driver, page_url)

            new_articles = [a for a in page_articles if a["url"] not in seen_urls]
            for a in new_articles:
                seen_urls.add(a["url"])

            all_articles.extend(new_articles)
            print(f"\n  → +{len(new_articles)} baru | Total: {len(all_articles)}")
            time.sleep(2)

    finally:
        print("\n  Selesai")
        driver.quit()

    return {
        "session_id":     session_id,
        "timestamp":      datetime.now().isoformat(),
        "articles_count": len(all_articles),
        "articles":       all_articles,
    }


def save_to_json(data: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename    = f"wired_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath    = os.path.join(OUTPUT_DIR, filename)
    latest_path = os.path.join(OUTPUT_DIR, "wired_latest.json")

    for path in [filepath, latest_path]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([data], f, indent=2, ensure_ascii=False)

    print(f"  ✓ Disimpan ke : {filepath}")
    print(f"  ✓ Latest      : {latest_path}")
    return filepath



if __name__ == "__main__":
    data = run_scraper()
    save_to_json(data)
    print(f"\n{'='*60}")
    print(f"  Selesai! {data['articles_count']} artikel berhasil diambil.")
    print(f"{'='*60}\n")