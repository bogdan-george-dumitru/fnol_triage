"""The workflow configuration contract.

This is the artifact the business team owns and maintains. The code in Stages 2-5
consumes it; the config UI edits it; the eval/preview runs it. Field names here are
stable — later stages depend on them.

`validate_references()` enforces internal consistency (e.g. a routing rule can't
point at a queue that doesn't exist). The config UI runs it before every save so a
non-technical user cannot persist a broken workflow.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import Severity

# Built-in deterministic conditions a flag rule may reference. These are
# implemented in code (Stage 3); the business selects and parameterises them but
# cannot invent new ones without engineering (a deliberate guard-rail).
BUILTIN_CONDITIONS = {
    "amount_over",  # params: {} -> uses thresholds.large_loss_amount[LOB]
    "loss_within_days_of_inception",  # params: {"days": N}
    "event_within_days_of_inception",  # params: {"days": N}
    "missing_document",  # params: {"document": "death_certificate"}
    "extraction_true",  # params: {"field": "bodily_injury"} -> trust the structured field
}


class ClaimTypeDef(BaseModel):
    key: str
    label_ro: str
    label_en: str
    keywords: list[str] = Field(default_factory=list)  # hints for mock baseline + prompt


class LineOfBusiness(BaseModel):
    key: str
    label_ro: str
    label_en: str
    claim_types: list[ClaimTypeDef]
    required_fields: list[str] = Field(default_factory=list)  # extraction fields that must be present


class Queue(BaseModel):
    key: str
    label: str
    sla_hours: int
    description: str = ""


class FlagRule(BaseModel):
    """A deterministic signal the code raises, with its effect on triage.

    A flag fires if its `keywords` match the text OR its `condition` evaluates
    true. Effects: raise severity to a floor, force a queue (e.g. SIU), and/or
    force at least a human review (amber).
    """

    key: str
    label: str
    applies_to: list[str] = Field(default_factory=list)  # LOB keys; empty = all
    applies_to_claim_types: list[str] = Field(default_factory=list)  # claim-type keys; empty = all

    # Triggers (any match fires the flag)
    keywords: list[str] = Field(default_factory=list)
    condition: str | None = None  # one of BUILTIN_CONDITIONS (deterministic)
    params: dict[str, float | int | str] = Field(default_factory=dict)
    # A natural-language predicate the model evaluates. Lets a business user ADD a
    # semantic flag by describing it in words — the model returns its key when it
    # applies; the EFFECT below stays deterministic. Only the openai provider can
    # evaluate it (the mock baseline cannot), so it never fires on mock.
    ai_predicate: str | None = None

    # Effects
    min_severity: Severity | None = None
    force_queue: str | None = None
    force_queue_priority: int = 0  # higher wins when several flags force a queue
    requires_review: bool = True  # at least amber
    message_ro: str = ""
    message_en: str = ""


class RoutingRule(BaseModel):
    """Ordered, first-match-wins mapping to a queue (applied after flags)."""

    key: str
    description: str = ""
    line_of_business: str | None = None
    claim_types: list[str] = Field(default_factory=list)  # empty = any
    severities: list[Severity] = Field(default_factory=list)  # empty = any
    any_flags: list[str] = Field(default_factory=list)  # match if any present
    queue: str


class Template(BaseModel):
    """Acknowledgment template. `body` uses {placeholders} filled from extraction."""

    key: str
    line_of_business: str
    language: str  # "ro" | "en"
    subject: str
    body: str


class FewShotExample(BaseModel):
    """A business-authored example injected into the classification prompt."""

    text: str
    line_of_business: str
    claim_type: str
    severity: Severity
    note: str = ""


class Thresholds(BaseModel):
    auto_ready_min_confidence: float = 0.80  # >= -> eligible for green
    review_min_confidence: float = 0.55  # < -> red / manual

    # Ingest text-layer heuristic (Stage 2)
    text_layer_min_chars_per_page: int = 25
    text_layer_max_garbage_ratio: float = 0.15

    # Domain thresholds
    large_loss_amount: dict[str, float] = Field(default_factory=dict)  # per LOB key
    contestability_days: int = 730  # Life/CPI contestability window
    dedup_window_days: int = 7  # business dedup: match loss dates within this window


class WorkflowConfig(BaseModel):
    lines_of_business: list[LineOfBusiness]
    queues: list[Queue]
    flag_rules: list[FlagRule] = Field(default_factory=list)
    routing_rules: list[RoutingRule] = Field(default_factory=list)
    templates: list[Template] = Field(default_factory=list)
    few_shot_examples: list[FewShotExample] = Field(default_factory=list)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    # --- convenience lookups ------------------------------------------------
    def lob_keys(self) -> set[str]:
        return {lob.key for lob in self.lines_of_business}

    def queue_keys(self) -> set[str]:
        return {q.key for q in self.queues}

    def claim_type_keys(self, lob: str) -> set[str]:
        for item in self.lines_of_business:
            if item.key == lob:
                return {ct.key for ct in item.claim_types}
        return set()

    def all_claim_type_keys(self) -> set[str]:
        keys: set[str] = set()
        for lob in self.lines_of_business:
            keys |= {ct.key for ct in lob.claim_types}
        return keys

    # --- referential integrity ---------------------------------------------
    def validate_references(self) -> list[str]:
        """Return a list of human-readable problems; empty means the config is sound."""
        errors: list[str] = []
        lobs = self.lob_keys()
        queues = self.queue_keys()

        for r in self.routing_rules:
            if r.line_of_business and r.line_of_business not in lobs:
                errors.append(f"routing rule '{r.key}' references unknown LOB '{r.line_of_business}'")
            if r.queue not in queues:
                errors.append(f"routing rule '{r.key}' references unknown queue '{r.queue}'")
            if r.line_of_business:
                valid = self.claim_type_keys(r.line_of_business)
                for ct in r.claim_types:
                    if ct not in valid:
                        errors.append(
                            f"routing rule '{r.key}' references unknown claim type "
                            f"'{ct}' for LOB '{r.line_of_business}'"
                        )

        for f in self.flag_rules:
            if f.condition and f.condition not in BUILTIN_CONDITIONS:
                errors.append(f"flag '{f.key}' uses unknown condition '{f.condition}'")
            if not f.keywords and not f.condition and not f.ai_predicate:
                errors.append(f"flag '{f.key}' has no trigger (keywords, condition or ai_predicate)")
            if f.force_queue and f.force_queue not in queues:
                errors.append(f"flag '{f.key}' forces unknown queue '{f.force_queue}'")
            for lob in f.applies_to:
                if lob not in lobs:
                    errors.append(f"flag '{f.key}' applies_to unknown LOB '{lob}'")
            for ct in f.applies_to_claim_types:
                if ct not in self.all_claim_type_keys():
                    errors.append(f"flag '{f.key}' applies_to unknown claim type '{ct}'")

        flag_keys = {f.key for f in self.flag_rules}
        for r in self.routing_rules:
            for fk in r.any_flags:
                if fk not in flag_keys:
                    errors.append(f"routing rule '{r.key}' references unknown flag '{fk}'")

        for t in self.templates:
            if t.line_of_business not in lobs:
                errors.append(f"template '{t.key}' references unknown LOB '{t.line_of_business}'")
            if t.language not in ("ro", "en"):
                errors.append(f"template '{t.key}' has unsupported language '{t.language}'")

        for i, ex in enumerate(self.few_shot_examples):
            if ex.line_of_business not in lobs:
                errors.append(f"few-shot example #{i} references unknown LOB '{ex.line_of_business}'")
            elif ex.claim_type not in self.claim_type_keys(ex.line_of_business):
                errors.append(
                    f"few-shot example #{i} references unknown claim type '{ex.claim_type}'"
                )

        for lob_key, _amount in self.thresholds.large_loss_amount.items():
            if lob_key not in lobs:
                errors.append(f"thresholds.large_loss_amount references unknown LOB '{lob_key}'")

        return errors
