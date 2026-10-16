"""Run the full triage pipeline on a file and print the proposal.

Usage:
    uv run python -m scripts.triage samples/water_damage_ro.eml
    LLM_PROVIDER=openai uv run python -m scripts.triage samples/handwritten_property_ro.png

Defaults to the mock provider (free). Requires a seeded DB (scripts.seed).
"""
from __future__ import annotations

import argparse

from app.config import get_settings
from app.ingest import ingest_path
from app.persistence import open_repository
from app.pipeline import triage
from app.providers import get_provider

_STATUS_ICON = {"green": "🟢", "amber": "🟡", "red": "🔴"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage a loss notification end to end.")
    parser.add_argument("file")
    args = parser.parse_args()

    settings = get_settings()
    repo = open_repository()
    config = repo.active_config()
    if config is None:
        raise SystemExit("No active config. Run: uv run python -m scripts.seed")
    version = repo.active_version()

    document, content = ingest_path(args.file, config.thresholds)
    provider = get_provider(settings)
    proposal = triage(document, content, provider, config, repo=repo, config_version=version)

    icon = _STATUS_ICON.get(proposal.status.value, "?")
    print(f"{icon}  {proposal.status.value.upper()}   {args.file}")
    print(f"provider={settings.llm_provider}  ingestion={document.ingestion_path.value}  "
          f"config_v={proposal.config_version}")
    print("-" * 68)
    print(f"claim ref:   {proposal.claim_reference}")
    print(f"LOB / type:  {proposal.line_of_business} / {proposal.claim_type}")
    print(f"severity:    {proposal.severity.value if proposal.severity else '-'}")
    print(f"queue:       {proposal.queue_label}  (SLA {proposal.sla_hours}h)")
    if proposal.classification:
        print(f"confidence:  {proposal.classification.confidence:.0%}")
    if proposal.alternatives:
        print(f"alternatives: {', '.join(proposal.alternatives)}")

    pc = proposal.policy_check
    if pc:
        if pc.found:
            print(f"policy:      {pc.policy_number} — {pc.status}, {pc.product}, "
                  f"inception {pc.inception_date}, sum insured {pc.sum_insured:.0f} {pc.currency}")
        else:
            print(f"policy:      {pc.policy_number or '-'} — NOT FOUND")

    if proposal.flags:
        print("flags:")
        for f in proposal.flags:
            print(f"   ⚑ {f.key}: {f.message}")
    if proposal.reasons:
        print("reasons:")
        for r in proposal.reasons:
            print(f"   • {r}")
    if proposal.draft:
        print("-" * 68)
        print(f"draft ack ({proposal.draft.language}) — {proposal.draft.subject}")
        print(proposal.draft.body)


if __name__ == "__main__":
    main()
