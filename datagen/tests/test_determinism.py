"""Same seed -> byte-identical output. Required for `make datagen` to be
reproducible from a clean checkout, per the Phase 2 DONE WHEN check."""

from datetime import timedelta

from synthgen.calendar_utils import REFERENCE_DATE
from synthgen.documents import gig_payout
from synthgen.identity import make_persona
from synthgen.rng import derive_seed, rng_for


def test_derive_seed_is_stable():
    assert derive_seed("ns", "key") == derive_seed("ns", "key")
    assert derive_seed("ns", "key1") != derive_seed("ns", "key2")


def test_identity_is_deterministic():
    p1 = make_persona("GIG_PAYOUT", 7)
    p2 = make_persona("GIG_PAYOUT", 7)
    assert p1 == p2


def test_build_weeks_is_deterministic():
    weeks1 = gig_payout.build_weeks(rng_for("test", "weeks"), 12, 5.0, 0.2)
    weeks2 = gig_payout.build_weeks(rng_for("test", "weeks"), 12, 5.0, 0.2)
    assert weeks1 == weeks2


def test_render_is_byte_identical_across_runs():
    persona = make_persona("GIG_PAYOUT", 99)
    partner_since = REFERENCE_DATE - timedelta(weeks=40)

    def render_once():
        weeks = gig_payout.build_weeks(rng_for("determinism_test", "img"), 12, 5.0, 0.2)
        img, _ = gig_payout.render(persona, "ride", "ZIP-TEST", partner_since, weeks, "1234")
        return img.tobytes()

    assert render_once() == render_once()
