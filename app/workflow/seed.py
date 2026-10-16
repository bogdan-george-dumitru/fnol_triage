"""A realistic starter workflow config for a Romanian personal-lines insurer.

Two lines of business: Home/Property and Life - Credit Protection Insurance (CPI).
This is the config the business team starts from and then maintains. It is static
(deterministic), so it is reproducible and reviewable.
"""
from __future__ import annotations

from app.models import Severity

from .schema import (
    ClaimTypeDef,
    FewShotExample,
    FlagRule,
    LineOfBusiness,
    Queue,
    RoutingRule,
    Template,
    Thresholds,
    WorkflowConfig,
)


def _property_lob() -> LineOfBusiness:
    return LineOfBusiness(
        key="property",
        label_ro="Locuință / Bunuri",
        label_en="Home / Property",
        required_fields=["policy_number", "event_or_loss_date", "loss_location", "description"],
        claim_types=[
            ClaimTypeDef(key="water_damage", label_ro="Daună de apă", label_en="Water damage",
                         keywords=["apă", "țeavă", "teava", "inundat", "scurgere", "water", "pipe", "leak", "flood"]),
            ClaimTypeDef(key="fire", label_ro="Incendiu", label_en="Fire",
                         keywords=["incendiu", "foc", "ars", "fum", "fire", "smoke", "burn"]),
            ClaimTypeDef(key="storm_hail", label_ro="Furtună / Grindină", label_en="Storm / Hail",
                         keywords=["furtună", "furtuna", "grindină", "grindina", "vânt", "storm", "hail", "wind"]),
            ClaimTypeDef(key="theft_burglary", label_ro="Furt / Spargere", label_en="Theft / Burglary",
                         keywords=["furt", "spargere", "jaf", "efracție", "theft", "burglary", "stolen", "break-in"]),
            ClaimTypeDef(key="glass", label_ro="Geam spart", label_en="Glass breakage",
                         keywords=["geam", "sticlă", "sticla", "fereastră", "glass", "window"]),
            ClaimTypeDef(key="electrical", label_ro="Daună electrică", label_en="Electrical damage",
                         keywords=["electric", "supratensiune", "scurtcircuit", "tensiune", "power surge", "short circuit"]),
            ClaimTypeDef(key="flood_natural", label_ro="Inundație (naturală)", label_en="Natural flood",
                         keywords=["inundație", "inundatie", "revărsare", "viitură", "flooding", "overflow"]),
            ClaimTypeDef(key="liability_third_party", label_ro="Răspundere față de terți", label_en="Third-party liability",
                         keywords=["vecin", "terț", "tert", "răspundere", "neighbour", "neighbor", "third party", "liability"]),
        ],
    )


def _life_cpi_lob() -> LineOfBusiness:
    return LineOfBusiness(
        key="life_cpi",
        label_ro="Viață - Asigurare de Protecție a Creditului",
        label_en="Life - Credit Protection Insurance",
        required_fields=["insured_name", "event_or_loss_date", "description"],
        claim_types=[
            ClaimTypeDef(key="death", label_ro="Deces", label_en="Death",
                         keywords=["deces", "decedat", "deceda", "moarte", "death", "deceased", "passed away"]),
            ClaimTypeDef(key="total_permanent_disability", label_ro="Invaliditate permanentă totală",
                         label_en="Total permanent disability",
                         keywords=["invaliditate", "invalid", "handicap permanent", "disability", "disabled"]),
            ClaimTypeDef(key="temporary_incapacity", label_ro="Incapacitate temporară de muncă",
                         label_en="Temporary incapacity",
                         keywords=["incapacitate", "concediu medical", "boală", "accidentat", "sick leave", "incapacity"]),
            ClaimTypeDef(key="involuntary_unemployment", label_ro="Șomaj involuntar",
                         label_en="Involuntary unemployment",
                         keywords=["șomaj", "somaj", "concediere", "disponibilizare", "unemployment", "laid off", "redundancy"]),
        ],
    )


def _queues() -> list[Queue]:
    return [
        Queue(key="property_fast_track", label="Property - Fast Track", sla_hours=24,
              description="Low-value, clear-cause property claims."),
        Queue(key="property_standard", label="Property - Standard", sla_hours=48,
              description="Standard property claims."),
        Queue(key="property_complex", label="Property - Complex / Large Loss", sla_hours=72,
              description="High-value or complex property claims."),
        Queue(key="cat_unit", label="Catastrophe Unit", sla_hours=72,
              description="Storm/flood events handled as catastrophe surges."),
        Queue(key="siu", label="Special Investigations (SIU)", sla_hours=120,
              description="Potential-fraud and contestability reviews."),
        Queue(key="life_death_claims", label="Life - Death Claims", sla_hours=72,
              description="CPI death claims; documentation-heavy."),
        Queue(key="life_disability", label="Life - Disability", sla_hours=72,
              description="CPI permanent/temporary disability claims."),
        Queue(key="life_unemployment", label="Life - Unemployment", sla_hours=48,
              description="CPI involuntary-unemployment claims."),
        Queue(key="manual_intake", label="Manual Intake", sla_hours=24,
              description="Fallback for unreadable or incomplete notifications."),
    ]


