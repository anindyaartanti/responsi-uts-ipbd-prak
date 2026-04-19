# Wired Pipeline — Automated Data Pipeline

Pipeline ETL otomatis yang melakukan scraping artikel dari **Wired.com**, menyajikannya via **FastAPI**, mengorkestrasikan proses dengan **Apache Airflow DAG**, dan menyimpan data terstruktur ke **PostgreSQL**.

---

### Alur Pipeline:
1. **Scraper** → Selenium mengambil 50+ artikel dari Wired.com → simpan ke JSON
2. **FastAPI** → Membaca JSON dan menyajikan via `GET /articles`
3. **Airflow DAG** → Setiap 6 jam: panggil API → transformasi → simpan ke DB
4. **PostgreSQL** → Tabel `wired_articles` dengan indexing lengkap
5. **SQL Reporting** → Query analisis siap pakai di `sql/reporting_queries.sql`

---

## Struktur Proyek

```
wired-pipeline/
├── docker-compose.yml
├── .env.example
│
├── scraper/
│   ├── scraper.py
│   └── requirements.txt
│
├── api/
│   ├── main.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── airflow/
│   └── dags/
│       └── wired_pipeline_dag.py
│
├── init/
│   ├── init_databases.sh
│   └── init.sql
│
├── data/
│
└── sql/
    └── reporting_queries.sql
```

---

### 1. Clone & Setup

```bash
git clone <repo-url>
cd responsi-uts-ipbd
```

### 2. Jalankan Scraper

```bash
cd scraper
pip install -r requirements.txt
python scraper.py
```

### 3. Jalankan Docker Compose

```bash
# Build dan jalankan semua services
docker compose up -d --build

# Cek status
docker compose ps
```

Services yang berjalan:
| Service | URL | Keterangan |
|---------|-----|-----------|
| FastAPI | http://localhost:8000 | REST API |
| FastAPI Docs | http://localhost:8000/docs | Swagger UI |
| Airflow | http://localhost:8080 | Web UI (admin/admin) |
| PostgreSQL | localhost:5432 | Database |

### 4. Trigger DAG

**Via Airflow UI:**
1. Buka http://localhost:8080
2. Login: `admin` / `admin`
3. Aktifkan DAG `wired_pipeline`

### 5. Query Database

```bash
# Jalankan reporting queries
docker exec -i wired-postgres psql -U wired_user -d wired_pipeline < sql/reporting_queries.sql

# PowerShell
Get-Content sql/reporting_queries.sql | docker exec -i wired-postgres psql -U wired_user -d wired_pipeline
```

---

## API Endpoints

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `GET` | `/` | Info API & daftar endpoint |
| `GET` | `/health` | Health check |
| `GET` | `/articles` | Semua artikel (session terbaru) |
| `GET` | `/articles?limit=10` | Batasi jumlah artikel |
| `GET` | `/articles?author=John` | Filter berdasarkan penulis |
| `GET` | `/articles?search=AI` | Cari di judul/deskripsi |
| `GET` | `/articles/all` | Artikel dari semua sesi |
| `GET` | `/sessions` | Daftar semua sesi scraping |
| `GET` | `/articles/{session_id}` | Artikel per sesi |

---

## DAG Tasks

```
start
  └── check_api_health      Verifikasi FastAPI online
        └── fetch_articles  GET /articles dari API
              └── transform_articles   Validasi, normalisasi tanggal/author
                    └── load_to_database   Upsert ke PostgreSQL
                          └── log_summary   Catat hasil ke pipeline_runs
                                └── end
```
---

## Database Schema

### Tabel `wired_articles`

| Kolom | Tipe | Keterangan |
|-------|------|-----------|
| `id` | SERIAL | Primary key |
| `session_id` | VARCHAR(100) | ID sesi scraping |
| `title` | TEXT | Judul artikel |
| `url` | TEXT UNIQUE | URL artikel (unik) |
| `description` | TEXT | Deskripsi singkat |
| `author` | VARCHAR(255) | Penulis (format "By...") |
| `scraped_at` | TIMESTAMP | Waktu scraping |
| `source` | VARCHAR(100) | Sumber (Wired.com) |
| `inserted_at` | TIMESTAMP | Waktu insert ke DB |
| `updated_at` | TIMESTAMP | Waktu update terakhir |
