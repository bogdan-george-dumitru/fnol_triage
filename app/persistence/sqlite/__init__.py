"""SQLite adapter for the persistence ports.

All SQLite-specific code lives in this package:
  `schema`    connection + DDL          `documents`  documents + proposals
  `claims`    booked claims             `policies`   policy master
  `dedup`     business-dedup lookup      `runs`       telemetry + /metrics
  `config`    versioned workflow config  `repository` the `SqliteRepository` facade

Nothing outside the adapter imports these submodules except the adapter-level tests;
application code depends on `app.persistence.base.Repository` and constructs the adapter
with `open_repository`.
"""
from __future__ import annotations

from app.persistence.sqlite.repository import SqliteRepository, open_repository
from app.persistence.sqlite.schema import get_connection, init_db

__all__ = ["SqliteRepository", "open_repository", "get_connection", "init_db"]
