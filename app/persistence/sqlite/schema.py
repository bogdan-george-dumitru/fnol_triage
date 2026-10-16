"""SQLite connection + schema (the adapter's infrastructure).

Plain stdlib `sqlite3` (no ORM) keeps the dependency surface small. All tables are
defined up front so no migrations are needed:
  - config_versions : versioned business workflow config
  - documents        : ingested loss notifications + stored proposal
  - runs             : per-document telemetry for /metrics
  - policies         : simulated policy master
  - claims           : booked claims, idempotent by document hash
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_versions (
    version     INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    author      TEXT NOT NULL,
    label       TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_hash        TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    source_kind     TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    received_at     TEXT NOT NULL,
    ingestion_path  TEXT NOT NULL,
    text            TEXT,
    num_pages       INTEGER,
    raw_path        TEXT,
    config_version  INTEGER,
    extraction_json TEXT,
    proposal_json   TEXT,
    status          TEXT,
    queue           TEXT,
    reviewed        INTEGER NOT NULL DEFAULT 0,
    -- denormalised keys for business deduplication lookups
    policy_number    TEXT,
    loss_date        TEXT,
    line_of_business TEXT,
    claim_type       TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id       TEXT NOT NULL,
    doc_hash         TEXT,
    created_at       TEXT NOT NULL,
    provider         TEXT,
    ingestion_path   TEXT,
    extract_ms       REAL,
    classify_ms      REAL,
    triage_ms        REAL,
    total_ms         REAL,
    input_tokens     INTEGER DEFAULT 0,
    output_tokens    INTEGER DEFAULT 0,
    cost_usd         REAL DEFAULT 0,
    status           TEXT,
    line_of_business TEXT,
    claim_type       TEXT,
    queue            TEXT,
    classify_failed  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS policies (
    policy_number  TEXT PRIMARY KEY,
    product        TEXT NOT NULL,          -- property / life_cpi
    holder_name    TEXT NOT NULL,
    inception_date TEXT NOT NULL,          -- ISO date
    status         TEXT NOT NULL,          -- in_force / lapsed / cancelled
    sum_insured    REAL NOT NULL,
    currency       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_hash               TEXT NOT NULL UNIQUE,    -- idempotency: one claim per document
    created_at             TEXT NOT NULL,
    claim_reference        TEXT NOT NULL,
    line_of_business       TEXT,                    -- final (approved) values
    claim_type             TEXT,
    severity               TEXT,
    status                 TEXT,
    queue                  TEXT,
    config_version         INTEGER,
    ai_proposal_json       TEXT NOT NULL,           -- original AI proposal
    approved_proposal_json TEXT NOT NULL,           -- what the human approved
    edited                 INTEGER NOT NULL DEFAULT 0,
    edits_json             TEXT,
    approved_by            TEXT,
    FOREIGN KEY (doc_hash) REFERENCES documents (doc_hash)
);
"""


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with row access by column name."""
    path = db_path or get_settings().db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they do not exist."""
    conn.executescript(SCHEMA)
    conn.commit()