def _flag_rules() -> list[FlagRule]:
    return [
        FlagRule(
            key="bodily_injury", label="Bodily injury involved", applies_to=["property"],
            # Driven by the structured extraction field, not narrative keywords:
            # keyword scanning missed "arsuri" (burns) and false-fired on "nu sunt răniți".
            condition="extraction_true", params={"field": "bodily_injury"},
            min_severity=Severity.complex, requires_review=True,
            message_ro="Posibilă vătămare corporală - necesită verificare manuală.",
            message_en="Possible bodily injury - requires manual review.",
        ),
        FlagRule(
            key="catastrophe", label="Catastrophe event", applies_to=["property"],
            applies_to_claim_types=["storm_hail", "flood_natural"],
            # Stems so Romanian morphology matches (furtună/furtunii/furtuna, grindină/grindinei).
            keywords=["grindin", "furtun", "vijelie", "uragan", "viitur", "inund", "hail", "storm", "flood"],
            force_queue="cat_unit", force_queue_priority=10, min_severity=Severity.standard,
            requires_review=False,
            message_ro="Eveniment posibil de tip catastrofă - direcționat către Unitatea CAT.",
            message_en="Possible catastrophe event - routed to the CAT unit.",
        ),
        FlagRule(
            key="large_loss", label="Large loss (over threshold)", applies_to=["property"],
            condition="amount_over", params={},
            min_severity=Severity.complex, force_queue="property_complex", force_queue_priority=5,
            requires_review=True,
            message_ro="Valoare estimată peste pragul de daună mare.",
            message_en="Estimated amount above the large-loss threshold.",
        ),
        FlagRule(
            key="fraud_near_inception", label="Loss soon after policy inception", applies_to=["property"],
            condition="loss_within_days_of_inception", params={"days": 30},
            force_queue="siu", force_queue_priority=20, requires_review=True,
            message_ro="Daună la scurt timp după emiterea poliței - verificare SIU.",
            message_en="Loss shortly after inception - SIU review.",
        ),
        FlagRule(
            key="contestability", label="Death within contestability window", applies_to=["life_cpi"],
            applies_to_claim_types=["death"],
            condition="event_within_days_of_inception", params={},  # uses thresholds.contestability_days
            min_severity=Severity.complex, force_queue="siu", force_queue_priority=20,
            requires_review=True,
            message_ro="Deces în perioada de contestabilitate - verificare SIU / subscriere.",
            message_en="Death within the contestability window - SIU / underwriting review.",
        ),
        FlagRule(
            key="missing_death_certificate", label="Death certificate not mentioned",
            applies_to=["life_cpi"], applies_to_claim_types=["death"],
            condition="missing_document", params={"document": "death_certificate"},
            requires_review=True,
            message_ro="Certificatul de deces nu pare atașat - solicitați documentul.",
            message_en="Death certificate does not appear attached - request the document.",
        ),
        # --- AI-predicate flags (semantic; evaluated by the model, effect deterministic) ---
        FlagRule(
            key="suspected_arson", label="Possible arson", applies_to=["property"],
            applies_to_claim_types=["fire"],
            ai_predicate=("The description suggests the fire may have been set deliberately — "
                          "e.g. multiple points of origin, smell/presence of accelerant, an "
                          "inconsistent account, or a clear financial motive."),
            force_queue="siu", force_queue_priority=18, min_severity=Severity.complex,
            requires_review=True,
            message_ro="Indicii de posibil incendiu intenționat - verificare SIU.",
            message_en="Signs of possible arson - SIU review.",
        ),
        FlagRule(
            key="suspected_fraud_narrative", label="Fraud indicators in the narrative",
            applies_to=["property", "life_cpi"],
            ai_predicate=("The narrative has hallmarks of possible fraud — a staged or "
                          "exaggerated loss, internally inconsistent details, or pressure to "
                          "pay out quickly without documentation."),
            force_queue="siu", force_queue_priority=14, requires_review=True,
            message_ro="Indicii de posibilă fraudă în relatare - verificare SIU.",
            message_en="Possible fraud indicators in the account - SIU review.",
        ),
        FlagRule(
            key="vulnerable_customer", label="Vulnerable customer",
            ai_predicate=("The claimant appears vulnerable or in distress — bereavement, "
                          "disability, serious illness, financial hardship or confusion — and "
                          "needs careful, empathetic handling."),
            requires_review=True,
            message_ro="Client posibil vulnerabil - tratare cu atenție și empatie.",
            message_en="Possibly vulnerable customer - handle with care.",
        ),
    ]


