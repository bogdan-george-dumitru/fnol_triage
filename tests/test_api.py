from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).parent.parent / "samples"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.persistence import open_repository
    from app.policy import build_policies
    from app.workflow.seed import build_starter_config

    repo = open_repository(init=True)
    repo.save_version(build_starter_config(), author="seed", label="seed")
    repo.replace_policies(build_policies())
    repo.close()

    from app.main import app

    yield TestClient(app)
    get_settings.cache_clear()


def _upload(client, name):
    data = (SAMPLES / name).read_bytes()
    return client.post("/api/documents", files={"file": (name, data, "text/plain")})


def test_config_endpoint(client) -> None:
    cfg = client.get("/api/config").json()
    assert {lob["key"] for lob in cfg["lines_of_business"]} == {"property", "life_cpi"}
    assert any(q["key"] == "manual_intake" for q in cfg["queues"])


def test_upload_produces_proposal(client) -> None:
    r = _upload(client, "water_damage_ro.eml")
    assert r.status_code == 200
    body = r.json()
    assert body["proposal"]["line_of_business"] == "property"
    assert body["proposal"]["claim_type"] == "water_damage"
    assert body["already_has_claim"] is False
    # appears in the inbox
    docs = client.get("/api/documents").json()["documents"]
    assert any(d["doc_hash"] == body["doc_hash"] for d in docs)


def test_approve_creates_claim_and_is_idempotent(client) -> None:
    h = _upload(client, "water_damage_ro.eml").json()["doc_hash"]
    r1 = client.post(f"/api/documents/{h}/approve", json={"approved_by": "ana"})
    assert r1.json()["created"] is True
    # second approve -> idempotent, no new claim
    r2 = client.post(f"/api/documents/{h}/approve", json={"approved_by": "ana"})
    assert r2.json()["created"] is False
    assert r1.json()["claim"]["id"] == r2.json()["claim"]["id"]


def test_reupload_same_document_does_not_create_second_claim(client) -> None:
    h = _upload(client, "water_damage_ro.eml").json()["doc_hash"]
    client.post(f"/api/documents/{h}/approve", json={"approved_by": "ana"})
    # upload the exact same bytes again
    again = _upload(client, "water_damage_ro.eml").json()
    assert again["doc_hash"] == h
    assert again["already_has_claim"] is True


def test_metrics_endpoint_tracks_runs_and_overrides(client) -> None:
    _upload(client, "water_damage_ro.eml")
    h = _upload(client, "fire_injury_ro.txt").json()["doc_hash"]
    client.post(f"/api/documents/{h}/approve", json={"approved_by": "bob", "queue": "property_fast_track"})

    m = client.get("/api/metrics").json()
    assert m["documents_processed"] == 2
    assert m["latency_ms"]["p50"] is not None
    assert sum(m["status_distribution"].values()) == 2
    assert m["cost"]["total_usd"] == 0.0  # mock provider is free
    hr = m["human_review"]
    assert hr["claims_booked"] == 1 and hr["claims_edited"] == 1
    assert "queue" in hr["field_overrides"]


def test_reprocess_updates_and_is_blocked_after_booking(client) -> None:
    h = _upload(client, "water_damage_ro.eml").json()["doc_hash"]
    r = client.post(f"/api/documents/{h}/reprocess")
    assert r.status_code == 200
    assert r.json()["provider"] == "mock"
    assert r.json()["proposal"]["line_of_business"] == "property"
    # once booked, reprocess is blocked
    client.post(f"/api/documents/{h}/approve", json={"approved_by": "ana"})
    assert client.post(f"/api/documents/{h}/reprocess").status_code == 409


def test_business_dedup_flags_same_loss_different_document(client) -> None:
    # Two different documents, same policy + claim type, loss dates 4 days apart.
    first = _upload(client, "water_damage_ro.eml").json()
    second = _upload(client, "water_damage_phone_ro.txt").json()
    dups = second["proposal"]["possible_duplicates"]
    assert first["proposal"]["claim_reference"] in dups


def test_config_full_and_preview(client) -> None:
    full = client.get("/api/config/full").json()
    assert full["version"] == 1
    cfg = full["config"]
    cfg["thresholds"]["large_loss_amount"]["property"] = 200000.0
    prev = client.post("/api/config/preview", json={"config": cfg}).json()
    assert prev["errors"] == []
    assert prev["summary"]["changed_count"] >= 1
    large = next(r for r in prev["rows"] if r["name"] == "large_loss")
    assert "queue" in large["changed"]


def test_config_save_and_rollback(client) -> None:
    cfg = client.get("/api/config/full").json()["config"]
    cfg["thresholds"]["large_loss_amount"]["property"] = 90000.0
    saved = client.post("/api/config/save", json={"config": cfg, "author": "lead", "label": "raise LL"}).json()
    assert saved["errors"] == [] and saved["version"] == 2
    assert client.get("/api/config/full").json()["version"] == 2
    # rollback to v1
    client.post("/api/config/activate", json={"version": 1})
    assert client.get("/api/config/full").json()["version"] == 1


def test_config_save_rejects_invalid(client) -> None:
    cfg = client.get("/api/config/full").json()["config"]
    cfg["routing_rules"][0]["queue"] = "ghost_queue"
    r = client.post("/api/config/save", json={"config": cfg}).json()
    assert r["version"] is None
    assert any("ghost_queue" in e for e in r["errors"])


def test_approve_records_human_edits(client) -> None:
    h = _upload(client, "fire_injury_ro.txt").json()["doc_hash"]
    # override the queue the AI proposed
    r = client.post(
        f"/api/documents/{h}/approve",
        json={"approved_by": "bob", "queue": "property_fast_track"},
    )
    claim = r.json()["claim"]
    assert claim["edited"] is True
    assert "queue" in claim["edits"]
