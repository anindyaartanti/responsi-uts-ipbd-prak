import json
import logging
import re
from datetime import datetime, timedelta

import requests
import psycopg2
import psycopg2.extras
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from airflow.models import Variable
from airflow.utils.dates import days_ago

# ─── Konfigurasi ──────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

API_BASE_URL = Variable.get("WIRED_API_URL", default_var="http://wired-api:8000")
DB_CONFIG = {
    "host":     Variable.get("PG_HOST",     default_var="postgres"),
    "port":     Variable.get("PG_PORT",     default_var="5432"),
    "dbname":   Variable.get("PG_DB",       default_var="wired_pipeline"),
    "user":     Variable.get("PG_USER",     default_var="wired_user"),
    "password": Variable.get("PG_PASSWORD", default_var="wired_pass"),
}

DEFAULT_ARGS = {
    "owner": "data-engineer",
    "depends_on_past": False,
    "start_date": days_ago(1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

# ─── Task Functions ───────────────────────────────────────────────────────────


def task_check_api_health(**context) -> None:
    health_url = f"{API_BASE_URL}/health"
    logger.info(f"Memeriksa API health: {health_url}")

    try:
        resp = requests.get(health_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"API sehat: {data}")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"API tidak dapat diakses di {health_url}: {exc}") from exc


def task_fetch_articles(**context) -> None:
    url = f"{API_BASE_URL}/articles"
    logger.info(f"Mengambil artikel dari: {url}")

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    articles = payload.get("articles", [])
    session_id = payload.get("session_id", "unknown")
    scraped_at = payload.get("scraped_at", datetime.now().isoformat())

    logger.info(f"Berhasil mengambil {len(articles)} artikel dari session {session_id}")

    # Push ke XCom
    context["ti"].xcom_push(key="articles", value=articles)
    context["ti"].xcom_push(key="session_id", value=session_id)
    context["ti"].xcom_push(key="scraped_at", value=scraped_at)


def task_transform_articles(**context) -> None:
    ti = context["ti"]
    articles: list[dict] = ti.xcom_pull(key="articles", task_ids="fetch_articles")

    if not articles:
        logger.warning("Tidak ada artikel untuk ditransformasi.")
        ti.xcom_push(key="transformed_articles", value=[])
        return

    transformed = []
    seen_urls: set[str] = set()

    for raw in articles:
        try:
            # ── URL ──
            url = (raw.get("url") or "").strip()
            if not url or not url.startswith("http"):
                logger.debug(f"Skip artikel tanpa URL valid: {raw.get('title')}")
                continue

            if url in seen_urls:
                logger.debug(f"Skip duplikat URL: {url}")
                continue
            seen_urls.add(url)

            # ── Title ──
            title = (raw.get("title") or "").strip()
            if not title:
                logger.debug(f"Skip artikel tanpa judul: {url}")
                continue

            # ── Description ──
            description = (raw.get("description") or "").strip() or None

            # ── Author — bersihkan format "By..." ──
            author_raw = (raw.get("author") or "").strip()
            author = normalize_author(author_raw) if author_raw else None

            # ── Tanggal — pastikan format ISO 8601 ──
            scraped_at_raw = raw.get("scraped_at", "")
            scraped_at = normalize_datetime(scraped_at_raw)

            # ── Source ──
            source = (raw.get("source") or "Wired.com").strip()

            transformed.append({
                "title":       title,
                "url":         url,
                "description": description,
                "author":      author,
                "scraped_at":  scraped_at,
                "source":      source,
            })

        except Exception as exc:
            logger.warning(f"Gagal transformasi artikel '{raw.get('title')}': {exc}")
            continue

    logger.info(
        f"Transformasi selesai: {len(articles)} artikel input → "
        f"{len(transformed)} artikel valid"
    )
    ti.xcom_push(key="transformed_articles", value=transformed)


def normalize_author(raw: str) -> str:
    raw = raw.strip()
    # Hapus duplikasi "ByBy"
    raw = re.sub(r"^(By)+\s*", "By", raw, flags=re.IGNORECASE)
    if not raw.startswith("By"):
        raw = "By" + raw
    return raw


def normalize_datetime(raw: str) -> str:
    if not raw:
        return datetime.now().isoformat()

    # Sudah ISO 8601
    try:
        dt = datetime.fromisoformat(raw)
        return dt.isoformat()
    except ValueError:
        pass

    # Format umum lainnya
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a, %d %b %Y %H:%M:%S %z",
        "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue

    logger.warning(f"Tidak dapat parse tanggal '{raw}', gunakan waktu sekarang.")
    return datetime.now().isoformat()


def task_load_to_database(**context) -> None:
    ti = context["ti"]
    articles: list[dict] = ti.xcom_pull(
        key="transformed_articles", task_ids="transform_articles"
    )
    session_id: str = ti.xcom_pull(key="session_id", task_ids="fetch_articles")

    if not articles:
        logger.info("Tidak ada artikel untuk disimpan.")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cursor = conn.cursor()

    INSERT_SQL = """
        INSERT INTO wired_articles
            (session_id, title, url, description, author, scraped_at, source)
        VALUES
            (%(session_id)s, %(title)s, %(url)s, %(description)s,
             %(author)s, %(scraped_at)s, %(source)s)
        ON CONFLICT (url) DO UPDATE SET
            title       = EXCLUDED.title,
            description = COALESCE(EXCLUDED.description, wired_articles.description),
            author      = COALESCE(EXCLUDED.author,      wired_articles.author),
            scraped_at  = EXCLUDED.scraped_at,
            updated_at  = CURRENT_TIMESTAMP
    """

    rows = [
        {
            "session_id":   session_id,
            "title":        a["title"],
            "url":          a["url"],
            "description":  a["description"],
            "author":       a["author"],
            "scraped_at":   a["scraped_at"],
            "source":       a["source"],
        }
        for a in articles
    ]

    try:
        psycopg2.extras.execute_batch(cursor, INSERT_SQL, rows, page_size=100)
        conn.commit()
        logger.info(f"✓ {len(rows)} artikel berhasil di-upsert ke database (session: {session_id})")
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"Gagal menyimpan ke database: {exc}") from exc
    finally:
        cursor.close()
        conn.close()


