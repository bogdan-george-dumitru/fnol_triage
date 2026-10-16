"""Ingest: turn an uploaded file into an `IngestedDocument`.

Decides the ingestion path per the brief:
  - .txt / .eml           -> read text directly
  - .pdf with text layer  -> pypdf extracts usable text (cheap/fast)
  - .pdf without a usable text layer, .png/.jpg -> vision (handled at extraction)

The text-layer decision is a documented, TUNABLE heuristic (`text_layer_quality`)
driven by the business config thresholds, and it errs toward vision/human when
uncertain (a wasted vision call is cheaper than a silently wrong claim).
"""
from __future__ import annotations

import email
import hashlib
import io
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from pathlib import Path

from pypdf import PdfReader

from app.models import IngestedDocument, IngestionPath, SourceKind
from app.workflow.schema import Thresholds

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff"}


@dataclass
class TextLayerAssessment:
    usable: bool
    chars_per_page: float
    garbage_ratio: float
    reason: str


def text_layer_quality(
    text: str | None, num_pages: int | None, thresholds: Thresholds
) -> TextLayerAssessment:
    """Judge whether an extracted PDF text layer is good enough to trust.

    Signals (all cheap, no model call):
      - chars-per-page: too few => almost certainly a scan.
      - garbage ratio: replacement/control chars from broken font extraction.
    """
    text = text or ""
    pages = max(num_pages or 1, 1)
    total = len(text)
    chars_per_page = total / pages

    if total:
        bad = sum(
            1
            for c in text
            if ord(c) == 0xFFFD or (not c.isprintable() and not c.isspace())
        )
        garbage_ratio = bad / total
    else:
        garbage_ratio = 1.0

    if chars_per_page < thresholds.text_layer_min_chars_per_page:
        return TextLayerAssessment(
            False, chars_per_page, garbage_ratio,
            f"too little text ({chars_per_page:.0f} chars/page < "
            f"{thresholds.text_layer_min_chars_per_page}) — likely scanned",
        )
    if garbage_ratio > thresholds.text_layer_max_garbage_ratio:
        return TextLayerAssessment(
            False, chars_per_page, garbage_ratio,
            f"garbled text ({garbage_ratio:.0%} junk > "
            f"{thresholds.text_layer_max_garbage_ratio:.0%})",
        )
    return TextLayerAssessment(True, chars_per_page, garbage_ratio, "usable text layer")


def _eml_to_text(data: bytes) -> str:
    msg = email.message_from_bytes(data, policy=policy.default)
    parts: list[str] = []
    subject = msg.get("subject")
    if subject:
        parts.append(f"Subject: {subject}")
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
        if body is not None:
            content = _decode_part(body)
            if body.get_content_type() == "text/html":
                content = _strip_html(content)
            parts.append(content)
        else:  # no structured body; fall back to raw payload
            parts.append(data.decode("utf-8", errors="replace"))
    except Exception:
        parts.append(data.decode("utf-8", errors="replace"))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _decode_part(part) -> str:
    """Decode a message part from its raw bytes.

    Email parts without a declared charset are assumed us-ascii by the stdlib,
    which mangles UTF-8 Romanian diacritics. Decode the raw payload ourselves,
    honouring a declared charset but defaulting to UTF-8.
    """
    payload = part.get_payload(decode=True)
    if payload is None:
        return part.get_content()
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    import re

    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _pdf_text(data: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(data))
    pages = reader.pages
    text = "\n".join((page.extract_text() or "") for page in pages)
    return text, len(pages)


def _source_kind(ext: str) -> SourceKind:
    if ext == ".eml":
        return SourceKind.email
    if ext == ".pdf":
        return SourceKind.pdf
    if ext in IMAGE_EXTS:
        return SourceKind.image
    return SourceKind.text


def ingest(
    filename: str, data: bytes, thresholds: Thresholds | None = None
) -> IngestedDocument:
    """Ingest raw bytes into an `IngestedDocument`. `doc_hash` is the idempotency key."""
    thresholds = thresholds or Thresholds()
    ext = Path(filename).suffix.lower()
    kind = _source_kind(ext)
    doc_hash = hashlib.sha256(data).hexdigest()
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    text: str | None = None
    num_pages: int | None = None
    path = IngestionPath.none

    if kind in (SourceKind.text, SourceKind.email):
        if kind == SourceKind.email:
            text = _eml_to_text(data)
        else:
            text = data.decode("utf-8", errors="replace").strip()
        path = IngestionPath.text if text else IngestionPath.none
    elif kind == SourceKind.pdf:
        try:
            extracted, num_pages = _pdf_text(data)
        except Exception:
            extracted, num_pages = "", None
        assessment = text_layer_quality(extracted, num_pages, thresholds)
        if assessment.usable:
            text = extracted.strip()
            path = IngestionPath.pdf_text_layer
        else:
            path = IngestionPath.vision  # scanned/handwritten -> vision at extraction
    elif kind == SourceKind.image:
        path = IngestionPath.vision

    return IngestedDocument(
        doc_hash=doc_hash,
        filename=filename,
        media_type=media_type,
        source_kind=kind,
        size_bytes=len(data),
        received_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ingestion_path=path,
        text=text,
        num_pages=num_pages,
    )


def ingest_path(path: str, thresholds: Thresholds | None = None) -> tuple[IngestedDocument, bytes]:
    """Convenience: read a file and ingest it. Returns the document and raw bytes."""
    data = Path(path).read_bytes()
    return ingest(Path(path).name, data, thresholds), data
