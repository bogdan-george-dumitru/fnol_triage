"""SQLite adapter: ingested documents + their triage proposals (`documents` table).

Proposals are stored (pending) until a handler approves them (-> a claim). Raw bytes
are saved under the uploads dir so the review screen can show the original (image/PDF)
beside the proposal.

`get_document` returns a `StoredDocument` (a port record), never a `sqlite3.Row`, so
the driver type does not leak across the boundary.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import get_settings
from app.models import IngestedDocument, TriageProposal
from app.persistence.base import StoredDocument


def save_raw(doc_hash: str, filename: str, data: bytes) -> str:
    uploads = Path(get_settings().uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix
    path = uploads / f"{doc_hash}{suffix}"
    path.write_bytes(data)
    return str(path)


def save_proposal(
    conn: sqlite3.Connection,
    document: IngestedDocument,
    content: bytes,
    proposal: TriageProposal,
) -> None:
    raw_path = save_raw(document.doc_hash, document.filename, content)
    ex = proposal.extraction
    loss_date = ex.event_or_loss_date or ex.reported_date
    conn.execute(
        """
        INSERT INTO documents (doc_hash, filename, media_type, source_kind, size_bytes,
            received_at, ingestion_path, text, num_pages, raw_path, config_version,
            extraction_json, proposal_json, status, queue, reviewed,
            policy_number, loss_date, line_of_business, claim_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        ON CONFLICT(doc_hash) DO UPDATE SET
            proposal_json=excluded.proposal_json, status=excluded.status,
            queue=excluded.queue, extraction_json=excluded.extraction_json,
            config_version=excluded.config_version, policy_number=excluded.policy_number,
            loss_date=excluded.loss_date, line_of_business=excluded.line_of_business,
            claim_type=excluded.claim_type
        """,
        (
            document.doc_hash, document.filename, document.media_type,
            document.source_kind.value, document.size_bytes, document.received_at,
            document.ingestion_path.value, document.text, document.num_pages, raw_path,
            proposal.config_version, proposal.extraction.model_dump_json(),
            proposal.model_dump_json(), proposal.status.value, proposal.queue,
            ex.policy_number, loss_date, proposal.line_of_business, proposal.claim_type,
        ),
    )
    conn.commit()


def get_proposal(conn: sqlite3.Connection, doc_hash: str) -> TriageProposal | None:
    row = conn.execute(
        "SELECT proposal_json FROM documents WHERE doc_hash = ?", (doc_hash,)
    ).fetchone()
    if row is None or row["proposal_json"] is None:
        return None
    return TriageProposal.model_validate_json(row["proposal_json"])


def get_document(conn: sqlite3.Connection, doc_hash: str) -> StoredDocument | None:
    row = conn.execute(
        "SELECT doc_hash, filename, media_type, source_kind, ingestion_path, text, raw_path "
        "FROM documents WHERE doc_hash = ?",
        (doc_hash,),
    ).fetchone()
    if row is None:
        return None
    return StoredDocument(
        doc_hash=row["doc_hash"],
        filename=row["filename"],
        media_type=row["media_type"],
        source_kind=row["source_kind"],
        ingestion_path=row["ingestion_path"],
        text=row["text"],
        raw_path=row["raw_path"],
    )


def list_proposals(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.doc_hash, d.filename, d.source_kind, d.ingestion_path, d.status,
               d.queue, d.received_at, d.proposal_json,
               (c.id IS NOT NULL) AS has_claim
        FROM documents d
        LEFT JOIN claims c ON c.doc_hash = d.doc_hash
        ORDER BY d.received_at DESC
        """
    ).fetchall()
    out = []
    for r in rows:
        proposal = json.loads(r["proposal_json"]) if r["proposal_json"] else {}
        out.append(
            {
                "doc_hash": r["doc_hash"],
                "filename": r["filename"],
                "source_kind": r["source_kind"],
                "ingestion_path": r["ingestion_path"],
                "status": r["status"],
                "queue": r["queue"],
                "queue_label": proposal.get("queue_label"),
                "line_of_business": proposal.get("line_of_business"),
                "claim_type": proposal.get("claim_type"),
                "claim_reference": proposal.get("claim_reference"),
                "received_at": r["received_at"],
                "has_claim": bool(r["has_claim"]),
            }
        )
    return out


def mark_reviewed(conn: sqlite3.Connection, doc_hash: str) -> None:
    conn.execute("UPDATE documents SET reviewed = 1 WHERE doc_hash = ?", (doc_hash,))
    conn.commit()
