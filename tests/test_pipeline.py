from __future__ import annotations

from app.config import Settings
from app.ingest import ingest
from app.models import Classification, FnolExtraction, IngestedDocument, Severity, Status
from app.persistence import open_repository
from app.pipeline import triage
from app.policy import build_policies
from app.providers.base import LLMProvider
from app.providers.mock import MockProvider
from app.workflow.seed import build_starter_config


def _seeded_repo(tmp_path):
    repo = open_repository(str(tmp_path / "t.db"), init=True)
    repo.save_version(build_starter_config(), author="t", label="t")
    repo.replace_policies(build_policies())
    return repo


class FakeProvider(LLMProvider):
    """Returns canned extraction/classification to drive specific pipeline paths."""

    name = "fake"

    def __init__(self, extraction: FnolExtraction, classification: Classification) -> None:
        super().__init__(Settings(llm_provider="mock"))
        self._ext = extraction
        self._cls = classification

    def extract(self, document, content):
        return self._ext

    def classify(self, extraction, config):
        return self._cls


def test_pipeline_green_path(tmp_path) -> None:
    repo = _seeded_repo(tmp_path)
    cfg = repo.active_config()
    ext = FnolExtraction(
        policy_number="PROP-2024-558120", event_or_loss_date="2025-10-06",
        loss_location="Str. Lalelelor 12", description="țeavă spartă, apartament inundat",
        language="ro", overall_confidence=0.95,
    )
    cls = Classification(line_of_business="property", claim_type="water_damage",
                         severity=Severity.standard, confidence=0.92)
    doc = ingest("note.txt", b"placeholder")
    proposal = triage(doc, b"placeholder", FakeProvider(ext, cls), cfg, repo=repo)
    assert proposal.status == Status.green
    assert proposal.queue == "property_standard"
    assert proposal.draft is not None and "{" not in proposal.draft.body


def test_pipeline_image_goes_red_manual_on_mock(tmp_path) -> None:
    repo = _seeded_repo(tmp_path)
    cfg = repo.active_config()
    doc = ingest("scan.png", b"not a real image")
    proposal = triage(doc, b"not a real image", MockProvider(Settings()), cfg, repo=repo)
    assert proposal.status == Status.red
    assert proposal.queue == "manual_intake"
    assert proposal.classification is None


def test_pipeline_classify_fallback_forces_amber(tmp_path) -> None:
    repo = _seeded_repo(tmp_path)
    cfg = repo.active_config()

    class BrokenClassify(FakeProvider):
        def classify(self, extraction, config):
            raise RuntimeError("model unavailable")

    ext = FnolExtraction(
        policy_number="PROP-2024-558120", event_or_loss_date="2025-10-06",
        loss_location="Str. X", description="țeavă spartă inundație", language="ro",
        overall_confidence=0.95,
    )
    cls = Classification(line_of_business="property", claim_type="water_damage",
                         severity=Severity.standard, confidence=0.92)
    doc = ingest("n.txt", b"x")
    proposal = triage(doc, b"x", BrokenClassify(ext, cls), cfg, repo=repo)
    # Fallback ran (baseline classification) and status cannot be green.
    assert proposal.status != Status.green
    assert any("baseline" in r for r in proposal.reasons)
