"""HTTP API for the review workflow."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import get_settings
from app.ingest import ingest
from app.observability import RunMetrics, estimate_cost, new_request_id
from app.persistence import open_repository
from app.pipeline import triage
from app.providers import get_provider
from app.workflow.schema import WorkflowConfig

router = APIRouter(prefix="/api")


def _active_config_or_503():
    repo = open_repository()
    config = repo.active_config()
    if config is None:
        repo.close()
        raise HTTPException(503, "No active workflow config. Run: python -m scripts.seed")
    return repo, config, repo.active_version()


@router.get("/config")
def get_config():
    repo, config, version = _active_config_or_503()
    try:
        return {
            "version": version,
            "lines_of_business": [
                {
                    "key": lob.key,
                    "label": lob.label_en,
                    "claim_types": [{"key": ct.key, "label": ct.label_en} for ct in lob.claim_types],
                }
                for lob in config.lines_of_business
            ],
            "queues": [{"key": q.key, "label": q.label, "sla_hours": q.sla_hours} for q in config.queues],
            "severities": ["fast_track", "standard", "complex"],
            "statuses": ["green", "amber", "red"],
        }
    finally:
        repo.close()


@router.post("/documents")
async def upload_document(file: UploadFile):
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    repo, config, version = _active_config_or_503()
    try:
        settings = get_settings()
        document = ingest(file.filename or "upload", data, config.thresholds)
        provider = get_provider(settings)
        metrics = RunMetrics(
            request_id=new_request_id(), doc_hash=document.doc_hash,
            provider=provider.name, ingestion_path=document.ingestion_path.value,
        )
        proposal = triage(
            document, data, provider, config, repo=repo, config_version=version, metrics=metrics
        )
        metrics.cost_usd = estimate_cost(metrics.input_tokens, metrics.output_tokens, settings)
        repo.record_run(metrics)
        repo.save_proposal(document, data, proposal)
        existing = repo.get_claim(document.doc_hash)
        return {
            "doc_hash": document.doc_hash,
            "proposal": proposal.model_dump(),
            "already_has_claim": existing is not None,
        }
    finally:
        repo.close()


@router.get("/documents")
def documents():
    repo = open_repository()
    try:
        return {"documents": repo.list_proposals()}
    finally:
        repo.close()


@router.get("/metrics")
def metrics():
    repo = open_repository()
    try:
        return repo.compute_metrics()
    finally:
        repo.close()


@router.get("/documents/{doc_hash}")
def document_detail(doc_hash: str):
    repo = open_repository()
    try:
        row = repo.get_document(doc_hash)
        proposal = repo.get_proposal(doc_hash)
        if row is None or proposal is None:
            raise HTTPException(404, "document not found")
        claim = repo.get_claim(doc_hash)
        return {
            "document": {
                "doc_hash": row.doc_hash,
                "filename": row.filename,
                "source_kind": row.source_kind,
                "ingestion_path": row.ingestion_path,
                "text": row.text,
                "raw_url": f"/api/documents/{doc_hash}/raw",
            },
            "proposal": proposal.model_dump(),
            "claim": claim.model_dump() if claim else None,
        }
    finally:
        repo.close()


@router.get("/documents/{doc_hash}/raw")
def document_raw(doc_hash: str):
    repo = open_repository()
    try:
        row = repo.get_document(doc_hash)
        if row is None or not row.raw_path or not Path(row.raw_path).exists():
            raise HTTPException(404, "raw file not found")
        return FileResponse(row.raw_path, media_type=row.media_type, filename=row.filename)
    finally:
        repo.close()


@router.post("/documents/{doc_hash}/reprocess")
def reprocess(doc_hash: str):
    """Re-run ingest + triage on the stored document with the CURRENT provider and
    active config, and update the stored proposal. Blocked once a claim is booked."""
    repo, config, version = _active_config_or_503()
    try:
        row = repo.get_document(doc_hash)
        if row is None:
            raise HTTPException(404, "document not found")
        if repo.get_claim(doc_hash) is not None:
            raise HTTPException(409, "claim already booked; cannot reprocess")
        if not row.raw_path or not Path(row.raw_path).exists():
            raise HTTPException(410, "raw file no longer available")

        settings = get_settings()
        data = Path(row.raw_path).read_bytes()
        document = ingest(row.filename, data, config.thresholds)
        provider = get_provider(settings)
        m = RunMetrics(
            request_id=new_request_id(), doc_hash=document.doc_hash,
            provider=provider.name, ingestion_path=document.ingestion_path.value,
        )
        proposal = triage(document, data, provider, config, repo=repo, config_version=version, metrics=m)
        m.cost_usd = estimate_cost(m.input_tokens, m.output_tokens, settings)
        repo.record_run(m)
        repo.save_proposal(document, data, proposal)
        return {"doc_hash": doc_hash, "provider": provider.name, "proposal": proposal.model_dump()}
    finally:
        repo.close()


class ApproveRequest(BaseModel):
    approved_by: str | None = None
    line_of_business: str | None = None
    claim_type: str | None = None
    severity: str | None = None
    queue: str | None = None
    status: str | None = None


@router.post("/documents/{doc_hash}/approve")
def approve(doc_hash: str, req: ApproveRequest):
    repo = open_repository()
    try:
        proposal = repo.get_proposal(doc_hash)
        if proposal is None:
            raise HTTPException(404, "document not found")
        claim, created = repo.create_claim(
            proposal, req.model_dump(exclude={"approved_by"}), req.approved_by
        )
        repo.mark_reviewed(doc_hash)
        return {"created": created, "claim": claim.model_dump()}
    finally:
        repo.close()


# --- config management (Stage 5) -------------------------------------------
def _parse_config(data: dict) -> tuple[WorkflowConfig | None, list[str]]:
    try:
        config = WorkflowConfig.model_validate(data)
    except Exception as e:  # pydantic validation error
        return None, [f"invalid config structure: {e}"]
    return config, config.validate_references()


@router.get("/config/full")
def config_full():
    repo = open_repository()
    try:
        config = repo.active_config()
        if config is None:
            raise HTTPException(503, "No active config. Run: python -m scripts.seed")
        return {
            "version": repo.active_version(),
            "config": config.model_dump(),
            "versions": [vars(m) for m in repo.list_versions()],
        }
    finally:
        repo.close()


@router.get("/config/version/{version}")
def config_version(version: int):
    repo = open_repository()
    try:
        return {"version": version, "config": repo.get_config(version).model_dump()}
    except KeyError:
        raise HTTPException(404, f"config version {version} not found")
    finally:
        repo.close()


class ConfigBody(BaseModel):
    config: dict


@router.post("/config/validate")
def config_validate(body: ConfigBody):
    _config, errors = _parse_config(body.config)
    return {"errors": errors}


@router.post("/config/preview")
def config_preview(body: ConfigBody):
    from eval.dataset import build_cases
    from app.preview import diff, run_cases

    proposed, errors = _parse_config(body.config)
    if proposed is None or errors:
        return {"errors": errors}
    repo = open_repository()
    try:
        active = repo.active_config()
        if active is None:
            raise HTTPException(503, "No active config.")
        cases = build_cases()
        result = diff(run_cases(repo, active, cases), run_cases(repo, proposed, cases), cases)
        return {"errors": [], **result}
    finally:
        repo.close()


class SaveBody(BaseModel):
    config: dict
    author: str = "ops"
    label: str = "edit"


@router.post("/config/save")
def config_save(body: SaveBody):
    config, errors = _parse_config(body.config)
    if config is None or errors:
        return {"errors": errors, "version": None}
    repo = open_repository()
    try:
        version = repo.save_version(config, author=body.author, label=body.label)
        return {"errors": [], "version": version}
    finally:
        repo.close()


class ActivateBody(BaseModel):
    version: int


@router.post("/config/activate")
def config_activate(body: ActivateBody):
    repo = open_repository()
    try:
        repo.activate(body.version)
        return {"ok": True, "version": body.version}
    except KeyError:
        raise HTTPException(404, f"config version {body.version} not found")
    finally:
        repo.close()
