from __future__ import annotations

import pytest

from app.config import Settings
from app.errors import ExtractionError
from app.ingest import ingest
from app.providers.mock import MockProvider, extract_fields_from_text
from app.providers.openai_provider import run_with_retry


def _mock() -> MockProvider:
    return MockProvider(Settings(llm_provider="mock"))


def test_mock_extracts_ro_water_damage() -> None:
    text = (
        "Bună ziua, notific o daună la polița nr. PROP-2024-558120. "
        "La data de 06.10.2025 s-a spart o țeavă și s-a inundat apartamentul. "
        "Estimez pagubele la 18.500 lei. Vecinul de dedesubt are și el pagube."
    )
    doc = ingest("n.txt", text.encode("utf-8"))
    ext = _mock().extract(doc, text.encode("utf-8"))
    assert ext.policy_number == "PROP-2024-558120"
    assert ext.event_or_loss_date == "06.10.2025"
    assert ext.estimated_amount == 18500.0
    assert ext.currency == "LEI"
    assert ext.language == "ro"
    assert ext.third_party_involved is True
    assert ext.overall_confidence and ext.overall_confidence > 0


def test_mock_detects_english_and_loan_ref() -> None:
    text = "Policy CPI-2025-114977 loan no. LN-889201. I was made redundant."
    ext = extract_fields_from_text(text)
    assert ext.language == "en"
    assert ext.policy_number == "CPI-2025-114977"
    assert ext.loan_reference == "LN-889201"


def test_mock_image_goes_manual() -> None:
    doc = ingest("scan.png", b"not an image")
    ext = _mock().extract(doc, b"not an image")
    assert ext.overall_confidence == 0.0
    assert ext.illegible_fields == ["all"]


def test_mock_flags_bodily_injury() -> None:
    ext = extract_fields_from_text("Incendiu, un membru al familiei a fost rănit.")
    assert ext.bodily_injury is True


# --- retry helper (covers the OpenAI schema-invalid -> retry -> manual path) ---

def test_run_with_retry_succeeds_second_attempt() -> None:
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad schema")
        return "ok"

    assert run_with_retry(flaky, retries=1) == "ok"
    assert calls["n"] == 2


def test_run_with_retry_raises_after_exhaustion() -> None:
    def always_none():
        return None

    with pytest.raises(ExtractionError):
        run_with_retry(always_none, retries=1)
