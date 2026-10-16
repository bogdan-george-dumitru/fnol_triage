"""The SQLite adapter: `SqliteRepository` implements the persistence ports.

It binds one `sqlite3.Connection` to the sibling SQL modules in this package. Those
modules own the SQL; this class is the single object callers hold, so they depend on
the port (`app.persistence.base.Repository`), not on `sqlite3`.

To port to Postgres you add a `postgres` package implementing the same Protocols —
the domain, the API, the scripts and the tests do not change.
"""
from __future__ import annotations

import sqlite3

from app.persistence.sqlite import claims as _claims
from app.persistence.sqlite import config as _config
from app.persistence.sqlite import dedup as _dedup
from app.persistence.sqlite import documents as _documents
from app.persistence.sqlite import policies as _policies
from app.persistence.sqlite import runs as _runs
from app.persistence.sqlite.schema import get_connection, init_db


class SqliteRepository:
    """SQLite-backed implementation of `app.persistence.base.Repository`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- TriageRepository: the domain's reads ---
    def get_policy(self, policy_number):
        return _policies.get_policy(self.conn, policy_number)

    def find_possible_duplicates(
        self, extraction, lob, claim_type, exclude_doc_hash, window_days=7
    ):
        return _dedup.find_possible_duplicates(
            self.conn, extraction, lob, claim_type, exclude_doc_hash, window_days
        )

    # --- documents + stored proposals ---
    def save_proposal(self, document, content, proposal):
        _documents.save_proposal(self.conn, document, content, proposal)

    def get_proposal(self, doc_hash):
        return _documents.get_proposal(self.conn, doc_hash)

    def get_document(self, doc_hash):
        return _documents.get_document(self.conn, doc_hash)

    def list_proposals(self):
        return _documents.list_proposals(self.conn)

    def mark_reviewed(self, doc_hash):
        _documents.mark_reviewed(self.conn, doc_hash)

    # --- claims ---
    def get_claim(self, doc_hash):
        return _claims.get_claim(self.conn, doc_hash)

    def create_claim(self, proposal, final, approved_by):
        return _claims.create_claim(self.conn, proposal, final, approved_by)

    # --- runs / metrics ---
    def record_run(self, metrics):
        _runs.record_run(self.conn, metrics)

    def compute_metrics(self):
        return _runs.compute_metrics(self.conn)

    # --- versioned config ---
    def active_config(self):
        return _config.active_config(self.conn)

    def active_version(self):
        return _config.active_version(self.conn)

    def get_config(self, version):
        return _config.get_config(self.conn, version)

    def list_versions(self):
        return _config.list_versions(self.conn)

    def save_version(self, config, author, label):
        return _config.save_version(self.conn, config, author=author, label=label)

    def activate(self, version):
        _config.activate(self.conn, version)

    # --- policy master (seeded on setup) ---
    def replace_policies(self, policies):
        return _policies.replace_policies(self.conn, policies)

    # --- lifecycle ---
    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def open_repository(db_path: str | None = None, *, init: bool = False) -> SqliteRepository:
    """Open a SQLite-backed repository. `init=True` also creates the schema."""
    conn = get_connection(db_path)
    if init:
        init_db(conn)
    return SqliteRepository(conn)
