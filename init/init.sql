CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- Full-text search
CREATE EXTENSION IF NOT EXISTS btree_gin;  -- GIN index support

-- Tabel utama: wired_articles

CREATE TABLE IF NOT EXISTS wired_articles (
    id            SERIAL          PRIMARY KEY,
    session_id    VARCHAR(100),
    title         TEXT            NOT NULL,
    url           TEXT            NOT NULL UNIQUE,
    description   TEXT,
    author        VARCHAR(255),
    scraped_at    TIMESTAMP,
    source        VARCHAR(100)    DEFAULT 'Wired.com',
    inserted_at   TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE  wired_articles            IS 'Artikel yang di-scrape dari Wired.com';
COMMENT ON COLUMN wired_articles.session_id IS 'ID sesi scraping unik per run';
COMMENT ON COLUMN wired_articles.title      IS 'Judul artikel';
COMMENT ON COLUMN wired_articles.url        IS 'URL lengkap artikel (UNIQUE)';
COMMENT ON COLUMN wired_articles.description IS 'Deskripsi singkat / deck artikel';
COMMENT ON COLUMN wired_articles.author     IS 'Nama penulis, format "By<NamaPenulis>"';
COMMENT ON COLUMN wired_articles.scraped_at IS 'Waktu artikel di-scrape';
COMMENT ON COLUMN wired_articles.inserted_at IS 'Waktu baris pertama kali di-insert';
COMMENT ON COLUMN wired_articles.updated_at  IS 'Waktu terakhir baris di-update';


-- Tabel log: pipeline_runs

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id               SERIAL       PRIMARY KEY,
    session_id       VARCHAR(100) UNIQUE,
    scraped_at       TIMESTAMP,
    articles_loaded  INTEGER      DEFAULT 0,
    run_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    status           VARCHAR(50)  DEFAULT 'success',
    notes            TEXT
);

COMMENT ON TABLE pipeline_runs IS 'Log setiap eksekusi pipeline ETL';


-- Indexes


-- Index untuk query berdasarkan waktu scraping
CREATE INDEX IF NOT EXISTS idx_articles_scraped_at
    ON wired_articles (scraped_at DESC);

-- Index untuk filter berdasarkan author
CREATE INDEX IF NOT EXISTS idx_articles_author
    ON wired_articles (author);

-- Index untuk filter berdasarkan session
CREATE INDEX IF NOT EXISTS idx_articles_session_id
    ON wired_articles (session_id);

-- GIN index untuk full-text search pada title dan description
CREATE INDEX IF NOT EXISTS idx_articles_title_fts
    ON wired_articles USING GIN (to_tsvector('english', title));

CREATE INDEX IF NOT EXISTS idx_articles_desc_fts
    ON wired_articles USING GIN (
        to_tsvector('english', COALESCE(description, ''))
    );

-- Trigram index untuk ILIKE / similarity search
CREATE INDEX IF NOT EXISTS idx_articles_title_trgm
    ON wired_articles USING GIN (title gin_trgm_ops);


-- Trigger

-- Trigger: auto-update updated_at

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_wired_articles_updated_at
    BEFORE UPDATE ON wired_articles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
