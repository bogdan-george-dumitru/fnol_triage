"""Persistence: ports (`base`) + the SQLite adapter (`sqlite`).

Application code imports the ports and the adapter factory from here; it never reaches
into `app.persistence.sqlite.*` submodules.
"""
from __future__ import annotations

from app.persistence.base import (
    ConfigValidationError,
    Repository,
    StoredDocument,
    TriageRepository,
    VersionMeta,
)
from app.persistence.sqlite import SqliteRepository, open_repository

__all__ = [
    "Repository",
    "TriageRepository",
    "StoredDocument",
    "VersionMeta",
    "ConfigValidationError",
    "SqliteRepository",
    "open_repository",
]
