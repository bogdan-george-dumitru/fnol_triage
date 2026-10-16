"""FastAPI entrypoint.

Serves the JSON API and the single static review page. Run with:

    uv run uvicorn app.main:app --reload

Then open http://127.0.0.1:8000/ (seed first: python -m scripts.seed).

Structured JSON logs (to stdout) are emitted:
  - once at startup/shutdown,
  - once per HTTP request (method / path / status / duration / request_id),
  - once per document processed ("run_complete", from app.observability.record_run).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import get_settings
from app.observability import log_event, new_request_id

_STATIC = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log_event("startup", provider=settings.llm_provider, version=app.version)
    yield
    log_event("shutdown")


app = FastAPI(title="AI-assisted FNOL triage", version="0.6.0", lifespan=lifespan)
app.include_router(api_router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log one JSON line per HTTP request, tagging it with a request_id."""
    rid = request.headers.get("x-request-id") or new_request_id()
    start = perf_counter()
    response = await call_next(request)
    log_event(
        "request",
        request_id=rid,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((perf_counter() - start) * 1000, 1),
    )
    response.headers["X-Request-ID"] = rid
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe + which provider is active (does not call the provider)."""
    return {"status": "ok", "provider": get_settings().llm_provider}


@app.get("/metrics")
def metrics() -> dict:
    """Alias for /api/metrics (the brief names it /metrics)."""
    from app.persistence import open_repository

    repo = open_repository()
    try:
        return repo.compute_metrics()
    finally:
        repo.close()


@app.get("/")
def index() -> FileResponse:
    # Dev tool: never serve a stale page, so a plain reload always picks up UI edits.
    return FileResponse(
        _STATIC / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