def _routing_rules() -> list[RoutingRule]:
    # Evaluated in order, first match wins. Applied AFTER flag force_queue overrides.
    return [
        RoutingRule(key="life_death", line_of_business="life_cpi", claim_types=["death"],
                    queue="life_death_claims", description="CPI death -> death-claims desk"),
        RoutingRule(key="life_disability", line_of_business="life_cpi",
                    claim_types=["total_permanent_disability", "temporary_incapacity"],
                    queue="life_disability", description="CPI disability/incapacity -> disability desk"),
        RoutingRule(key="life_unemployment", line_of_business="life_cpi",
                    claim_types=["involuntary_unemployment"], queue="life_unemployment"),
        RoutingRule(key="property_complex", line_of_business="property",
                    severities=[Severity.complex], queue="property_complex"),
        RoutingRule(key="property_fast_track", line_of_business="property",
                    severities=[Severity.fast_track], queue="property_fast_track"),
        RoutingRule(key="property_standard", line_of_business="property", queue="property_standard",
                    description="Any remaining property claim"),
    ]


_ACK_BODY_RO_PROPERTY = (
    "Bună ziua {claimant_name},\n\n"
    "Am înregistrat notificarea dumneavoastră de daună pentru polița {policy_number} "
    "(dosar {claim_reference}). Cazul a fost direcționat către echipa „{queue_label}” "
    "și veți fi contactat în maximum {sla_hours} ore.\n\n"
    "Cu stimă,\nEchipa de daune"
)
_ACK_BODY_EN_PROPERTY = (
    "Hello {claimant_name},\n\n"
    "We have registered your loss notification for policy {policy_number} "
    "(file {claim_reference}). It has been routed to the \"{queue_label}\" team and you "
    "will be contacted within {sla_hours} hours.\n\n"
    "Kind regards,\nClaims team"
)
_ACK_BODY_RO_LIFE = (
    "Bună ziua {claimant_name},\n\n"
    "Am primit notificarea privind polița de protecție a creditului {policy_number} "
    "(dosar {claim_reference}) și vă transmitem condoleanțe / vă suntem alături. "
    "Dosarul este gestionat de echipa „{queue_label}”, care vă va contacta în maximum "
    "{sla_hours} ore cu lista documentelor necesare.\n\n"
    "Cu respect,\nEchipa de daune viață"
)
_ACK_BODY_EN_LIFE = (
    "Hello {claimant_name},\n\n"
    "We have received the notification for credit-protection policy {policy_number} "
    "(file {claim_reference}). The \"{queue_label}\" team will contact you within "
    "{sla_hours} hours with the list of required documents.\n\n"
    "With respect,\nLife claims team"
)


def _templates() -> list[Template]:
    return [
        Template(key="ack_property_ro", line_of_business="property", language="ro",
                 subject="Confirmare înregistrare daună {claim_reference}", body=_ACK_BODY_RO_PROPERTY),
        Template(key="ack_property_en", line_of_business="property", language="en",
                 subject="Claim registered {claim_reference}", body=_ACK_BODY_EN_PROPERTY),
        Template(key="ack_life_ro", line_of_business="life_cpi", language="ro",
                 subject="Confirmare înregistrare dosar {claim_reference}", body=_ACK_BODY_RO_LIFE),
        Template(key="ack_life_en", line_of_business="life_cpi", language="en",
                 subject="Claim registered {claim_reference}", body=_ACK_BODY_EN_LIFE),
    ]


def _few_shot_examples() -> list[FewShotExample]:
    return [
        FewShotExample(
            text="S-a spart o țeavă în baie și s-a inundat tot apartamentul, parchetul este distrus.",
            line_of_business="property", claim_type="water_damage", severity=Severity.standard,
            note="Clear single-cause water damage, moderate value.",
        ),
        FewShotExample(
            text="A fost grindină puternică azi-noapte și mi-a spart toate țiglele și geamurile.",
            line_of_business="property", claim_type="storm_hail", severity=Severity.standard,
            note="Weather event -> expect the catastrophe flag.",
        ),
        FewShotExample(
            text="Vă anunț că soțul meu, asiguratul, a decedat luna aceasta. Avem credit la bancă.",
            line_of_business="life_cpi", claim_type="death", severity=Severity.complex,
            note="CPI death notified by a beneficiary.",
        ),
        FewShotExample(
            text="I was laid off last week and I have credit protection insurance on my loan.",
            line_of_business="life_cpi", claim_type="involuntary_unemployment", severity=Severity.standard,
        ),
    ]


def _thresholds() -> Thresholds:
    return Thresholds(
        auto_ready_min_confidence=0.80,
        review_min_confidence=0.55,
        text_layer_min_chars_per_page=25,
        text_layer_max_garbage_ratio=0.15,
        large_loss_amount={"property": 50000.0},  # RON
        contestability_days=730,
    )


def build_starter_config() -> WorkflowConfig:
    """Return the deterministic starter workflow config."""
    return WorkflowConfig(
        lines_of_business=[_property_lob(), _life_cpi_lob()],
        queues=_queues(),
        flag_rules=_flag_rules(),
        routing_rules=_routing_rules(),
        templates=_templates(),
        few_shot_examples=_few_shot_examples(),
        thresholds=_thresholds(),
    )
