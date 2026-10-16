from __future__ import annotations

import hashlib

from app.ingest import ingest, text_layer_quality
from app.models import IngestionPath, SourceKind
from app.workflow.schema import Thresholds


def test_txt_ingest_sets_text_path() -> None:
    data = "Poliță nr. PROP-1 daună de apă".encode("utf-8")
    doc = ingest("note.txt", data)
    assert doc.source_kind == SourceKind.text
    assert doc.ingestion_path == IngestionPath.text
    assert doc.text and "PROP-1" in doc.text
    assert doc.doc_hash == hashlib.sha256(data).hexdigest()


def test_eml_ingest_extracts_subject_and_body() -> None:
    eml = (
        b"From: a@b.ro\r\nTo: daune@x.ro\r\nSubject: Notificare\r\n\r\n"
        b"S-a spart o teava si s-a inundat."
    )
    doc = ingest("msg.eml", eml)
    assert doc.source_kind == SourceKind.email
    assert doc.ingestion_path == IngestionPath.text
    assert "Notificare" in doc.text
    assert "inundat" in doc.text


def test_eml_utf8_body_without_declared_charset() -> None:
    # No Content-Type charset header -> must still decode UTF-8 diacritics correctly.
    eml = (
        "From: a@b.ro\r\nTo: daune@x.ro\r\nSubject: Notificare\r\n\r\n"
        "Poliță nr. PROP-2024-558120, s-a inundat apartamentul."
    ).encode("utf-8")
    doc = ingest("msg.eml", eml)
    assert "�" not in doc.text  # no replacement chars
    assert "Poliță" in doc.text
    assert "PROP-2024-558120" in doc.text


def test_image_goes_to_vision() -> None:
    doc = ingest("photo.jpg", b"\xff\xd8\xff\xe0 not really a jpeg")
    assert doc.source_kind == SourceKind.image
    assert doc.ingestion_path == IngestionPath.vision
    assert doc.text is None


def test_same_bytes_same_hash_idempotency() -> None:
    data = b"identical content"
    assert ingest("a.txt", data).doc_hash == ingest("b.txt", data).doc_hash


def test_text_layer_heuristic_flags_scanned() -> None:
    th = Thresholds()
    # almost no text on one page -> not usable (likely scan)
    scanned = text_layer_quality("x", 1, th)
    assert not scanned.usable and "scanned" in scanned.reason.lower()

    good = text_layer_quality("A" * 500, 1, th)
    assert good.usable


def test_text_layer_heuristic_flags_garbage() -> None:
    th = Thresholds()
    junk = "�" * 300  # replacement chars, enough chars/page but garbage
    assessment = text_layer_quality(junk, 1, th)
    assert not assessment.usable
    assert assessment.garbage_ratio > th.text_layer_max_garbage_ratio
