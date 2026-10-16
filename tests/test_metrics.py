from __future__ import annotations

from app.config import Settings
from app.observability import RunMetrics, estimate_cost
from app.persistence import open_repository


def test_estimate_cost() -> None:
    s = Settings(openai_input_cost_per_1m=0.25, openai_output_cost_per_1m=2.0)
    assert estimate_cost(1_000_000, 0, s) == 0.25
    assert estimate_cost(0, 1_000_000, s) == 2.0
    assert estimate_cost(0, 0, s) == 0.0


def test_record_and_aggregate(tmp_path) -> None:
    repo = open_repository(str(tmp_path / "t.db"), init=True)
    repo.record_run(RunMetrics(request_id="a", total_ms=100.0, status="green",
                               queue="property_standard", ingestion_path="text", provider="mock",
                               input_tokens=10, output_tokens=20, cost_usd=0.001))
    repo.record_run(RunMetrics(request_id="b", total_ms=300.0, status="amber",
                               queue="siu", ingestion_path="vision", provider="openai",
                               input_tokens=900, output_tokens=1100, cost_usd=0.003))
    m = repo.compute_metrics()
    assert m["documents_processed"] == 2
    assert m["latency_ms"]["p50"] is not None
    assert m["latency_ms"]["max"] == 300.0
    assert m["status_distribution"] == {"green": 1, "amber": 1}
    assert m["ingestion_path_distribution"] == {"text": 1, "vision": 1}
    assert round(m["cost"]["total_usd"], 3) == 0.004
    assert m["human_review"]["claims_booked"] == 0
    # per-provider breakdown
    assert set(m["by_provider"]) == {"mock", "openai"}
    assert m["by_provider"]["mock"]["documents"] == 1
    assert m["by_provider"]["openai"]["latency_ms"]["p50"] == 300.0
    assert m["by_provider"]["mock"]["cost_per_document_usd"] == 0.001
