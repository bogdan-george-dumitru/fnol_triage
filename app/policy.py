"""Simulated policy master — the DOMAIN half.

The `Policy` entity and a small deterministic seed. In a real deployment the triage
layer would verify the policy against the insurer's policy system; here the seed is
chosen so the policy-dependent checks (contestability, loss-near-inception,
sum-insured, in-force status) are meaningful in demos.

Storage (the `policies` table: `get_policy` / `replace_policies`) lives in the SQLite
adapter (`app.persistence.sqlite.policies`), behind the repository port — this module
has no database dependency.
"""
from __future__ import annotations

from pydantic import BaseModel


class Policy(BaseModel):
    policy_number: str
    product: str  # "property" | "life_cpi"
    holder_name: str
    inception_date: str  # ISO date
    status: str  # "in_force" | "lapsed" | "cancelled"
    sum_insured: float
    currency: str = "RON"


# Deterministic seed. A couple are chosen to exercise edge cases:
#  - PROP-2024-778310 inception 2025-09-20 vs loss 2025-10-08 -> within 30 days
#    => fraud-near-inception flag fires.
#  - CPI-2023-900341 inception 2023-05-01 vs death 2025-10-02 -> ~888 days
#    => OUTSIDE the 730-day contestability window (a normal death claim).
_SEED: list[Policy] = [
    Policy(policy_number="PROP-2024-558120", product="property", holder_name="Maria Ionescu",
           inception_date="2024-03-15", status="in_force", sum_insured=350000.0),
    Policy(policy_number="PROP-2024-331050", product="property", holder_name="Vasile Dumitrescu",
           inception_date="2024-07-01", status="in_force", sum_insured=500000.0),
    Policy(policy_number="PROP-2024-778310", product="property", holder_name="Ion Petre",
           inception_date="2025-09-20", status="in_force", sum_insured=400000.0),
    Policy(policy_number="CPI-2025-114977", product="life_cpi", holder_name="Andrei Popescu",
           inception_date="2025-01-10", status="in_force", sum_insured=80000.0),
    Policy(policy_number="CPI-2023-900341", product="life_cpi", holder_name="Gheorghe Marin",
           inception_date="2023-05-01", status="in_force", sum_insured=200000.0),
    # An extra lapsed policy to exercise the not-in-force path.
    Policy(policy_number="PROP-2022-100200", product="property", holder_name="Dan Georgescu",
           inception_date="2022-02-01", status="lapsed", sum_insured=250000.0),
]


def build_policies() -> list[Policy]:
    return list(_SEED)
