"""Structured logging + per-run metrics (the non-storage half).

- A JSON logger writes one line per event to stdout, tagged with a `request_id`.
- `RunMetrics` collects per-stage latency, token usage and estimated cost for one
  document. Persisting it to the `runs` table (and aggregating `/metrics`) lives in
  the SQLite adapter (`app.persistence.sqlite.runs`), behind the repository port.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import Settings

_LOGGER_NAME = "fnol"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(event: str, **fields) -> None:
    get_logger().info(event, extra={"fields": fields})


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunMetrics:
    request_id: str
    doc_hash: str | None = None
    provider: str | None = None
    ingestion_path: str | None = None
    extract_ms: float = 0.0
    classify_ms: float = 0.0
    triage_ms: float = 0.0
    total_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    status: str | None = None
    line_of_business: str | None = None
    claim_type: str | None = None
    queue: str | None = None
    classify_failed: bool = False
    created_at: str = field(default_factory=_now)


def estimate_cost(input_tokens: int, output_tokens: int, settings: Settings) -> float:
    return round(
        input_tokens / 1_000_000 * settings.openai_input_cost_per_1m
        + output_tokens / 1_000_000 * settings.openai_output_cost_per_1m,
        6,
    )
