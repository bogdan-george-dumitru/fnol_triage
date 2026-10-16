"""The provider interface.

Two backends implement it (OpenAI and mock). The interface is deliberately small:
the AI only *extracts* and *classifies*. Routing, flag firing, severity floors and
template filling are deterministic code (Stages 3-4), not the model's job.

Both methods are declared here from the start to document the contract; they get
concrete implementations in Stage 2 (extract) and Stage 3 (classify).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.config import Settings
from app.models import Classification, FnolExtraction, IngestedDocument
from app.workflow.schema import WorkflowConfig


class LLMProvider(ABC):
    """One interface, two backends (OpenAI and mock baseline)."""

    name: str = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def extract(self, document: IngestedDocument, content: bytes) -> FnolExtraction:
        """Extract structured FNOL fields from an ingested loss notification.

        `content` is the original bytes, needed for the vision path (scanned or
        handwritten documents). Text-path providers use `document.text`.
        """
        raise NotImplementedError

    @abstractmethod
    def classify(
        self, extraction: FnolExtraction, config: WorkflowConfig
    ) -> Classification:
        """Classify LOB, claim type and severity, and suggest advisory flags,
        using the business-owned taxonomy/examples in `config`."""
        raise NotImplementedError
