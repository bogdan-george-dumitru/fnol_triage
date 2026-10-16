"""Initialise the database and install the starter workflow config as version 1.

Usage:
    uv run python -m scripts.seed [--db data/app.db]

Idempotent-ish: re-running adds another version of the starter config and makes
it active. The starter config is deterministic, so versions are identical content.
"""
from __future__ import annotations

import argparse

from app.config import get_settings
from app.persistence import open_repository
from app.policy import build_policies
from app.workflow.seed import build_starter_config


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Seed the DB with the starter config.")
    parser.add_argument("--db", default=settings.db_path)
    args = parser.parse_args()

    repo = open_repository(args.db, init=True)
    try:
        config = build_starter_config()
        errors = config.validate_references()
        if errors:
            raise SystemExit("Starter config is invalid:\n  - " + "\n  - ".join(errors))
        version = repo.save_version(
            config, author="seed", label="Starter config (Home/Property + Life CPI)"
        )
        n_pol = repo.replace_policies(build_policies())
        lobs = ", ".join(lob.key for lob in config.lines_of_business)
        print(f"Installed workflow config version {version} (active) into {args.db}")
        print(f"  lines of business: {lobs}")
        print(f"  queues: {len(config.queues)}, flags: {len(config.flag_rules)}, "
              f"routing rules: {len(config.routing_rules)}, templates: {len(config.templates)}")
        print(f"  policies (simulated master): {n_pol}")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
