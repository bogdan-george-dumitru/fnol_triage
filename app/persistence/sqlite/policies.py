"""SQLite adapter: the simulated policy master (`policies` table)."""
from __future__ import annotations

import sqlite3

from app.policy import Policy


def replace_policies(conn: sqlite3.Connection, policies: list[Policy]) -> int:
    conn.execute("DELETE FROM policies")
    conn.executemany(
        "INSERT INTO policies (policy_number, product, holder_name, inception_date, "
        "status, sum_insured, currency) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (p.policy_number, p.product, p.holder_name, p.inception_date, p.status,
             p.sum_insured, p.currency)
            for p in policies
        ],
    )
    conn.commit()
    return len(policies)


def get_policy(conn: sqlite3.Connection, policy_number: str | None) -> Policy | None:
    if not policy_number:
        return None
    row = conn.execute(
        "SELECT * FROM policies WHERE policy_number = ?", (policy_number,)
    ).fetchone()
    if row is None:
        return None
    return Policy(
        policy_number=row["policy_number"],
        product=row["product"],
        holder_name=row["holder_name"],
        inception_date=row["inception_date"],
        status=row["status"],
        sum_insured=row["sum_insured"],
        currency=row["currency"],
    )
