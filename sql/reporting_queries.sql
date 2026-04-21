-- ── Query 1 ──────────────────────────────────────────────────
-- Judul artikel dan nama author yang sudah dibersihkan dari "By"

SELECT
    LEFT(title, 60) AS title,
    REGEXP_REPLACE(author, '^By\s*', '', 'gi') AS author
FROM wired_articles
ORDER BY scraped_at DESC;


-- ── Query 2 ──────────────────────────────────────────────────
-- 3 penulis yang paling sering muncul

SELECT
    REGEXP_REPLACE(author, '^By\s*', '', 'gi') AS author,
    COUNT(*) AS total_artikel
FROM wired_articles
WHERE author IS NOT NULL
GROUP BY author
ORDER BY total_artikel DESC
LIMIT 3;


-- ── Query 3 ──────────────────────────────────────────────────
-- Artikel yang mengandung kata kunci "AI", "Climate", atau "Security"
-- pada judul atau deskripsi

SELECT
    LEFT(title, 60) AS title,
    LEFT(REGEXP_REPLACE(author, '^By\s*', '', 'gi'), 30) AS author,
    LEFT(description, 30) AS description
FROM wired_articles
WHERE
    title       ~* 'AI|Climate|Security'
    OR description ~* 'AI|Climate|Security'
ORDER BY scraped_at DESC
LIMIT 10;