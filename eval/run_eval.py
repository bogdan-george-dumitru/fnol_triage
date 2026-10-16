"""Evaluate the triage pipeline against the hand-labeled test set.

Usage:
    uv run python -m eval.run_eval --provider mock      # free
    uv run python -m eval.run_eval --provider openai    # costs money

Builds a fresh temp DB (starter config + policy master), runs the full pipeline
over eval/testset/labels.json, and reports extraction P/R, classification and
routing accuracy, green-line precision (the key metric), status distribution,
latency and cost. Writes results to eval/results/.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.ingest import ingest_path
from app.observability import RunMetrics, estimate_cost
from app.persistence import open_repository
from app.pipeline import triage
from app.policy import build_policies
from app.providers import get_provider
from app.triage import normalize_date
from app.workflow.seed import build_starter_config

ROOT = Path(__file__).resolve().parent.parent
KEY_FIELDS = ["policy_number", "loan_reference", "event_or_loss_date",
              "estimated_amount", "bodily_injury", "language"]


def _percentile(values, pct):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(pct / 100 * (len(s) - 1)))))
    return round(s[k], 1)


def _norm(field, val):
    if val is None:
        return None
    if field == "event_or_loss_date":
        return normalize_date(str(val))
    if field == "estimated_amount":
        return float(val)
    if field == "bodily_injury":
        return bool(val)
    return str(val).strip().lower()


def _predicted(ext, field):
    if field == "event_or_loss_date":
        return ext.event_or_loss_date or ext.reported_date
    return getattr(ext, field, None)


def run(provider_name: str) -> dict:
    settings = Settings(llm_provider=provider_name)
    cases = json.loads((ROOT / "eval/testset/labels.json").read_text("utf-8"))

    with tempfile.TemporaryDirectory() as td:
        repo = open_repository(str(Path(td) / "eval.db"), init=True)
        config = build_starter_config()
        repo.save_version(config, author="eval", label="eval")
        repo.replace_policies(build_policies())
        provider = get_provider(settings)

        rows = []
        # extraction counters
        correct = retrieved = relevant = 0
        # flag counters
        f_tp = f_fp = f_fn = 0
        latencies = []
        total_cost = 0.0

        for case in cases:
            doc, content = ingest_path(str(ROOT / case["path"]), config.thresholds)
            m = RunMetrics(request_id="eval", doc_hash=doc.doc_hash,
                           provider=provider.name, ingestion_path=doc.ingestion_path.value)
            p = triage(doc, content, provider, config, repo=repo, metrics=m)
            m.cost_usd = estimate_cost(m.input_tokens, m.output_tokens, settings)
            latencies.append(m.total_ms)
            total_cost += m.cost_usd

            ext = p.extraction
            for field in KEY_FIELDS:
                if field not in case["fields"] or case["fields"][field] is None:
                    continue
                relevant += 1
                pv = _predicted(ext, field)
                if pv is not None:
                    retrieved += 1
                    if _norm(field, pv) == _norm(field, case["fields"][field]):
                        correct += 1

            pred_flags = {f.key for f in p.flags}
            exp_flags = set(case.get("flags", []))
            f_tp += len(pred_flags & exp_flags)
            f_fp += len(pred_flags - exp_flags)
            f_fn += len(exp_flags - pred_flags)

            rows.append({
                "name": Path(case["path"]).name, "scenario": case["scenario"],
                "ingestion": doc.ingestion_path.value,
                "truth": {"lob": case["lob"], "claim_type": case["claim_type"],
                          "severity": case["severity"], "status": case["status"], "queue": case["queue"]},
                "pred": {"lob": p.line_of_business, "claim_type": p.claim_type,
                         "severity": p.severity.value if p.severity else None,
                         "status": p.status.value, "queue": p.queue},
                "cost_usd": m.cost_usd, "latency_ms": round(m.total_ms, 1),
            })

    n = len(rows)

    def acc(pred_key, truth_key):
        return round(sum(1 for r in rows if r["pred"][pred_key] == r["truth"][truth_key]) / n, 3)

    complex_cases = [r for r in rows if r["truth"]["severity"] == "complex"]
    high_sev_recall = (round(sum(1 for r in complex_cases if r["pred"]["severity"] == "complex")
                             / len(complex_cases), 3) if complex_cases else None)
    pred_green = [r for r in rows if r["pred"]["status"] == "green"]
    truth_green = [r for r in rows if r["truth"]["status"] == "green"]
    green_precision = (round(sum(1 for r in pred_green if r["truth"]["status"] == "green")
                             / len(pred_green), 3) if pred_green else None)
    green_recall = (round(sum(1 for r in truth_green if r["pred"]["status"] == "green")
                          / len(truth_green), 3) if truth_green else None)

    prec = round(correct / retrieved, 3) if retrieved else 0.0
    rec = round(correct / relevant, 3) if relevant else 0.0
    f1 = round(2 * prec * rec / (prec + rec), 3) if (prec + rec) else 0.0
    f_prec = round(f_tp / (f_tp + f_fp), 3) if (f_tp + f_fp) else None
    f_rec = round(f_tp / (f_tp + f_fn), 3) if (f_tp + f_fn) else None

    status_dist = {}
    for r in rows:
        status_dist[r["pred"]["status"]] = status_dist.get(r["pred"]["status"], 0) + 1

    return {
        "provider": provider_name,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_cases": n,
        "extraction": {"precision": prec, "recall": rec, "f1": f1},
        "classification": {
            "lob_accuracy": acc("lob", "lob"),
            "claim_type_accuracy": acc("claim_type", "claim_type"),
            "severity_accuracy": acc("severity", "severity"),
            "high_severity_recall": high_sev_recall,
        },
        "routing_accuracy": acc("queue", "queue"),
        "status_accuracy": acc("status", "status"),
        "green_precision": green_precision,
        "green_recall": green_recall,
        "flags": {"precision": f_prec, "recall": f_rec},
        "status_distribution": status_dist,
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)},
        "cost": {"total_usd": round(total_cost, 6), "per_document_usd": round(total_cost / n, 6) if n else 0},
        "cases": rows,
    }


def _print_summary(res: dict) -> None:
    print(f"\n=== EVAL: provider={res['provider']}  cases={res['n_cases']} ===")
    e = res["extraction"]
    print(f"extraction      P={e['precision']}  R={e['recall']}  F1={e['f1']}")
    c = res["classification"]
    print(f"classification  LOB={c['lob_accuracy']}  claim_type={c['claim_type_accuracy']}  "
          f"severity={c['severity_accuracy']}  high-sev-recall={c['high_severity_recall']}")
    print(f"routing accuracy (KEY)   {res['routing_accuracy']}")
    print(f"status accuracy          {res['status_accuracy']}")
    print(f"green precision (KEY)    {res['green_precision']}   green recall {res['green_recall']}")
    print(f"flags  P={res['flags']['precision']}  R={res['flags']['recall']}")
    print(f"status distribution      {res['status_distribution']}")
    print(f"latency p50/p95 (ms)     {res['latency_ms']['p50']} / {res['latency_ms']['p95']}")
    print(f"cost/doc                 ${res['cost']['per_document_usd']}  (total ${res['cost']['total_usd']})")
    mism = [r for r in res["cases"] if r["pred"]["queue"] != r["truth"]["queue"]]
    if mism:
        print("routing mismatches:")
        for r in mism:
            print(f"  {r['name']:30} pred={r['pred']['queue']:18} truth={r['truth']['queue']} ({r['ingestion']})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the triage pipeline.")
    parser.add_argument("--provider", choices=["mock", "openai"], default="mock")
    parser.add_argument("--out", default=str(ROOT / "eval/results"))
    args = parser.parse_args()

    res = run(args.provider)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (out_dir / f"eval_{args.provider}_{ts}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"eval_{args.provider}_latest.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(res)
    print(f"\nWrote results to {out_dir}/eval_{args.provider}_latest.json")


if __name__ == "__main__":
    main()
