from __future__ import annotations

import copy

import pytest

from app.models import Severity
from app.persistence import ConfigValidationError, open_repository
from app.workflow.seed import build_starter_config


def test_starter_config_is_deterministic() -> None:
    a = build_starter_config()
    b = build_starter_config()
    assert a.model_dump() == b.model_dump()


def test_starter_config_passes_reference_checks() -> None:
    assert build_starter_config().validate_references() == []


def test_starter_config_shape() -> None:
    cfg = build_starter_config()
    assert cfg.lob_keys() == {"property", "life_cpi"}
    # every routing rule and flag points at a real queue
    for r in cfg.routing_rules:
        assert r.queue in cfg.queue_keys()
    # every LOB ships at least one claim type and a template in each language
    for lob in cfg.lines_of_business:
        assert lob.claim_types
        langs = {t.language for t in cfg.templates if t.line_of_business == lob.key}
        assert {"ro", "en"} <= langs


def test_validate_references_catches_broken_queue() -> None:
    cfg = build_starter_config()
    cfg.routing_rules[0].queue = "does_not_exist"
    errors = cfg.validate_references()
    assert any("does_not_exist" in e for e in errors)


def test_validate_references_catches_unknown_condition() -> None:
    cfg = build_starter_config()
    cfg.flag_rules[0].condition = "teleport"
    cfg.flag_rules[0].keywords = []
    errors = cfg.validate_references()
    assert any("teleport" in e for e in errors)


def test_store_save_and_activate(tmp_path) -> None:
    repo = open_repository(str(tmp_path / "t.db"), init=True)
    try:
        cfg = build_starter_config()
        v1 = repo.save_version(cfg, author="seed", label="v1")
        assert repo.active_version() == v1

        # A second, edited version becomes active.
        cfg2 = copy.deepcopy(cfg)
        cfg2.thresholds.large_loss_amount["property"] = 75000.0
        v2 = repo.save_version(cfg2, author="ops_lead", label="raise large-loss threshold")
        assert v2 > v1
        assert repo.active_version() == v2
        assert repo.active_config().thresholds.large_loss_amount["property"] == 75000.0

        # Rollback to v1.
        repo.activate(v1)
        assert repo.active_version() == v1
        assert repo.active_config().thresholds.large_loss_amount["property"] == 50000.0

        metas = repo.list_versions()
        assert [m.version for m in metas] == [v2, v1]
        assert sum(m.is_active for m in metas) == 1
    finally:
        repo.close()


def test_store_rejects_invalid_config(tmp_path) -> None:
    repo = open_repository(str(tmp_path / "t.db"), init=True)
    try:
        cfg = build_starter_config()
        cfg.routing_rules[0].queue = "nope"
        with pytest.raises(ConfigValidationError):
            repo.save_version(cfg, author="x", label="broken")
    finally:
        repo.close()


def test_severity_rank_ordering() -> None:
    assert Severity.fast_track.rank < Severity.standard.rank < Severity.complex.rank
