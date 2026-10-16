"""Mock / baseline provider.

Regex/keyword extraction + (Stage 3) keyword-scored classification. Needs no API
key, so the app, tests and eval always run, and it is the non-LLM baseline in the
eval. It has NO OCR, so image/handwritten documents resolve to manual intake by
design — the honest gap that quantifies the vision model's value.
"""
from __future__ import annotations

import re

from app.models import Classification, FnolExtraction, IngestedDocument, IngestionPath
from app.workflow.schema import WorkflowConfig

from .base import LLMProvider

_RO_DIACRITICS = set("ăâîșțĂÂÎȘȚ")
_RO_HINTS = ("poliță", "polita", "daună", "dauna", "asigurat", "deces", "vă ", "și ")

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4})\b")
_POLICY_RE = re.compile(
    r"(?:poli[țtţ][aă]|policy)\s*(?:nr\.?|no\.?|number|#)?\s*[:#]?\s*([A-Z]{0,4}[-/]?\d[\w\-/]{3,})",
    re.IGNORECASE,
)
_LOAN_RE = re.compile(
    r"(?:credit|loan|contract(?:\s+de\s+credit)?)\s*(?:nr\.?|no\.?|#)?\s*[:#]?\s*([A-Z]{0,4}[-/]?\d[\w\-/]{3,})",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(\d[\d.,\s]{2,})\s*(RON|lei|EUR|€|USD|\$)", re.IGNORECASE
)
_INJURY = ("rănit", "ranit", "vătăma", "vatama", "accidentat", "injur", "hurt", "wounded")
_THIRD_PARTY = ("vecin", "terț", "tert", "third party", "neighbour", "neighbor")

_LABEL_NAME_RE = re.compile(
    r"(?:nume|name|asigurat|insured|claimant)\s*[:#]\s*([A-ZȘȚĂÂÎ][\w .'\-ȘȚĂÂÎșțăâî]{2,40})",
    re.IGNORECASE,
)


def _detect_language(text: str) -> str:
    if any(ch in _RO_DIACRITICS for ch in text):
        return "ro"
    low = text.lower()
    if any(h in low for h in _RO_HINTS):
        return "ro"
    return "en"


def _parse_amount(raw: str) -> float | None:
    cleaned = raw.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_fields_from_text(text: str) -> FnolExtraction:
    """Deterministic regex/keyword extraction — the baseline."""
    low = text.lower()
    found = 0

    policy = _POLICY_RE.search(text)
    loan = _LOAN_RE.search(text)
    date = _DATE_RE.search(text)
    amount_m = _AMOUNT_RE.search(text)
    name_m = _LABEL_NAME_RE.search(text)

    policy_number = policy.group(1) if policy else None
    loan_reference = loan.group(1) if loan else None
    event_date = date.group(1) if date else None
    amount = _parse_amount(amount_m.group(1)) if amount_m else None
    currency = amount_m.group(2).upper() if amount_m else None

    for v in (policy_number, event_date, amount, name_m):
        if v:
            found += 1

    # Baseline confidence: modest, grows a little with how many anchors we found.
    confidence = min(0.60, 0.30 + 0.08 * found) if text.strip() else 0.0

    description = re.sub(r"\s+", " ", text).strip()[:1000] or None

    return FnolExtraction(
        language=_detect_language(text),
        policy_number=policy_number,
        loan_reference=loan_reference,
        claim_reference=None,
        claimant_name=name_m.group(1).strip() if name_m else None,
        event_or_loss_date=event_date,
        description=description,
        estimated_amount=amount,
        currency=currency,
        bodily_injury=any(k in low for k in _INJURY) or None,
        third_party_involved=any(k in low for k in _THIRD_PARTY) or None,
        overall_confidence=confidence,
        notes="mock/regex baseline extraction",
    )


class MockProvider(LLMProvider):
    name = "mock"

    def extract(self, document: IngestedDocument, content: bytes) -> FnolExtraction:
        # No OCR: anything that needs vision goes to manual intake.
        if document.ingestion_path == IngestionPath.vision or not document.text:
            return FnolExtraction(
                overall_confidence=0.0,
                illegible_fields=["all"],
                notes="mock baseline has no OCR; image/scanned document -> manual intake",
            )
        return extract_fields_from_text(document.text)

    def classify(self, extraction: FnolExtraction, config: WorkflowConfig) -> Classification:
        from app.triage import score_claim_types

        text = " ".join(
            p for p in (extraction.description, extraction.peril_text, extraction.event_type_hint) if p
        )
        scored = score_claim_types(text, config)
        best_lob, best_ct, best_score = scored[0] if scored else ("property", "", 0)

        # If nothing matched, fall back to the extraction's LOB hint if usable.
        if best_score == 0 and extraction.line_of_business_hint:
            hint = extraction.line_of_business_hint.lower()
            for lob in config.lines_of_business:
                if lob.key in hint or lob.label_ro.lower() in hint or lob.label_en.lower() in hint:
                    best_lob = lob.key
                    break

        severity = self._severity(best_ct, extraction, best_lob, config)
        confidence = min(0.75, 0.40 + 0.10 * best_score) if best_score else 0.30

        return Classification(
            line_of_business=best_lob,
            claim_type=best_ct,
            severity=severity,
            confidence=confidence,
            suggested_flags=[],
            rationale="keyword-score baseline",
        )

    @staticmethod
    def _severity(claim_type: str, extraction: FnolExtraction, lob: str, config: WorkflowConfig):
        from app.models import Severity

        if claim_type in {"death", "total_permanent_disability"} or extraction.bodily_injury:
            return Severity.complex
        threshold = config.thresholds.large_loss_amount.get(lob)
        if extraction.estimated_amount and threshold and extraction.estimated_amount >= threshold:
            return Severity.complex
        if claim_type == "glass" and (extraction.estimated_amount or 0) < 2000:
            return Severity.fast_track
        return Severity.standard
