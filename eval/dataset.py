"""Labeled FNOL cases with fixed extraction + classification.

Used by:
  - the config PREVIEW (Stage 5): recompute the deterministic triage under a
    proposed config and see which cases flip — free and instant, because
    extraction/classification are held fixed.
  - the EVAL (Stage 7): compare against the expected labels.

Holding extraction + classification fixed isolates what the business edits
(routing rules, flags, thresholds, queues). It does NOT re-simulate the model's
classification, so taxonomy/prompt edits are not reflected here — stated plainly
so the preview is not over-sold.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Classification, FnolExtraction, Severity


@dataclass
class Case:
    name: str
    extraction: FnolExtraction
    classification: Classification
    expected_status: str
    expected_queue: str
    expected_flags: list[str] = field(default_factory=list)
    note: str = ""


def _ext(**kw) -> FnolExtraction:
    kw.setdefault("overall_confidence", 0.9)
    return FnolExtraction(**kw)


def _cls(lob: str, ct: str, sev: Severity, conf: float = 0.9) -> Classification:
    return Classification(line_of_business=lob, claim_type=ct, severity=sev, confidence=conf)


def build_cases() -> list[Case]:
    return [
        Case(
            name="water_damage_standard",
            extraction=_ext(policy_number="PROP-2024-558120", event_or_loss_date="2025-10-06",
                            loss_location="Str. Lalelelor 12", description="țeavă spartă, apartament inundat",
                            estimated_amount=18500.0, currency="RON", language="ro"),
            classification=_cls("property", "water_damage", Severity.standard, 0.92),
            expected_status="green", expected_queue="property_standard",
            note="Clean, in-appetite property claim.",
        ),
        Case(
            name="fire_with_injury",
            extraction=_ext(policy_number="PROP-2024-331050", event_or_loss_date="2025-10-05",
                            loss_location="Str. Zorilor 4", description="incendiu, arsuri la mână",
                            bodily_injury=True, estimated_amount=42000.0, currency="RON", language="ro"),
            classification=_cls("property", "fire", Severity.standard),
            expected_status="amber", expected_queue="property_complex", expected_flags=["bodily_injury"],
            note="Injury floors severity to complex and forces review.",
        ),
        Case(
            name="storm_catastrophe",
            extraction=_ext(policy_number="PROP-2024-558120", event_or_loss_date="2025-10-07",
                            loss_location="Str. Teilor 9", description="furtună puternică, grindină, acoperiș avariat",
                            estimated_amount=9000.0, currency="RON", language="ro"),
            classification=_cls("property", "storm_hail", Severity.standard),
            expected_status="green", expected_queue="cat_unit", expected_flags=["catastrophe"],
            note="Weather event -> CAT unit (advisory, no review required).",
        ),
        Case(
            name="fraud_near_inception",
            extraction=_ext(policy_number="PROP-2024-778310", event_or_loss_date="2025-10-05",
                            loss_location="Str. Narciselor 2", description="țeavă spartă, apartament inundat",
                            estimated_amount=15000.0, currency="RON", language="ro"),
            classification=_cls("property", "water_damage", Severity.standard),
            expected_status="amber", expected_queue="siu", expected_flags=["fraud_near_inception"],
            note="Loss 15 days after inception -> SIU.",
        ),
        Case(
            name="death_within_contestability",
            extraction=_ext(policy_number="CPI-2023-900341", insured_name="Gheorghe Marin",
                            event_or_loss_date="2023-08-01", description="deces asigurat",
                            documents_mentioned=["certificat de deces"], language="ro"),
            classification=_cls("life_cpi", "death", Severity.complex),
            expected_status="amber", expected_queue="siu", expected_flags=["contestability"],
            note="Death inside the 730-day window -> SIU / underwriting.",
        ),
        Case(
            name="death_normal",
            extraction=_ext(policy_number="CPI-2023-900341", insured_name="Gheorghe Marin",
                            event_or_loss_date="2025-10-02", description="deces asigurat",
                            documents_mentioned=["certificat de deces"], language="ro"),
            classification=_cls("life_cpi", "death", Severity.complex),
            expected_status="green", expected_queue="life_death_claims",
            note="Death outside contestability, certificate present.",
        ),
        Case(
            name="unemployment",
            extraction=_ext(policy_number="CPI-2025-114977", insured_name="Andrei Popescu",
                            event_or_loss_date="2025-09-30", description="concediere, șomaj involuntar",
                            documents_mentioned=["adeverință de la angajator"], language="en"),
            classification=_cls("life_cpi", "involuntary_unemployment", Severity.standard),
            expected_status="green", expected_queue="life_unemployment",
        ),
        Case(
            name="missing_policy",
            extraction=_ext(event_or_loss_date="2025-10-04", loss_location="Str. Plopilor 7",
                            description="s-a inundat baia", language="ro"),
            classification=_cls("property", "water_damage", Severity.standard),
            expected_status="red", expected_queue="manual_intake",
            note="No policy/loan reference -> manual intake.",
        ),
        Case(
            name="lapsed_policy",
            extraction=_ext(policy_number="PROP-2022-100200", event_or_loss_date="2025-10-01",
                            loss_location="Str. Castanilor 3", description="incendiu minor",
                            estimated_amount=5000.0, currency="RON", language="ro"),
            classification=_cls("property", "fire", Severity.standard),
            expected_status="amber", expected_queue="property_standard",
            note="Policy not in force -> amber for verification.",
        ),
        Case(
            name="large_loss",
            extraction=_ext(policy_number="PROP-2024-331050", event_or_loss_date="2025-10-03",
                            loss_location="Str. Salciei 11", description="incendiu de proporții",
                            estimated_amount=150000.0, currency="RON", language="ro"),
            classification=_cls("property", "fire", Severity.standard),
            expected_status="amber", expected_queue="property_complex", expected_flags=["large_loss"],
            note="Above large-loss threshold -> complex.",
        ),
    ]
