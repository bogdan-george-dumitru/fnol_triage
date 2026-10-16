"""SQLite adapter: per-run telemetry (`runs` table) + /metrics aggregation.

`record_run` persists one `RunMetrics` and emits the `run_complete` JSON log line;
`compute_metrics` aggregates `runs` (+ `claims` for the human override rate) into the
/metrics payload.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict

from app.observability import RunMetrics, log_event


def record_run(conn: sqlite3.Connection, m: RunMetrics) -> None:
    conn.execute(
        """
        INSERT INTO runs (request_id, doc_hash, created_at, provider, ingestion_path,
            extract_ms, classify_ms, triage_ms, total_ms, input_tokens, output_tokens,
            cost_usd, status, line_of_business, claim_type, queue, classify_failed)
        VALUES (:request_id, :doc_hash, :created_at, :provider, :ingestion_path,
            :extract_ms, :classify_ms, :triage_ms, :total_ms, :input_tokens, :output_tokens,
            :cost_usd, :status, :line_of_business, :claim_type, :queue, :classify_failed)
        """,
        {**asdict(m), "classify_failed": int(m.classify_failed)},
    )
    conn.commit()
    log_event(
        "run_complete",
        request_id=m.request_id, doc_hash=(m.doc_hash or "")[:12], provider=m.provider,
        ingestion_path=m.ingestion_path, total_ms=round(m.total_ms, 1),
        extract_ms=round(m.extract_ms, 1), classify_ms=round(m.classify_ms, 1),
        tokens_in=m.input_tokens, tokens_out=m.output_tokens, cost_usd=m.cost_usd,
        status=m.status, queue=m.queue,
    )


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    # nearest-rank
    k = max(0, min(len(s) - 1, int(round(pct / 100 * (len(s) - 1)))))
    return round(s[k], 1)


def _distribution(conn: sqlite3.Connection, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS k, COUNT(*) AS n FROM runs GROUP BY {column}"
    ).fetchall()
    return {(r["k"] or "unknown"): r["n"] for r in rows}


def compute_metrics(conn: sqlite3.Connection) -> dict:
    runs = conn.execute(
        "SELECT total_ms, cost_usd, input_tokens, output_tokens, provider FROM runs"
    ).fetchall()
    n = len(runs)
    latencies = [r["total_ms"] for r in runs if r["total_ms"] is not None]
    total_cost = sum(r["cost_usd"] or 0 for r in runs)
    total_in = sum(r["input_tokens"] or 0 for r in runs)
    total_out = sum(r["output_tokens"] or 0 for r in runs)

    # Per-provider breakdown — latency/cost differ fundamentally between mock and
    # openai, so the blended p50/p95 is misleading on its own.
    by_prov: dict[str, list] = defaultdict(list)
    for r in runs:
        by_prov[r["provider"] or "unknown"].append(r)
    provider_breakdown = {}
    for prov, rs in sorted(by_prov.items()):
        lat = [x["total_ms"] for x in rs if x["total_ms"] is not None]
        cost = sum(x["cost_usd"] or 0 for x in rs)
        provider_breakdown[prov] = {
            "documents": len(rs),
            "latency_ms": {"p50": _percentile(lat, 50), "p95": _percentile(lat, 95)},
            "cost_per_document_usd": round(cost / len(rs), 6) if rs else 0,
        }

    # Human edit / override rate (from approved claims).
    claims = conn.execute("SELECT edited, edits_json FROM claims").fetchall()
    n_claims = len(claims)
    n_edited = sum(1 for c in claims if c["edited"])
    field_overrides: Counter = Counter()
    for c in claims:
        if c["edits_json"]:
            field_overrides.update(json.loads(c["edits_json"]))

    return {
        "documents_processed": n,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": round(max(latencies), 1) if latencies else None,
        },
        "cost": {
            "total_usd": round(total_cost, 6),
            "per_document_usd": round(total_cost / n, 6) if n else 0,
        },
        "tokens": {
            "input_total": total_in,
            "output_total": total_out,
            "avg_per_doc": round((total_in + total_out) / n, 1) if n else 0,
        },
        "by_provider": provider_breakdown,
        "status_distribution": _distribution(conn, "status"),
        "queue_distribution": _distribution(conn, "queue"),
        "line_of_business_distribution": _distribution(conn, "line_of_business"),
        "ingestion_path_distribution": _distribution(conn, "ingestion_path"),
        "provider_distribution": _distribution(conn, "provider"),
        "human_review": {
            "claims_booked": n_claims,
            "claims_edited": n_edited,
            "override_rate": round(n_edited / n_claims, 3) if n_claims else None,
            "field_overrides": dict(field_overrides),
        },
    }
