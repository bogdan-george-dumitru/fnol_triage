from __future__ import annotations

from datetime import date

from app.models import Classification, FnolExtraction, Severity, Status
from app.policy import Policy
from app.triage import (
    apply_severity_floor,
    build_draft,
    determine_status,
    evaluate_flags,
    missing_required_fields,
    normalize_date,
    route,
    score_claim_types,
)
from app.workflow.seed import build_starter_config

CFG = build_starter_config()


def _policy(**kw) -> Policy:
    base = dict(
        policy_number="PROP-2024-558120", product="property", holder_name="X",
        inception_date="2024-03-15", status="in_force", sum_insured=350000.0,
    )
    base.update(kw)
    return Policy(**base)


def test_normalize_date_formats() -> None:
    assert normalize_date("2025-10-06") == date(2025, 10, 6)
    assert normalize_date("06.10.2025") == date(2025, 10, 6)
    assert normalize_date("6/10/2025") == date(2025, 10, 6)
    assert normalize_date("garbage") is None
    assert normalize_date(None) is None


def test_score_claim_types_picks_water_damage() -> None:
    scored = score_claim_types("s-a spart o țeavă și s-a inundat apartamentul", CFG)
    assert scored[0][1] == "water_damage"


def test_catastrophe_scoped_to_weather_claim_types() -> None:
    # 'inundație' keyword present, but a water_damage claim must NOT get CAT.
    ext = FnolExtraction(description="daună inundație în apartament", language="ro")
    fired_water = {f.key for f in evaluate_flags(ext, CFG, _policy(), "property", "water_damage")}
    assert "catastrophe" not in fired_water
    # A storm_hail claim with the same wording does get CAT.
    fired_storm = {f.key for f in evaluate_flags(ext, CFG, _policy(), "property", "storm_hail")}
    assert "catastrophe" in fired_storm
    # Morphology: the genitive "furtunii" must still match the "furtun" stem.
    ext2 = FnolExtraction(description="în timpul furtunii a căzut un copac pe acoperiș", language="ro")
    assert "catastrophe" in {f.key for f in evaluate_flags(ext2, CFG, _policy(), "property", "storm_hail")}


def test_contestability_only_for_death_within_window() -> None:
    pol = _policy(policy_number="CPI-2023-900341", product="life_cpi", inception_date="2023-05-01")
    ext = FnolExtraction(description="deces asigurat", event_or_loss_date="2024-01-01")
    death_flags = {f.key for f in evaluate_flags(ext, CFG, pol, "life_cpi", "death")}
    assert "contestability" in death_flags
    # Same policy/date but an unemployment claim must NOT trigger contestability.
    unemp_flags = {f.key for f in evaluate_flags(ext, CFG, pol, "life_cpi", "involuntary_unemployment")}
    assert "contestability" not in unemp_flags


def test_death_outside_contestability_does_not_fire() -> None:
    pol = _policy(policy_number="CPI-2023-900341", product="life_cpi", inception_date="2023-05-01")
    ext = FnolExtraction(description="deces", event_or_loss_date="2025-10-02")  # ~888 days later
    flags = {f.key for f in evaluate_flags(ext, CFG, pol, "life_cpi", "death")}
    assert "contestability" not in flags


def test_fraud_near_inception_forces_siu() -> None:
    pol = _policy(inception_date="2025-09-20")
    ext = FnolExtraction(description="daună", event_or_loss_date="2025-10-08")  # 18 days
    fired = evaluate_flags(ext, CFG, pol, "property", "water_damage")
    assert "fraud_near_inception" in {f.key for f in fired}
    assert route("property", "water_damage", Severity.standard, fired, CFG) == "siu"


