"""Config preview: recompute the deterministic triage for the labeled cases under
a given config, and diff two configs. Free and instant (no model calls)."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from app.config import Settings
from app.models import Classification, FnolExtraction, IngestedDocument, IngestionPath, SourceKind
from app.pipeline import triage
from app.providers.base import LLMProvider
from app.workflow.schema import WorkflowConfig

if TYPE_CHECKING:
    from app.persistence.base import TriageRepository

_COMPARE_KEYS = ("status", "queue", "severity", "claim_type")


class _FixedProvider(LLMProvider):
    """Returns a fixed extraction + classification so only the config varies."""

    name = "fixed"

    def __init__(self, extraction: FnolExtraction, classification: Classification) -> None:
        super().__init__(Settings(llm_provider="mock"))
        self._e = extraction
        self._c = classification

    def extract(self, document, content):
        return self._e

    def classify(self, extraction, config):
        return self._c


def _synth_doc(name: str) -> IngestedDocument:
    return IngestedDocument(
        doc_hash=hashlib.sha256(name.encode()).hexdigest(),
        filename=name, media_type="text/plain", source_kind=SourceKind.text,
        size_bytes=0, received_at="", ingestion_path=IngestionPath.text, text="x",
    )


def run_case(repo: TriageRepository, config: WorkflowConfig, case) -> dict:
    proposal = triage(
        _synth_doc(case.name), b"", _FixedProvider(case.extraction, case.classification),
        config, repo=repo,
    )
    return {
        "name": case.name,
        "status": proposal.status.value,
        "queue": proposal.queue,
        "queue_label": proposal.queue_label,
        "line_of_business": proposal.line_of_business,
        "claim_type": proposal.claim_type,
        "severity": proposal.severity.value if proposal.severity else None,
        "flags": [f.key for f in proposal.flags],
    }


def run_cases(repo: TriageRepository, config: WorkflowConfig, cases) -> list[dict]:
    return [run_case(repo, config, c) for c in cases]


def _counts(results: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for r in results:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


def diff(active: list[dict], proposed: list[dict], cases) -> dict:
    rows = []
    changed = 0
    for a, p, c in zip(active, proposed, cases):
        fields = [k for k in _COMPARE_KEYS if a[k] != p[k]]
        if fields:
            changed += 1
        rows.append({
            "name": c.name, "note": c.note,
            "expected_status": c.expected_status, "expected_queue": c.expected_queue,
            "active": a, "proposed": p, "changed": fields,
        })
    return {
        "rows": rows,
        "summary": {
            "changed_count": changed,
            "active_status": _counts(active, "status"),
            "proposed_status": _counts(proposed, "status"),
            "active_queue": _counts(active, "queue"),
            "proposed_queue": _counts(proposed, "queue"),
        },
    }
