"""Persistence ports — the storage seam.

The deterministic triage pipeline (`app.pipeline`) depends on `TriageRepository`,
never on `sqlite3`. So the database is an **adapter behind an interface**, not a hard
dependency of the domain. `Repository` is the wider port the application/API layer
uses. The only adapter today is the SQLite one in `app.persistence.sqlite`; a Postgres
adapter would implement the same Protocols without touching the domain or the API.

These are `typing.Protocol`s (structural typing) on purpose: an adapter conforms by
*shape*, so no adapter has to import or subclass anything here. Same dependency-
inversion idea as the model provider (`app.providers.base`), applied to storage.

The small record types defined here (`StoredDocument`, `VersionMeta`) and
`ConfigValidationError` are the **vocabulary of the port** — plain domain objects that
cross the boundary, so adapters never leak a driver type (e.g. a `sqlite3.Row`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.models import Claim, FnolExtraction, IngestedDocument, TriageProposal
    from app.observability import RunMetrics
    from app.policy import Policy
    from app.workflow.schema import WorkflowConfig


@dataclass(frozen=True)
class StoredDocument:
    """A stored loss notification, as the port hands it back (not a DB row)."""

    doc_hash: str
    filename: str
    media_type: str
    source_kind: str
    ingestion_path: str
    text: str | None
    raw_path: str | None


@dataclass
class VersionMeta:
    """Metadata for one saved config version."""

    version: int
    created_at: str
    author: str
    label: str
    is_active: bool


class ConfigValidationError(ValueError):
    """Raised when a config fails referential-integrity checks before saving."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class TriageRepository(Protocol):
    """The narrow READ port the deterministic triage pipeline needs.

    Kept deliberately small: the domain only looks up a policy and checks for
    business duplicates. Everything else lives on the wider `Repository`.
    """

    def get_policy(self, policy_number: str | None) -> Policy | None: ...

    def find_possible_duplicates(
        self,
        extraction: FnolExtraction,
        lob: str | None,
        claim_type: str | None,
        exclude_doc_hash: str,
        window_days: int = 7,
    ) -> list[dict]: ...


class Repository(TriageRepository, Protocol):
    """The full persistence port used by the application / API layer."""

    # --- documents + stored proposals ---
    def save_proposal(
        self, document: IngestedDocument, content: bytes, proposal: TriageProposal
    ) -> None: ...
    def get_proposal(self, doc_hash: str) -> TriageProposal | None: ...
    def get_document(self, doc_hash: str) -> StoredDocument | None: ...
    def list_proposals(self) -> list[dict]: ...
    def mark_reviewed(self, doc_hash: str) -> None: ...

    # --- claims (idempotent by document hash) ---
    def get_claim(self, doc_hash: str) -> Claim | None: ...
    def create_claim(
        self, proposal: TriageProposal, final: dict, approved_by: str | None
    ) -> tuple[Claim, bool]: ...

    # --- per-run telemetry / metrics ---
    def record_run(self, metrics: RunMetrics) -> None: ...
    def compute_metrics(self) -> dict: ...

    # --- versioned workflow config ---
    def active_config(self) -> WorkflowConfig | None: ...
    def active_version(self) -> int | None: ...
    def get_config(self, version: int) -> WorkflowConfig: ...
    def list_versions(self) -> list[VersionMeta]: ...
    def save_version(self, config: WorkflowConfig, author: str, label: str) -> int: ...
    def activate(self, version: int) -> None: ...

    # --- policy master (simulated; seeded on setup) ---
    def replace_policies(self, policies: list[Policy]) -> int: ...

    # --- lifecycle ---
    def close(self) -> None: ...
