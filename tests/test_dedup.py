from __future__ import annotations

from app.models import FnolExtraction
from app.persistence.sqlite.dedup import find_possible_duplicates
from app.persistence.sqlite.schema import get_connection, init_db


def _insert_doc(conn, doc_hash, policy, loss_date, lob, claim_type):
    conn.execute(
        """INSERT INTO documents (doc_hash, filename, media_type, source_kind, size_bytes,
           received_at, ingestion_path, policy_number, loss_date, line_of_business, claim_type)
           VALUES (?, 'f.txt', 'text/plain', 'text', 1, '2025-10-10', 'text', ?, ?, ?, ?)""",
        (doc_hash, policy, loss_date, lob, claim_type),
    )
    conn.commit()


def test_dedup_matches_same_policy_date_and_type(tmp_path):
    conn = get_connection(str(tmp_path / "t.db"))
    init_db(conn)
    _insert_doc(conn, "aaaa1111" + "0" * 56, "PROP-1", "2025-10-06", "property", "water_damage")

    ext = FnolExtraction(policy_number="PROP-1", event_or_loss_date="2025-10-08")
    dups = find_possible_duplicates(conn, ext, "property", "water_damage", "self", window_days=7)
    assert len(dups) == 1
    assert dups[0]["claim_reference"] == "FNOL-AAAA1111"


def test_dedup_respects_date_window(tmp_path):
    conn = get_connection(str(tmp_path / "t.db"))
    init_db(conn)
    _insert_doc(conn, "b" * 64, "PROP-1", "2025-10-06", "property", "water_damage")
    ext = FnolExtraction(policy_number="PROP-1", event_or_loss_date="2025-10-20")  # 14 days
    assert find_possible_duplicates(conn, ext, "property", "water_damage", "self", 7) == []


def test_dedup_ignores_different_policy_or_type(tmp_path):
    conn = get_connection(str(tmp_path / "t.db"))
    init_db(conn)
    _insert_doc(conn, "c" * 64, "PROP-1", "2025-10-06", "property", "water_damage")
    ext = FnolExtraction(policy_number="PROP-2", event_or_loss_date="2025-10-06")
    assert find_possible_duplicates(conn, ext, "property", "water_damage", "self", 7) == []
    ext2 = FnolExtraction(policy_number="PROP-1", event_or_loss_date="2025-10-06")
    assert find_possible_duplicates(conn, ext2, "property", "fire", "self", 7) == []


def test_dedup_requires_policy(tmp_path):
    conn = get_connection(str(tmp_path / "t.db"))
    init_db(conn)
    _insert_doc(conn, "d" * 64, "PROP-1", "2025-10-06", "property", "water_damage")
    ext = FnolExtraction(event_or_loss_date="2025-10-06")  # no policy -> don't guess
    assert find_possible_duplicates(conn, ext, "property", "water_damage", "self", 7) == []
