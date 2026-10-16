from __future__ import annotations

import copy

from app.persistence import open_repository
from app.policy import build_policies
from app.preview import diff, run_cases
from app.workflow.seed import build_starter_config
from eval.dataset import build_cases


def _seeded(tmp_path):
    repo = open_repository(str(tmp_path / "t.db"), init=True)
    repo.save_version(build_starter_config(), author="t", label="t")
    repo.replace_policies(build_policies())
    return repo


def test_cases_match_expected_under_starter_config(tmp_path) -> None:
    repo = _seeded(tmp_path)
    cfg = repo.active_config()
    cases = build_cases()
    by = {r["name"]: r for r in run_cases(repo, cfg, cases)}
    for c in cases:
        got = by[c.name]
        assert got["status"] == c.expected_status, (c.name, "status", got)
        assert got["queue"] == c.expected_queue, (c.name, "queue", got)
        for fk in c.expected_flags:
            assert fk in got["flags"], (c.name, "missing flag", fk, got["flags"])


def test_preview_diff_detects_threshold_change(tmp_path) -> None:
    repo = _seeded(tmp_path)
    active = repo.active_config()
    cases = build_cases()

    # Raise the large-loss threshold above the large_loss case's amount (150k).
    proposed = copy.deepcopy(active)
    proposed.thresholds.large_loss_amount["property"] = 200000.0

    result = diff(run_cases(repo, active, cases), run_cases(repo, proposed, cases), cases)
    assert result["summary"]["changed_count"] >= 1
    large = next(r for r in result["rows"] if r["name"] == "large_loss")
    assert "queue" in large["changed"]
    assert large["active"]["queue"] == "property_complex"
    assert large["proposed"]["queue"] == "property_standard"


def test_preview_diff_empty_when_config_unchanged(tmp_path) -> None:
    repo = _seeded(tmp_path)
    active = repo.active_config()
    cases = build_cases()
    result = diff(run_cases(repo, active, cases), run_cases(repo, active, cases), cases)
    assert result["summary"]["changed_count"] == 0
