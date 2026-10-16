"""SQLite adapter: versioned persistence for the workflow config.

Every save creates a new immutable version; exactly one version is active at a time.
Rollback = activate an older version. This gives the business team a safety net: a bad
config change is one click to undo, and the history is auditable.

`VersionMeta` and `ConfigValidationError` are the port's vocabulary (`persistence.base`).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.persistence.base import ConfigValidationError, VersionMeta
from app.workflow.schema import WorkflowConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_version(
    conn: sqlite3.Connection,
    config: WorkflowConfig,
    author: str,
    label: str,
    activate: bool = True,
) -> int:
    """Validate and persist a new config version. Returns the new version number."""
    errors = config.validate_references()
    if errors:
        raise ConfigValidationError(errors)

    cur = conn.execute(
        "INSERT INTO config_versions (created_at, author, label, is_active, config_json) "
        "VALUES (?, ?, ?, 0, ?)",
        (_now(), author, label, config.model_dump_json()),
    )
    version = int(cur.lastrowid)
    if activate:
        _activate(conn, version)
    conn.commit()
    return version


def _activate(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("UPDATE config_versions SET is_active = 0 WHERE is_active = 1")
    conn.execute("UPDATE config_versions SET is_active = 1 WHERE version = ?", (version,))


def activate(conn: sqlite3.Connection, version: int) -> None:
    """Make `version` the active config (used for rollback)."""
    row = conn.execute(
        "SELECT 1 FROM config_versions WHERE version = ?", (version,)
    ).fetchone()
    if row is None:
        raise KeyError(f"config version {version} does not exist")
    _activate(conn, version)
    conn.commit()


def active_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT version FROM config_versions WHERE is_active = 1"
    ).fetchone()
    return int(row["version"]) if row else None


def get_config(conn: sqlite3.Connection, version: int) -> WorkflowConfig:
    row = conn.execute(
        "SELECT config_json FROM config_versions WHERE version = ?", (version,)
    ).fetchone()
    if row is None:
        raise KeyError(f"config version {version} does not exist")
    return WorkflowConfig.model_validate_json(row["config_json"])


def active_config(conn: sqlite3.Connection) -> WorkflowConfig | None:
    v = active_version(conn)
    return get_config(conn, v) if v is not None else None


def list_versions(conn: sqlite3.Connection) -> list[VersionMeta]:
    cur = conn.execute(
        "SELECT version, created_at, author, label, is_active "
        "FROM config_versions ORDER BY version DESC"
    )
    return [
        VersionMeta(
            version=r["version"],
            created_at=r["created_at"],
            author=r["author"],
            label=r["label"],
            is_active=bool(r["is_active"]),
        )
        for r in cur.fetchall()
    ]
