"""Ingest a file and run extraction on it — a runnable slice of Stage 2.

Usage:
    uv run python -m scripts.extract samples/water_damage_ro.eml
    LLM_PROVIDER=openai uv run python -m scripts.extract samples/scan.pdf   # costs money

Defaults to the mock provider (free). Prints the ingestion decision and the
extracted fields as JSON.
"""
from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.ingest import ingest_path
from app.persistence import open_repository
from app.providers import get_provider
from app.workflow.schema import Thresholds


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest + extract a loss notification.")
    parser.add_argument("file")
    args = parser.parse_args()

    settings = get_settings()

    # Use the active config's thresholds if the DB is seeded; otherwise defaults.
    thresholds = Thresholds()
    try:
        cfg = open_repository().active_config()
        if cfg is not None:
            thresholds = cfg.thresholds
    except Exception:
        pass

    document, content = ingest_path(args.file, thresholds)
    print(f"provider:        {settings.llm_provider}")
    print(f"source_kind:     {document.source_kind.value}")
    print(f"ingestion_path:  {document.ingestion_path.value}")
    print(f"doc_hash:        {document.doc_hash[:16]}...")
    if document.num_pages:
        print(f"pages:           {document.num_pages}")
    print("-" * 60)

    provider = get_provider(settings)
    extraction = provider.extract(document, content)
    print(json.dumps(extraction.model_dump(exclude_none=True), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
