"""SQLite adapter: the simulated claims system (`claims` table).

Stands in for the insurer's core platform (Guidewire, custom API, ...). A real
deployment would POST the approved claim there; here we record it in the local
`claims` table. Creation is **idempotent by document hash**: approving (or
re-uploading) the same document twice never creates two claims.

Also captures what the human changed vs. the AI proposal, which feeds the
edit/override-rate metric.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.models import Claim, TriageProposal

# Fields a human can override on the review screen.
_OVERRIDABLE = ("line_of_business", "claim_type", "severity", "queue", "status")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        id=row["id"], doc_hash=row["doc_hash"], claim_reference=row["claim_reference"],
        created_at=row["created_at"], line_of_business=row["line_of_business"],
        claim_type=row["claim_type"], severity=row["severity"], status=row["status"],
        queue=row["queue"], approved_by=row["approved_by"], edited=bool(row["edited"]),
        edits=json.loads(row["edits_json"]) if row["edits_json"] else [],
    )


def get_claim(conn: sqlite3.Connection, doc_hash: str) -> Claim | None:
    row = conn.execute("SELECT * FROM claims WHERE doc_hash = ?", (doc_hash,)).fetchone()
    return _row_to_claim(row) if row else None


def _ai_values(proposal: TriageProposal) -> dict:
    return {
        "line_of_business": proposal.line_of_business,
        "claim_type": proposal.claim_type,
        "severity": proposal.severity.value if proposal.severity else None,
        "queue": proposal.queue,
        "status": proposal.status.value,
    }


def create_claim(
    conn: sqlite3.Connection,
    proposal: TriageProposal,
    final: dict,
    approved_by: str | None,
) -> tuple[Claim, bool]:
    """Create a claim from an approved proposal. Idempotent by doc_hash.

    Returns (claim, created). If a claim already exists for this document, returns
    the existing one with created=False — the same document never books twice.
    """
    existing = get_claim(conn, proposal.doc_hash)
    if existing is not None:
        return existing, False

    ai = _ai_values(proposal)
    merged = {k: (final.get(k) if final.get(k) is not None else ai.get(k)) for k in _OVERRIDABLE}
    edits = [k for k in _OVERRIDABLE if merged[k] != ai.get(k)]

    approved_proposal = proposal.model_copy(
        update={
            "line_of_business": merged["line_of_business"],
            "claim_type": merged["claim_type"],
            "queue": merged["queue"],
        }
    )

    cur = conn.execute(
        """
        INSERT INTO claims (doc_hash, created_at, claim_reference, line_of_business,
            claim_type, severity, status, queue, config_version, ai_proposal_json,
            approved_proposal_json, edited, edits_json, approved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            proposal.doc_hash, _now(), proposal.claim_reference, merged["line_of_business"],
            merged["claim_type"], merged["severity"], merged["status"], merged["queue"],
            proposal.config_version, proposal.model_dump_json(),
            approved_proposal.model_dump_json(), int(bool(edits)), json.dumps(edits),
            approved_by,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM claims WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_claim(row), True
