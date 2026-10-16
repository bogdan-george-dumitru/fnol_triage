"""SQLite adapter: business-level deduplication lookup.

Technical idempotency (the document hash) only catches the *exact same bytes*. It does
NOT catch the same loss arriving on two channels, or re-worded — those are different
bytes, different hash. This finds the *logical* duplicate by matching on the extracted
business keys (policy number + claim type + a loss-date window), and the pipeline
surfaces it as a flag for the handler.

It never merges or drops automatically: two notifications on the same policy can be two
genuine events, so the human decides.
"""
from __future__ import annotations

import sqlite3

from app.models import FnolExtraction
from app.triage import normalize_date


def _fnol_ref(doc_hash: str) -> str:
    return f"FNOL-{doc_hash[:8].upper()}"


def find_possible_duplicates(
    conn: sqlite3.Connection,
    extraction: FnolExtraction,
    lob: str | None,
    claim_type: str | None,
    exclude_doc_hash: str,
    window_days: int = 7,
) -> list[dict]:
    """Return already-seen documents that look like the same loss.

    Requires a policy number (the strong key); without it we don't guess.
    Matches same policy + LOB + claim type, with the loss date inside `window_days`.
    """
    policy = extraction.policy_number
    if not policy or not lob or not claim_type:
        return []

    base_date = normalize_date(extraction.event_or_loss_date) or normalize_date(extraction.reported_date)
    rows = conn.execute(
        """
        SELECT d.doc_hash, d.loss_date, d.received_at, (c.id IS NOT NULL) AS has_claim
        FROM documents d
        LEFT JOIN claims c ON c.doc_hash = d.doc_hash
        WHERE d.policy_number = ? AND d.line_of_business = ? AND d.claim_type = ?
          AND d.doc_hash <> ?
        """,
        (policy, lob, claim_type, exclude_doc_hash),
    ).fetchall()

    matches: list[dict] = []
    for r in rows:
        if base_date is not None:
            other = normalize_date(r["loss_date"])
            if other is not None and abs((other - base_date).days) > window_days:
                continue
        matches.append(
            {
                "claim_reference": _fnol_ref(r["doc_hash"]),
                "received_at": r["received_at"],
                "has_claim": bool(r["has_claim"]),
            }
        )
    return matches
