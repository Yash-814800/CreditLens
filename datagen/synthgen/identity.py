"""Synthetic per-document applicant identities for the bulk fraud-eval corpus.

Distinct from the hand-crafted demo personas P01-P08 (see personas.py), which
carry target *signals* for pipeline testing. These are throwaway fictional
identities that only need to look plausible on a document.
"""

from __future__ import annotations

from faker import Faker

from synthgen.rng import derive_seed
from synthgen.schemas import PersonaMeta

_VOCATIONS = [
    "ride-hailing driver",
    "food delivery partner",
    "grocery delivery partner",
    "auto-rickshaw driver",
    "cab driver",
]

_CITIES = [
    ("Whitefield, Bengaluru", "560066"),
    ("Andheri East, Mumbai", "400069"),
    ("Kothrud, Pune", "411038"),
    ("Sector 62, Noida", "201309"),
    ("Velachery, Chennai", "600042"),
    ("Banjara Hills, Hyderabad", "500034"),
    ("Salt Lake, Kolkata", "700091"),
]


def make_persona(doc_type: str, index: int) -> PersonaMeta:
    seed = derive_seed("identity", f"{doc_type}:{index}")
    fake = Faker("en_IN")
    fake.seed_instance(seed)
    area, pincode = fake.random_element(_CITIES)
    full_name = fake.name()
    persona_id = f"SYN-{doc_type[:3]}-{index:04d}"
    return PersonaMeta(
        persona_id=persona_id,
        full_name=full_name,
        phone=f"9{fake.random_number(digits=9, fix_len=True)}",
        declared_address=f"{fake.building_number()}, {area} - {pincode}",
        stated_vocation=fake.random_element(_VOCATIONS),
    )