def task_log_summary(**context) -> None:
    ti = context["ti"]
    articles: list[dict] = ti.xcom_pull(
        key="transformed_articles", task_ids="transform_articles"
    )
    session_id: str = ti.xcom_pull(key="session_id", task_ids="fetch_articles")
    scraped_at: str = ti.xcom_pull(key="scraped_at",  task_ids="fetch_articles")

    count = len(articles) if articles else 0

    logger.info("=" * 60)
    logger.info("  PIPELINE SUMMARY")
    logger.info(f"  Session ID  : {session_id}")
    logger.info(f"  Scraped At  : {scraped_at}")
    logger.info(f"  Articles    : {count}")
    logger.info(f"  Finished At : {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # Simpan summary ke tabel pipeline_runs
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pipeline_runs
                (session_id, scraped_at, articles_loaded, run_at, status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                articles_loaded = EXCLUDED.articles_loaded,
                run_at          = EXCLUDED.run_at,
                status          = EXCLUDED.status
            """,
            (session_id, scraped_at, count, datetime.now().isoformat(), "success"),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        logger.warning(f"Gagal menyimpan pipeline log: {exc}")


# ─── DAG Definition ───────────────────────────────────────────────────────────

with DAG(
    dag_id="wired_pipeline",
    description="Scrape Wired.com → API → Transform → PostgreSQL",
    default_args=DEFAULT_ARGS,
    schedule_interval="0 */1 * * *",   # Setiap 1 jam
    catchup=False,
    max_active_runs=1,
    tags=["wired", "scraping", "etl"],
    doc_md="""
## Wired Pipeline DAG

Pipeline ETL otomatis untuk mengambil artikel dari Wired.com.

### Alur:
1. **check_api** — Verifikasi FastAPI berjalan
2. **fetch_articles** — GET /articles dari FastAPI
3. **transform_articles** — Validasi & normalisasi data
4. **load_to_database** — Upsert ke PostgreSQL `wired_articles`
5. **log_summary** — Catat hasil ke `pipeline_runs`
""",
) as dag:

    start = EmptyOperator(task_id="start")

    check_api = PythonOperator(
        task_id="check_api_health",
        python_callable=task_check_api_health,
    )

    fetch = PythonOperator(
        task_id="fetch_articles",
        python_callable=task_fetch_articles,
    )

    transform = PythonOperator(
        task_id="transform_articles",
        python_callable=task_transform_articles,
    )

    load = PythonOperator(
        task_id="load_to_database",
        python_callable=task_load_to_database,
    )

    summary = PythonOperator(
        task_id="log_summary",
        python_callable=task_log_summary,
    )

    end = EmptyOperator(task_id="end")

    # ── Pipeline Flow ──
    start >> check_api >> fetch >> transform >> load >> summary >> end
