"""Core domain models for the FNOL (First Notice of Loss) triage workflow.

These are the engineering-owned types that drive control flow. The *business-owned*
configuration (taxonomy, routing rules, templates, thresholds) lives in
`app.workflow.schema` and references these enums.

Design note on the ownership split:
  - `Severity` and `Status` are FIXED enums: the code's control flow (routing,
    status colouring, floors) depends on them, so engineering owns them.
  - Line-of-business keys and claim-type keys are plain strings validated against
    the business config's taxonomy, because the business team must be able to add
    or rename them without a code change. That is the whole point of the workflow.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Triage tier the model proposes and deterministic floors may raise."""

    fast_track = "fast_track"
    standard = "standard"
    complex = "complex"

    @property
    def rank(self) -> int:
        return {"fast_track": 0, "standard": 1, "complex": 2}[self.value]


class Status(str, Enum):
    """Per-FNOL review status shown to the handler."""

    green = "green"  # confident + rules satisfied -> one-click approve
    amber = "amber"  # needs a look -> reasons + alternatives
    red = "red"  # cannot auto-propose -> manual intake


class SourceKind(str, Enum):
    email = "email"
    text = "text"
    pdf = "pdf"
    image = "image"


class IngestionPath(str, Enum):
    """How the document's content was obtained (set during ingest, Stage 2)."""

    text = "text"  # plain text / email body
    pdf_text_layer = "pdf_text_layer"  # typed PDF, pypdf extracted usable text
    vision = "vision"  # scanned/handwritten/image -> OpenAI vision
    none = "none"  # nothing usable -> manual intake


class IngestedDocument(BaseModel):
    """A loss notification after ingest. `doc_hash` is the idempotency key."""

    doc_hash: str
    filename: str
    media_type: str
    source_kind: SourceKind
    size_bytes: int
    received_at: str  # ISO timestamp

    ingestion_path: IngestionPath = IngestionPath.none
    text: str | None = None  # extracted text when a text path was used
    num_pages: int | None = None


class FnolExtraction(BaseModel):
    """Structured fields pulled from the notification by `provider.extract`.

    One schema covers both lines of business; LOB-specific fields are optional.
    Dates are kept as strings to tolerate whatever the model returns; normalising
    happens in the deterministic layer. Per-field confidence and `illegible_fields`
    support the handwriting failure mode (low confidence -> amber/red, never a
    confident guess).
    """

    language: str | None = None  # "ro" | "en"

    # Identifiers
    policy_number: str | None = None
    loan_reference: str | None = None  # Life/CPI: the credit the cover is attached to
    claim_reference: str | None = None  # customer's own reference, if any

    # People
    claimant_name: str | None = None  # who is notifying (may be a beneficiary/lender)
    claimant_contact: str | None = None
    insured_name: str | None = None
    beneficiary: str | None = None
    lender: str | None = None  # Life/CPI

    # Event
    line_of_business_hint: str | None = None  # classification decides the final LOB
    event_or_loss_date: str | None = None
    reported_date: str | None = None
    loss_location: str | None = None  # property
    peril_text: str | None = None  # cause as written by the customer
    event_type_hint: str | None = None  # Life/CPI: death/disability/... as written
    description: str | None = None
    estimated_amount: float | None = None
    currency: str | None = None

    bodily_injury: bool | None = None
    third_party_involved: bool | None = None
    documents_mentioned: list[str] = Field(default_factory=list)

    # Confidence / legibility
    field_confidence: dict[str, float] = Field(default_factory=dict)
    overall_confidence: float | None = None
    illegible_fields: list[str] = Field(default_factory=list)

    notes: str | None = None


class Classification(BaseModel):
    """Output of `provider.classify`: LOB, claim type, severity + advisory flags.

    `claim_type` and `line_of_business` are strings validated against the config
    taxonomy. `suggested_flags` are advisory — the deterministic layer decides
    which flags actually fire.
    """

    line_of_business: str
    claim_type: str
    severity: Severity
    confidence: float
    suggested_flags: list[str] = Field(default_factory=list)
    rationale: str | None = None


class FiredFlag(BaseModel):
    """A deterministic flag that actually fired on this FNOL."""

    key: str
    label: str
    message: str  # localised (ro/en) message for the handler


class PolicyCheck(BaseModel):
    """Result of looking the policy up in the (simulated) policy master."""

    policy_number: str | None = None
    found: bool = False
    status: str | None = None  # in_force / lapsed / cancelled
    product: str | None = None
    inception_date: str | None = None
    sum_insured: float | None = None
    currency: str | None = None


class DraftAck(BaseModel):
    template_key: str
    language: str
    subject: str
    body: str


class TriageProposal(BaseModel):
    """The full proposal shown to the handler: what the AI proposed + what the
    deterministic layer decided, with reasons. The human edits and approves this."""

    doc_hash: str
    claim_reference: str
    config_version: int | None = None

    extraction: FnolExtraction
    classification: Classification | None = None

    line_of_business: str | None = None
    claim_type: str | None = None
    severity: Severity | None = None

    queue: str
    queue_label: str
    sla_hours: int | None = None

    status: Status
    reasons: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)  # alternative claim types

    flags: list[FiredFlag] = Field(default_factory=list)
    policy_check: PolicyCheck | None = None
    draft: DraftAck | None = None
    possible_duplicates: list[str] = Field(default_factory=list)  # business-dedup: matching FNOL refs


class Claim(BaseModel):
    """A booked claim: the AI proposal, the approved values, and the human edits.

    Created idempotently (one per document hash) when a handler approves a proposal.
    Persisted via the repository; this is the domain entity, not a storage row.
    """

    id: int
    doc_hash: str
    claim_reference: str
    created_at: str
    line_of_business: str | None
    claim_type: str | None
    severity: str | None
    status: str | None
    queue: str | None
    approved_by: str | None
    edited: bool
    edits: list[str]
