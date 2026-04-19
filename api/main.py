import json
import os
import glob
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Konfigurasi ──────────────────────────────────────────────────────────────

DATA_DIR = os.getenv("DATA_DIR", "/app/data")

app = FastAPI(
    title="Wired Pipeline API",
    description="API untuk mengakses data artikel yang di-scrape dari Wired.com",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Pydantic Models ──────────────────────────────────────────────────────────

class Article(BaseModel):
    title: str
    url: str
    description: Optional[str] = None
    author: Optional[str] = None
    scraped_at: str
    source: str = "Wired.com"


class Session(BaseModel):
    session_id: str
    timestamp: str
    articles_count: int
    articles: list[Article]


class ArticlesResponse(BaseModel):
    total: int
    session_id: Optional[str] = None
    scraped_at: Optional[str] = None
    articles: list[Article]


# ─── Helper ───────────────────────────────────────────────────────────────────

def load_latest_data() -> list[dict]:
    # Coba file 'latest' dulu
    latest_file = os.path.join(DATA_DIR, "wired_latest.json")
    if os.path.exists(latest_file):
        with open(latest_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # Fallback: cari file JSON terbaru berdasarkan nama
    pattern = os.path.join(DATA_DIR, "wired_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return []

    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_sessions() -> list[dict]:
    pattern = os.path.join(DATA_DIR, "wired_2*.json")  # Exclude 'latest'
    files = sorted(glob.glob(pattern), reverse=True)
    all_sessions = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                all_sessions.extend(data)
        except Exception:
            continue
    return all_sessions


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return {
        "service": "Wired Pipeline API",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "GET /articles": "Ambil semua artikel dari session terbaru",
            "GET /articles/all": "Ambil artikel dari semua session",
            "GET /sessions": "Daftar semua session scraping",
            "GET /articles/{session_id}": "Artikel berdasarkan session ID",
            "GET /health": "Health check",
        },
    }


@app.get("/health", tags=["Info"])
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/articles", response_model=ArticlesResponse, tags=["Articles"])
def get_articles(
    limit: int = Query(default=None, ge=1, le=1000, description="Batasi jumlah artikel"),
    author: Optional[str] = Query(default=None, description="Filter berdasarkan author"),
    search: Optional[str] = Query(default=None, description="Cari di judul/deskripsi"),
):
    data = load_latest_data()

    if not data:
        raise HTTPException(
            status_code=404,
            detail="Belum ada data. Jalankan scraper terlebih dahulu.",
        )

    session = data[0]
    articles = session.get("articles", [])

    # Filter
    if author:
        articles = [a for a in articles if a.get("author") and author.lower() in a["author"].lower()]

    if search:
        articles = [
            a for a in articles
            if search.lower() in (a.get("title") or "").lower()
            or search.lower() in (a.get("description") or "").lower()
        ]

    if limit:
        articles = articles[:limit]

    return ArticlesResponse(
        total=len(articles),
        session_id=session.get("session_id"),
        scraped_at=session.get("timestamp"),
        articles=articles,
    )


@app.get("/articles/all", response_model=ArticlesResponse, tags=["Articles"])
def get_all_articles(
    limit: int = Query(default=200, ge=1, le=5000, description="Batasi jumlah artikel"),
):
    all_sessions = load_all_sessions()

    if not all_sessions:
        # Fallback ke latest
        return get_articles(limit=limit)

    all_articles = []
    seen_urls: set[str] = set()

    for session in all_sessions:
        for article in session.get("articles", []):
            url = article.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                all_articles.append(article)

    if limit:
        all_articles = all_articles[:limit]

    return ArticlesResponse(
        total=len(all_articles),
        articles=all_articles,
    )


@app.get("/sessions", tags=["Sessions"])
def get_sessions():
    pattern = os.path.join(DATA_DIR, "wired_2*.json")
    files = sorted(glob.glob(pattern), reverse=True)

    sessions = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if data:
                    s = data[0]
                    sessions.append({
                        "session_id": s.get("session_id"),
                        "timestamp": s.get("timestamp"),
                        "articles_count": s.get("articles_count"),
                        "file": os.path.basename(f),
                    })
        except Exception:
            continue

    return {"total_sessions": len(sessions), "sessions": sessions}


@app.get("/articles/{session_id}", response_model=ArticlesResponse, tags=["Articles"])
def get_articles_by_session(session_id: str):
    all_sessions = load_all_sessions()

    for session in all_sessions:
        if session.get("session_id") == session_id:
            return ArticlesResponse(
                total=len(session.get("articles", [])),
                session_id=session_id,
                scraped_at=session.get("timestamp"),
                articles=session.get("articles", []),
            )

    raise HTTPException(status_code=404, detail=f"Session '{session_id}' tidak ditemukan.")
