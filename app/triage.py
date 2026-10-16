"""The deterministic triage layer — code, not AI.

Given the model's extraction + classification and the business config, this module
decides what the business needs to be reliable: which flags fire, severity floors,
the routing queue, required-field completeness, policy verification, the per-FNOL
status, and the acknowledgment draft. None of this calls a model.
"""
from __future__ import annotations

from datetime import date, datetime

from app.models import (
    Classification,
    DraftAck,
    FiredFlag,
    FnolExtraction,
    PolicyCheck,
    Severity,
    Status,
)
from app.policy import Policy
from app.workflow.schema import FlagRule, WorkflowConfig

# Document-keyword map for the `missing_document` condition.
_DOCUMENT_KEYWORDS = {
    "death_certificate": ["certificat de deces", "certificat deces", "death certificate"],
}


# --- small utilities -------------------------------------------------------
def normalize_date(value: str | None) -> date | None:
    """Parse ISO / dd.mm.yyyy / dd/mm/yyyy (day-first, Romanian) into a date."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _blob(extraction: FnolExtraction) -> str:
    parts = [
        extraction.description,
        extraction.peril_text,
        extraction.event_type_hint,
        extraction.notes,
    ]
    return " ".join(p for p in parts if p).lower()


def score_claim_types(text: str, config: WorkflowConfig) -> list[tuple[str, str, int]]:
    """Keyword-score every (LOB, claim_type). Returns descending by score."""
    low = (text or "").lower()
    scored: list[tuple[str, str, int]] = []
    for lob in config.lines_of_business:
        for ct in lob.claim_types:
            score = sum(1 for kw in ct.keywords if kw.lower() in low)
            scored.append((lob.key, ct.key, score))
    scored.sort(key=lambda t: t[2], reverse=True)
    return scored


# --- flag evaluation -------------------------------------------------------
def _loss_date(extraction: FnolExtraction) -> date | None:
    return normalize_date(extraction.event_or_loss_date) or normalize_date(extraction.reported_date)


def _condition_fires(
    rule: FlagRule,
    extraction: FnolExtraction,
    config: WorkflowConfig,
    policy: Policy | None,
    lob: str | None,
) -> bool:
    cond = rule.condition
    if cond == "amount_over":
        amount = extraction.estimated_amount
        thr = config.thresholds.large_loss_amount.get(lob or "", None)
        return bool(amount and thr and amount >= thr)
    if cond in ("loss_within_days_of_inception", "event_within_days_of_inception"):
        if policy is None:
            return False
        inception = normalize_date(policy.inception_date)
        event = _loss_date(extraction)
        if inception is None or event is None:
            return False
        days_param = rule.params.get("days")
        window = int(days_param) if days_param else config.thresholds.contestability_days
        delta = (event - inception).days
        return 0 <= delta <= window
    if cond == "extraction_true":
        field = str(rule.params.get("field", ""))
        return getattr(extraction, field, None) is True
    if cond == "missing_document":
        doc = str(rule.params.get("document", ""))
        keywords = _DOCUMENT_KEYWORDS.get(doc, [doc])
        mentioned = " ".join(extraction.documents_mentioned).lower()
        return not any(kw.lower() in mentioned for kw in keywords)
    return False


def evaluate_flags(
    extraction: FnolExtraction,
    config: WorkflowConfig,
    policy: Policy | None,
    lob: str | None,
    claim_type: str | None = None,
    suggested_flags: set[str] | None = None,
) -> list[FlagRule]:
    """Return the FlagRules that fire for this FNOL.

    A flag fires on ANY of its triggers: a keyword match, a built-in condition, or
    (for an AI-predicate flag) the model having returned its key in `suggested_flags`.
    The applies_to / applies_to_claim_types gates apply to all trigger types.
    """
    blob = _blob(extraction)
    suggested = suggested_flags or set()
    fired: list[FlagRule] = []
    for rule in config.flag_rules:
        if rule.applies_to and lob not in rule.applies_to:
            continue
        if rule.applies_to_claim_types and claim_type not in rule.applies_to_claim_types:
            continue
        hit = False
        if rule.keywords and any(kw.lower() in blob for kw in rule.keywords):
            hit = True
        if not hit and rule.condition:
            hit = _condition_fires(rule, extraction, config, policy, lob)
        if not hit and rule.ai_predicate and rule.key in suggested:
            hit = True
        if hit:
            fired.append(rule)
    return fired


def to_fired_flags(fired: list[FlagRule], language: str) -> list[FiredFlag]:
    out: list[FiredFlag] = []
    for f in fired:
        msg = (f.message_ro if language == "ro" else f.message_en) or f.label
        out.append(FiredFlag(key=f.key, label=f.label, message=msg))
    return out


# --- severity + routing ----------------------------------------------------
def apply_severity_floor(base: Severity, fired: list[FlagRule]) -> Severity:
    best = base
    for f in fired:
        if f.min_severity and f.min_severity.rank > best.rank:
            best = f.min_severity
    return best


def route(
    lob: str | None,
    claim_type: str | None,
    severity: Severity,
    fired: list[FlagRule],
    config: WorkflowConfig,
) -> str:
    # 1) a flag may force a queue (highest priority wins) — e.g. SIU, CAT.
    forcing = [f for f in fired if f.force_queue]
    if forcing:
        return max(forcing, key=lambda f: f.force_queue_priority).force_queue  # type: ignore[return-value]
    # 2) otherwise first matching routing rule.
    fired_keys = {f.key for f in fired}
    for rule in config.routing_rules:
        if rule.line_of_business and rule.line_of_business != lob:
            continue
        if rule.claim_types and claim_type not in rule.claim_types:
            continue
        if rule.severities and severity not in rule.severities:
            continue
        if rule.any_flags and not (fired_keys & set(rule.any_flags)):
            continue
        return rule.queue
    return "manual_intake"


def queue_meta(config: WorkflowConfig, queue_key: str) -> tuple[str, int | None]:
    for q in config.queues:
        if q.key == queue_key:
            return q.label, q.sla_hours
    return queue_key, None


# --- required fields + policy check ---------------------------------------
def missing_required_fields(
    extraction: FnolExtraction, config: WorkflowConfig, lob: str | None
) -> list[str]:
    for item in config.lines_of_business:
        if item.key == lob:
            missing = []
            for field in item.required_fields:
                value = getattr(extraction, field, None)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing.append(field)
            return missing
    return []


def build_policy_check(policy: Policy | None, policy_number: str | None) -> PolicyCheck:
    if policy is None:
        return PolicyCheck(policy_number=policy_number, found=False)
    return PolicyCheck(
        policy_number=policy.policy_number,
        found=True,
        status=policy.status,
        product=policy.product,
        inception_date=policy.inception_date,
        sum_insured=policy.sum_insured,
        currency=policy.currency,
    )


# --- draft acknowledgment --------------------------------------------------
def build_draft(
    extraction: FnolExtraction,
    config: WorkflowConfig,
    lob: str | None,
    claim_reference: str,
    queue_label: str,
    sla_hours: int | None,
) -> DraftAck | None:
    language = extraction.language if extraction.language in ("ro", "en") else "ro"
    template = next(
        (t for t in config.templates if t.line_of_business == lob and t.language == language),
        None,
    )
    if template is None:
        return None
    values = {
        "claimant_name": extraction.claimant_name or ("stimată doamnă/domn" if language == "ro" else "Sir/Madam"),
        "policy_number": extraction.policy_number or (extraction.loan_reference or "-"),
        "claim_reference": claim_reference,
        "queue_label": queue_label,
        "sla_hours": sla_hours if sla_hours is not None else "-",
    }
    return DraftAck(
        template_key=template.key,
        language=language,
        subject=_safe_format(template.subject, values),
        body=_safe_format(template.body, values),
    )


def _safe_format(text: str, values: dict) -> str:
    out = text
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# --- status ---------------------------------------------------------------
def determine_status(
    extraction: FnolExtraction,
    classification: Classification,
    fired: list[FlagRule],
    policy: Policy | None,
    lob: str | None,
    missing: list[str],
    config: WorkflowConfig,
) -> tuple[Status, list[str]]:
    th = config.thresholds
    reasons: list[str] = []

    identifier_missing = not extraction.policy_number and not extraction.loan_reference
    if identifier_missing:
        reasons.append("no policy or loan reference found")
    for m in missing:
        reasons.append(f"missing required field: {m}")

    if policy is None and not identifier_missing:
        reasons.append("policy not found in the policy master — verify manually")
    elif policy is not None:
        if policy.status != "in_force":
            reasons.append(f"policy is {policy.status}, not in force")
        if lob and policy.product != lob:
            reasons.append("classified line of business differs from the policy product")

    review_flags = [f for f in fired if f.requires_review]
    for f in review_flags:
        reasons.append(f.label)

    low_confidence = classification.confidence < th.review_min_confidence
    if low_confidence:
        reasons.append(f"low classification confidence ({classification.confidence:.0%})")

    # Decide.
    if identifier_missing or low_confidence or (policy is not None and policy.status == "cancelled"):
        return Status.red, reasons

    clean = (
        not reasons
        and classification.confidence >= th.auto_ready_min_confidence
        and not missing
        and policy is not None
        and policy.status == "in_force"
    )
    if clean:
        return Status.green, reasons
    return Status.amber, reasons
