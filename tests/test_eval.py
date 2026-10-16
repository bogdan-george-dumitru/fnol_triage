from __future__ import annotations

from eval.run_eval import run


def test_mock_eval_runs_and_reports() -> None:
    res = run("mock")
    assert res["n_cases"] == 17
    for key in ("extraction", "classification", "routing_accuracy", "status_accuracy",
                "green_precision", "status_distribution", "latency_ms", "cost"):
        assert key in res
    # mock extracts labeled key fields with decent precision
    assert res["extraction"]["precision"] > 0.5
    # mock is free
    assert res["cost"]["total_usd"] == 0.0
    # every case produced a prediction row
    assert len(res["cases"]) == 17
