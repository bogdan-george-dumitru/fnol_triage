"""Domain-level exceptions."""
from __future__ import annotations


class ExtractionError(Exception):
    """Extraction failed (schema-invalid after retry, refusal, or no content).

    The pipeline turns this into a 🔴 red / manual-intake status rather than a
    confident but wrong proposal.
    """
