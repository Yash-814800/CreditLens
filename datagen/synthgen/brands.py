"""Fictional brand identities used across every generated document.

Real brands (Swiggy, Uber, actual DISCOMs, real banks) are never used, per
CLAUDE.md rule 4 (no fake results / label everything synthetic) and the
prompt pack's explicit instruction. These names are deliberately generic
enough to be obviously fictional while still reading as plausible Indian
gig-platform / utility / bank names.
"""

from __future__ import annotations

GIG_PLATFORMS = {
    "ride": {
        "name": "ZipRide Partner",
        "role_label": "Driver Partner",
        "activity_label": "trips",
    },
    "food": {
        "name": "FoodDash Partner",
        "role_label": "Delivery Partner",
        "activity_label": "orders",
    },
}

UTILITY_NAME = "Bharat Power Distribution (Demo)"
UTILITY_SHORT = "BPD (Demo)"

BANK_NAME = "Demo Sahakari Bank"
BANK_IFSC_PREFIX = "DEMO0"

SYNTHETIC_FOOTER = "SYNTHETIC SAMPLE — generated for CreditLens demo. Not a real document."
