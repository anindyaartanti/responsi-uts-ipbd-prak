#!/bin/bash

set -e

# ── Buat user dan database ──────────────────────────────────
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL

    CREATE USER airflow_user WITH PASSWORD 'airflow_pass';
    CREATE DATABASE airflow_db OWNER airflow_user;
    GRANT ALL PRIVILEGES ON DATABASE airflow_db TO airflow_user;

    CREATE USER wired_user WITH PASSWORD 'wired_pass';
    CREATE DATABASE wired_pipeline OWNER wired_user;
    GRANT ALL PRIVILEGES ON DATABASE wired_pipeline TO wired_user;

EOSQL

echo "Database airflow_db dan wired_pipeline berhasil dibuat."

# ── Jalankan schema SQL di database  ─────────────────────────
psql -v ON_ERROR_STOP=1 \
     --username "wired_user" \
     --dbname   "wired_pipeline" \
     --file     "/docker-entrypoint-initdb.d/01_init.sql"

echo "Schema wired_pipeline berhasil dibuat."