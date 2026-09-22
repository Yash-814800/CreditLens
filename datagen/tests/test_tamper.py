import io
from datetime import timedelta

import numpy as np
from PIL import Image

from synthgen import tamper
from synthgen.calendar_utils import REFERENCE_DATE
from synthgen.documents import gig_payout, utility_bill
from synthgen.identity import make_persona
from synthgen.rng import rng_for


def _region_diff(a: Image.Image, b: Image.Image, bbox) -> float:
    box = tuple(int(v) for v in bbox)
    ra = np.array(a.crop(box)).astype(int)
    rb = np.array(b.crop(box)).astype(int)
    assert ra.shape == rb.shape
    return float(np.abs(ra - rb).mean())


def test_gig_payout_tamper_types_change_the_patched_region():
    persona = make_persona("GIG_PAYOUT", 501)
    partner_since = REFERENCE_DATE - timedelta(weeks=40)
    for idx, tamper_type in enumerate(tamper.IMAGE_TAMPER_TYPES):
        rng = rng_for("test_tamper_gig", tamper_type)
        weeks = gig_payout.build_weeks(rng_for("test_tamper_gig_weeks", idx), 12, 5.0, 0.2)
        img, bboxes = gig_payout.render(persona, "ride", "ZIP-TEST", partner_since, weeks, "1234")

        img_bytes, vf, events, meta_stamp = tamper.tamper_gig_payout(
            rng,
            img,
            bboxes,
            weeks,
            "ride",
            persona.full_name,
            "ZIP-TEST",
            partner_since,
            "1234",
            tamper_type,
        )
        assert len(events) == 1
        tampered_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        if tamper_type == "metadata_stamp":
            assert meta_stamp is not None
            assert events[0].bbox is None
        else:
            assert meta_stamp is None
            assert events[0].bbox is not None
            assert _region_diff(img, tampered_img, events[0].bbox) > 1.0


def test_utility_bill_tamper_types_change_the_patched_region():
    for idx, tamper_type in enumerate(tamper.IMAGE_TAMPER_TYPES):
        persona = make_persona("UTILITY_BILL", 601 + idx)
        rng = rng_for("test_tamper_bill", tamper_type)
        build_rng = rng_for("test_tamper_bill_build", idx)
        bill = utility_bill.build_bill_data(build_rng, persona, 12, 0.9, f"CN{idx}", f"MT{idx}")
        img, bboxes = utility_bill.render_image(bill)

        img_bytes, vf, events, meta_stamp = tamper.tamper_utility_bill(rng, img, bboxes, bill, tamper_type)
        assert len(events) == 1
        tampered_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        if tamper_type == "metadata_stamp":
            assert meta_stamp is not None
        else:
            assert events[0].bbox is not None
            assert _region_diff(img, tampered_img, events[0].bbox) > 1.0


def test_edited_total_only_leaves_line_items_summing_to_the_old_total():
    persona = make_persona("UTILITY_BILL", 900)
    rng = rng_for("test_edited_total_only", "main")
    bill = utility_bill.build_bill_data(rng, persona, 12, 0.9, "CN900", "MT900")
    img, bboxes = utility_bill.render_image(bill)
    old_total = bill.total_amount_due

    _, vf, events, _ = tamper.tamper_utility_bill(rng, img, bboxes, bill, "edited_total_only")
    line_item_sum = round(sum(li["amount"] for li in vf["line_items"]), 2)
    assert abs(line_item_sum - old_total) < 1.0  # line items still sum to the OLD total
    assert abs(vf["total_amount_due"] - old_total) > 1.0  # displayed total is now wrong


def test_consistent_edit_line_items_and_total_agree_hard_case():
    persona = make_persona("UTILITY_BILL", 901)
    rng = rng_for("test_consistent_edit", "main")
    bill = utility_bill.build_bill_data(rng, persona, 12, 0.9, "CN901", "MT901")
    img, bboxes = utility_bill.render_image(bill)

    _, vf, _, _ = tamper.tamper_utility_bill(rng, img, bboxes, bill, "consistent_edit")
    line_item_sum = round(sum(li["amount"] for li in vf["line_items"]), 2)
    assert abs(line_item_sum - vf["total_amount_due"]) < 1.0  # internally consistent, unlike edited_total_only
