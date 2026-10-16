"""End-to-end triage: ingest result -> proposal.

Orchestrates extract -> classify -> deterministic triage, with the failure modes
the brief calls for:
  - extraction error / unreadable document -> 🔴 manual intake
  - classification failure -> fall back to the keyword baseline, forced to 🟡 amber

If a `RunMetrics` is passed, per-stage latency and LLM token usage are recorded
into it for observability (Stage 6).
"""
from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from app.errors import ExtractionError
from app.models import (
    Classification,
    FnolExtraction,
    IngestedDocument,
    Status,
    TriageProposal,
)
from app.observability import RunMetrics
from app.providers.base import LLMProvider
from app.triage import (
    apply_severity_floor,
    build_draft,
    build_policy_check,
    determine_status,
    evaluate_flags,
    missing_required_fields,
    queue_meta,
    route,
    score_claim_types,
    to_fired_flags,
)
from app.workflow.schema import WorkflowConfig

if TYPE_CHECKING:
    from app.persistence.base import TriageRepository


def _claim_reference(doc_hash: str) -> str:
    return f"FNOL-{doc_hash[:8].upper()}"


def _add_usage(provider: LLMProvider, metrics: RunMetrics | None) -> None:
    if metrics is None:
        return
    usage = getattr(provider, "last_usage", {}) or {}
    metrics.input_tokens += int(usage.get("input_tokens", 0))
    metrics.output_tokens += int(usage.get("output_tokens", 0))


def triage(
    document: IngestedDocument,
    content: bytes,
    provider: LLMProvider,
    config: WorkflowConfig,
    repo: TriageRepository | None = None,
    config_version: int | None = None,
    metrics: RunMetrics | None = None,
) -> TriageProposal:
    claim_ref = _claim_reference(document.doc_hash)
    start = perf_counter()

    def finalize(proposal: TriageProposal) -> TriageProposal:
        if metrics is not None:
            metrics.total_ms = (perf_counter() - start) * 1000
            metrics.status = proposal.status.value
            metrics.line_of_business = proposal.line_of_business
            metrics.claim_type = proposal.claim_type
            metrics.queue = proposal.queue
        return proposal

    def manual(extraction: FnolExtraction, reasons: list[str]) -> TriageProposal:
        label, sla = queue_meta(config, "manual_intake")
        return TriageProposal(
            doc_hash=document.doc_hash, claim_reference=claim_ref, config_version=config_version,
            extraction=extraction, classification=None, queue="manual_intake",
            queue_label=label, sla_hours=sla, status=Status.red, reasons=reasons,
            policy_check=build_policy_check(
                repo.get_policy(extraction.policy_number) if repo else None,
                extraction.policy_number,
            ),
        )

    # 1) Extract (schema-invalid after retry -> ExtractionError).
    t = perf_counter()
    try:
        extraction = provider.extract(document, content)
    except ExtractionError as e:
        if metrics is not None:
            metrics.extract_ms = (perf_counter() - t) * 1000
        _add_usage(provider, metrics)
        return finalize(manual(
            FnolExtraction(notes=str(e), overall_confidence=0.0, illegible_fields=["all"]),
            ["could not extract fields from the document (sent to manual intake)"],
        ))
    if metrics is not None:
        metrics.extract_ms = (perf_counter() - t) * 1000
    _add_usage(provider, metrics)

    # 2) Unreadable (e.g. mock baseline on an image/scan).
    if extraction.overall_confidence == 0.0 and "all" in extraction.illegible_fields:
        return finalize(manual(extraction, ["document could not be read (no OCR / illegible)"]))

    # 3) Classify, with a baseline fallback on failure.
    classify_failed = False
    t = perf_counter()
    try:
        classification = provider.classify(extraction, config)
        _add_usage(provider, metrics)
    except Exception:  # noqa: BLE001 — any classify failure -> baseline + amber
        from app.providers.mock import MockProvider

        classification = MockProvider(provider.settings).classify(extraction, config)
        classify_failed = True
    if metrics is not None:
        metrics.classify_ms = (perf_counter() - t) * 1000
        metrics.classify_failed = classify_failed

    # 4) Deterministic triage.
    t = perf_counter()
    lob = classification.line_of_business
    policy = repo.get_policy(extraction.policy_number) if repo else None
    fired = evaluate_flags(
        extraction, config, policy, lob, classification.claim_type,
        suggested_flags=set(classification.suggested_flags),
    )
    severity = apply_severity_floor(classification.severity, fired)
    queue = route(lob, classification.claim_type, severity, fired, config)
    queue_label, sla = queue_meta(config, queue)
    missing = missing_required_fields(extraction, config, lob)
    status, reasons = determine_status(
        extraction, classification, fired, policy, lob, missing, config
    )

    if classify_failed:
        reasons.append("classification fell back to the keyword baseline — please verify")
        if status == Status.green:
            status = Status.amber

    # A red (manual-intake) proposal always goes to the manual-intake desk, so
    # status and queue never disagree.
    if status == Status.red:
        queue = "manual_intake"
        queue_label, sla = queue_meta(config, queue)

    # Business deduplication: same loss on another channel / re-worded. Surfaced
    # as a flag for the handler — never auto-merged or dropped.
    possible_duplicates: list[str] = []
    if repo is not None:
        dups = repo.find_possible_duplicates(
            extraction, lob, classification.claim_type,
            document.doc_hash, config.thresholds.dedup_window_days,
        )
        if dups:
            possible_duplicates = [d["claim_reference"] for d in dups]
            reasons.append(
                "possible duplicate of " + ", ".join(possible_duplicates)
                + " — same policy, loss date and claim type"
            )
            if status == Status.green:
                status = Status.amber

    language = extraction.language if extraction.language in ("ro", "en") else "ro"
    scores = score_claim_types(
        " ".join(p for p in (extraction.description, extraction.peril_text) if p), config
    )
    alternatives = [ct for (_l, ct, sc) in scores if ct != classification.claim_type and sc > 0][:2]
    draft = (
        build_draft(extraction, config, lob, claim_ref, queue_label, sla)
        if status != Status.red
        else None
    )
    if metrics is not None:
        metrics.triage_ms = (perf_counter() - t) * 1000

    return finalize(TriageProposal(
        doc_hash=document.doc_hash, claim_reference=claim_ref, config_version=config_version,
        extraction=extraction, classification=classification, line_of_business=lob,
        claim_type=classification.claim_type, severity=severity, queue=queue,
        queue_label=queue_label, sla_hours=sla, status=status, reasons=reasons,
        alternatives=alternatives, flags=to_fired_flags(fired, language),
        policy_check=build_policy_check(policy, extraction.policy_number), draft=draft,
        possible_duplicates=possible_duplicates,
    ))