def test_bodily_injury_driven_by_structured_field_not_keywords() -> None:
    # Fires on the structured field even when the narrative says "arsuri", not "rănit".
    injured = FnolExtraction(description="arsuri la mână, îngrijiri medicale", bodily_injury=True)
    assert "bodily_injury" in {f.key for f in evaluate_flags(injured, CFG, _policy(), "property", "fire")}
    # Does NOT fire on the negated narrative "nu sunt răniți" when the field is False.
    not_injured = FnolExtraction(description="nu sunt răniți, doar pagube materiale", bodily_injury=False)
    assert "bodily_injury" not in {f.key for f in evaluate_flags(not_injured, CFG, _policy(), "property", "storm_hail")}


def test_ai_predicate_flag_fires_only_on_suggested_key() -> None:
    ext = FnolExtraction(description="incendiu în bucătărie", language="ro")
    # suspected_arson (property/fire) fires only when the model suggests its key.
    none = {f.key for f in evaluate_flags(ext, CFG, _policy(), "property", "fire", suggested_flags=set())}
    assert "suspected_arson" not in none
    yes = {f.key for f in evaluate_flags(ext, CFG, _policy(), "property", "fire", suggested_flags={"suspected_arson"})}
    assert "suspected_arson" in yes
    # gating still applies: wrong claim type -> no fire even if suggested
    wrong = {f.key for f in evaluate_flags(ext, CFG, _policy(), "property", "water_damage", suggested_flags={"suspected_arson"})}
    assert "suspected_arson" not in wrong


def test_starter_config_with_ai_flags_validates() -> None:
    assert build_starter_config().validate_references() == []


def test_large_loss_floor_and_routing() -> None:
    ext = FnolExtraction(description="incendiu mare", estimated_amount=120000.0)
    fired = evaluate_flags(ext, CFG, _policy(), "property", "fire")
    assert "large_loss" in {f.key for f in fired}
    assert apply_severity_floor(Severity.standard, fired) == Severity.complex
    assert route("property", "fire", Severity.complex, fired, CFG) == "property_complex"


def test_routing_rules_without_flags() -> None:
    assert route("property", "glass", Severity.fast_track, [], CFG) == "property_fast_track"
    assert route("property", "water_damage", Severity.standard, [], CFG) == "property_standard"
    assert route("life_cpi", "death", Severity.complex, [], CFG) == "life_death_claims"
    assert route("life_cpi", "involuntary_unemployment", Severity.standard, [], CFG) == "life_unemployment"


def test_missing_required_fields() -> None:
    ext = FnolExtraction(policy_number="PROP-1", description="x")  # property needs date + location too
    missing = missing_required_fields(ext, CFG, "property")
    assert "event_or_loss_date" in missing and "loss_location" in missing


def test_build_draft_fills_placeholders() -> None:
    ext = FnolExtraction(language="ro", claimant_name="Maria", policy_number="PROP-1")
    draft = build_draft(ext, CFG, "property", "FNOL-ABCD1234", "Property - Standard", 48)
    assert draft is not None
    assert "Maria" in draft.body and "FNOL-ABCD1234" in draft.body and "48" in draft.body
    assert "{" not in draft.body  # all placeholders filled


def test_status_green_when_clean_and_confident() -> None:
    ext = FnolExtraction(
        policy_number="PROP-2024-558120", event_or_loss_date="2025-10-06",
        loss_location="Str. X", description="daună de apă", language="ro",
        overall_confidence=0.95,
    )
    cls = Classification(line_of_business="property", claim_type="water_damage",
                         severity=Severity.standard, confidence=0.92)
    status, reasons = determine_status(ext, cls, [], _policy(), "property", [], CFG)
    assert status == Status.green and reasons == []


def test_status_red_when_no_identifier() -> None:
    ext = FnolExtraction(description="ceva", language="ro", overall_confidence=0.9)
    cls = Classification(line_of_business="property", claim_type="water_damage",
                         severity=Severity.standard, confidence=0.9)
    status, reasons = determine_status(ext, cls, [], None, "property", ["policy_number"], CFG)
    assert status == Status.red
    assert any("policy or loan" in r for r in reasons)
