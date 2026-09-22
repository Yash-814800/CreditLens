"""Tamper injection for the fraud-eval corpus.

Design note on image tampering (GIG_PAYOUT screenshots, UTILITY_BILL images):
rather than re-rendering the whole document with one field changed (which
would give the entire image a single, uniform compression history and hide
any localized forensic signature), every tamper here PATCHES a specific
region of an already-once-compressed image and then re-compresses the whole
thing a second time. Untouched pixels have gone through two JPEG generations
(quality 90, then quality 78); the patched region has gone through only the
second. That is the standard, textbook setup for Error Level Analysis to have
something real to find in Phase 4 -- not a decorative detail.

Design note on `consistent_edit` and `inserted_fake_credit_with_rebalanced_chain`:
these are deliberately built to be internally arithmetic-consistent (the
"hard case" the Phase 4 evaluation harness is required to report honestly on).
"""

from __future__ import annotations

import copy
import io
from dataclasses import replace
from datetime import timedelta

import numpy as np
from PIL import Image, ImageDraw

from synthgen.documents.bank_statement import Txn
from synthgen.documents.gig_payout import WeekRow
from synthgen.documents.gig_payout import to_visible_fields as gig_to_visible_fields
from synthgen.documents.utility_bill import BillData
from synthgen.documents.utility_bill import to_visible_fields as bill_to_visible_fields
from synthgen.fonts import font as get_font
from synthgen.format_utils import fmt_inr
from synthgen.schemas import TamperEvent

IMAGE_TAMPER_TYPES = [
    "amount_edit",
    "date_shift",
    "font_swap",
    "row_clone",
    "edited_total_only",
    "consistent_edit",
    "metadata_stamp",
]
BANK_TAMPER_TYPES = [
    "edited_credit_without_rebalancing",
    "inserted_fake_credit_with_rebalanced_chain",
]

METADATA_STAMP_TOOLS = ["Adobe Photoshop 25.0 (Windows)", "GIMP 2.10.36", "Canva Editor Export"]

GEN1_QUALITY = 90
GEN2_QUALITY = 78


def _round_trip_jpeg(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _jpeg_bytes(img: Image.Image, quality: int, *, software: str | None = None) -> bytes:
    """`software`, when given, is written into the real EXIF Software tag (id
    0x0131) -- this is what makes the `metadata_stamp` tamper type an actual
    forensic artifact Phase 4's metadata_forensics check can read back out of
    the file bytes, not just a label that only ever existed in truth.json."""
    buf = io.BytesIO()
    save_kwargs: dict = {}
    if software is not None:
        exif = Image.Exif()
        exif[0x0131] = software  # 0x0131 = EXIF "Software" tag
        save_kwargs["exif"] = exif
    img.convert("RGB").save(buf, format="JPEG", quality=quality, **save_kwargs)
    return buf.getvalue()


def _patch_text(
    img: Image.Image, entry: dict, new_text: str, font_family: str | None = None, pad: int = 6
) -> list[int]:
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = entry["bbox"]
    rect = [x0 - pad, y0 - pad, x1 + pad, y1 + pad]
    d.rectangle(rect, fill=entry["bg"])
    f = entry["font"]
    if font_family:
        f = get_font(font_family, f.size)
    d.text((x0, y0), new_text, font=f, fill=entry["fill"])
    return rect


def _patch_row_clone(img: Image.Image, src_entry: dict, dst_entry: dict) -> list[int]:
    x0, y0, x1, y1 = src_entry["bbox"]
    region = img.crop((x0, y0, x1, y1))
    dx0, dy0, dx1, dy1 = dst_entry["bbox"]
    if (x1 - x0, y1 - y0) != (dx1 - dx0, dy1 - dy0):
        region = region.resize((dx1 - dx0, dy1 - dy0))
    img.paste(region, (dx0, dy0))
    return [dx0, dy0, dx1, dy1]


def _union_bbox(a: list[int], b: list[int]) -> list[int]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def tamper_gig_payout(
    rng: np.random.Generator,
    clean_img: Image.Image,
    bboxes: dict,
    weeks: list[WeekRow],
    platform_key: str,
    partner_name: str,
    partner_id: str,
    partner_since,
    payout_account_last4: str,
    tamper_type: str,
) -> tuple[bytes, dict, list[TamperEvent], str | None]:
    gen1 = _round_trip_jpeg(clean_img, GEN1_QUALITY)
    img = gen1.copy()
    weeks2 = list(weeks)
    events: list[TamperEvent] = []
    metadata_stamp: str | None = None
    n = len(weeks)
    override_total: float | None = None

    if tamper_type == "amount_edit":
        i = int(rng.integers(0, n))
        old = weeks[i].net_payout
        sign = 1 if rng.random() < 0.5 else -1
        new_val = round(old + sign * old * float(rng.uniform(0.12, 0.35)), 2)
        weeks2[i] = replace(weeks2[i], net_payout=new_val)
        bbox = _patch_text(img, bboxes[f"week_net_{i}"], f"₹{new_val:,.2f}")
        events.append(
            TamperEvent(
                type="amount_edit",
                field=f"weeks[{i}].net_payout",
                original=old,
                tampered=new_val,
                bbox=bbox,
            )
        )

    elif tamper_type == "date_shift":
        i = int(rng.integers(0, n))
        shift = int(rng.choice([-3, -2, -1, 1, 2, 3, 4, 5]))
        old_start, old_end = weeks[i].week_start, weeks[i].week_end
        new_start, new_end = old_start + timedelta(days=shift), old_end + timedelta(days=shift)
        weeks2[i] = replace(weeks2[i], week_start=new_start, week_end=new_end)
        label = f"{new_start.strftime('%d %b')} – {new_end.strftime('%d %b')}"
        bbox = _patch_text(img, bboxes[f"week_range_{i}"], label)
        events.append(
            TamperEvent(
                type="date_shift",
                field=f"weeks[{i}].week_start_end",
                original=[old_start.isoformat(), old_end.isoformat()],
                tampered=[new_start.isoformat(), new_end.isoformat()],
                bbox=bbox,
            )
        )

    elif tamper_type == "font_swap":
        entry = bboxes["partner_since"]
        text = f"Partner since: {partner_since.isoformat()}"
        bbox = _patch_text(img, entry, text, font_family="tamper")
        events.append(
            TamperEvent(
                type="font_swap",
                field="partner_since",
                original=partner_since.isoformat(),
                tampered=partner_since.isoformat(),
                bbox=bbox,
            )
        )

    elif tamper_type == "row_clone":
        i, j = (int(x) for x in rng.choice(n, size=2, replace=False))
        bbox = _patch_row_clone(img, bboxes[f"row_rect_{i}"], bboxes[f"row_rect_{j}"])
        original_desc = f"{weeks[j].week_start.isoformat()}..{weeks[j].week_end.isoformat()}"
        weeks2[j] = weeks[i]
        tampered_desc = f"{weeks[i].week_start.isoformat()}..{weeks[i].week_end.isoformat()} (duplicate of week {i})"
        events.append(
            TamperEvent(
                type="row_clone",
                field=f"weeks[{j}]",
                original=original_desc,
                tampered=tampered_desc,
                bbox=bbox,
            )
        )

    elif tamper_type == "edited_total_only":
        old_total = round(sum(w.net_payout for w in weeks), 2)
        new_total = round(old_total * float(rng.uniform(1.1, 1.3)), 2)
        bbox = _patch_text(img, bboxes["period_total"], f"₹{new_total:,.2f}")
        override_total = new_total
        events.append(
            TamperEvent(
                type="edited_total_only",
                field="total_net_payout_period",
                original=old_total,
                tampered=new_total,
                bbox=bbox,
            )
        )

    elif tamper_type == "consistent_edit":
        i = int(rng.integers(0, n))
        old = weeks[i]
        delta = round(old.net_payout * float(rng.uniform(0.15, 0.3)), 2)
        new_gross = round(old.gross_earnings + delta, 2)
        new_net = round(new_gross + old.incentives - old.deductions, 2)
        weeks2[i] = replace(weeks2[i], gross_earnings=new_gross, net_payout=new_net)
        b1 = _patch_text(img, bboxes[f"week_gross_{i}"], f"Gross ₹{new_gross:,.2f}")
        b2 = _patch_text(img, bboxes[f"week_net_{i}"], f"₹{new_net:,.2f}")
        new_total = round(sum(w.net_payout for w in weeks2), 2)
        b3 = _patch_text(img, bboxes["period_total"], f"₹{new_total:,.2f}")
        events.append(
            TamperEvent(
                type="consistent_edit",
                field=f"weeks[{i}].gross_earnings+net_payout+total",
                original=[old.gross_earnings, old.net_payout],
                tampered=[new_gross, new_net],
                bbox=_union_bbox(_union_bbox(b1, b2), b3),
            )
        )

    elif tamper_type == "metadata_stamp":
        metadata_stamp = str(rng.choice(METADATA_STAMP_TOOLS))
        events.append(
            TamperEvent(
                type="metadata_stamp",
                field="_file_metadata",
                original="none",
                tampered=metadata_stamp,
            )
        )

    else:
        raise ValueError(f"unknown gig_payout tamper type {tamper_type!r}")

    final_bytes = _jpeg_bytes(img, GEN2_QUALITY, software=metadata_stamp)
    vf = gig_to_visible_fields(platform_key, partner_name, partner_id, partner_since, weeks2, payout_account_last4)
    if override_total is not None:
        vf["total_net_payout_period"] = override_total
    return final_bytes, vf, events, metadata_stamp


def tamper_utility_bill(
    rng: np.random.Generator,
    clean_img: Image.Image,
    bboxes: dict,
    bill: BillData,
    tamper_type: str,
) -> tuple[bytes, dict, list[TamperEvent], str | None]:
    gen1 = _round_trip_jpeg(clean_img, GEN1_QUALITY)
    img = gen1.copy()
    bill2 = copy.deepcopy(bill)
    events: list[TamperEvent] = []
    metadata_stamp: str | None = None

    if tamper_type == "amount_edit":
        idx = int(rng.integers(0, len(bill.line_items)))
        label, old_amt = bill.line_items[idx]
        new_amt = round(old_amt * float(rng.uniform(1.2, 1.6)), 2)
        bill2.line_items[idx] = (label, new_amt)
        bbox = _patch_text(img, bboxes[f"line_item_{idx}"], fmt_inr(new_amt))
        events.append(
            TamperEvent(
                type="amount_edit",
                field=f"line_items[{idx}].amount",
                original=old_amt,
                tampered=new_amt,
                bbox=bbox,
            )
        )

    elif tamper_type == "date_shift":
        old_due = bill.due_date
        shift = int(rng.choice([-10, -7, 5, 8, 12]))
        new_due = old_due + timedelta(days=shift)
        bill2.due_date = new_due
        bbox = _patch_text(img, bboxes["due_date"], f"Due date: {new_due.isoformat()}")
        events.append(
            TamperEvent(
                type="date_shift",
                field="due_date",
                original=old_due.isoformat(),
                tampered=new_due.isoformat(),
                bbox=bbox,
            )
        )

    elif tamper_type == "font_swap":
        text = f"Consumer name: {bill.consumer_name}"
        bbox = _patch_text(img, bboxes["consumer_name"], text, font_family="tamper")
        events.append(
            TamperEvent(
                type="font_swap",
                field="consumer_name",
                original=bill.consumer_name,
                tampered=bill.consumer_name,
                bbox=bbox,
            )
        )

    elif tamper_type == "row_clone":
        n = len(bill.payment_history)
        i, j = (int(x) for x in rng.choice(n, size=2, replace=False))
        bbox = _patch_row_clone(img, bboxes[f"history_row_rect_{i}"], bboxes[f"history_row_rect_{j}"])
        original_desc = f"{bill.payment_history[j].month_label}/{bill.payment_history[j].status}"
        bill2.payment_history[j] = bill.payment_history[i]
        tampered_desc = f"duplicate of row {i} ({bill.payment_history[i].month_label})"
        events.append(
            TamperEvent(
                type="row_clone",
                field=f"payment_history[{j}]",
                original=original_desc,
                tampered=tampered_desc,
                bbox=bbox,
            )
        )

    elif tamper_type == "edited_total_only":
        old_total = bill.total_amount_due
        new_total = round(old_total * float(rng.uniform(1.15, 1.4)), 2)
        bill2.total_amount_due = new_total
        bbox = _patch_text(img, bboxes["total_amount_due"], fmt_inr(new_total))
        events.append(
            TamperEvent(
                type="edited_total_only",
                field="total_amount_due",
                original=old_total,
                tampered=new_total,
                bbox=bbox,
            )
        )

    elif tamper_type == "consistent_edit":
        idx = int(rng.integers(0, len(bill.line_items)))
        label, old_amt = bill.line_items[idx]
        delta = round(abs(old_amt) * float(rng.uniform(0.2, 0.5)), 2)
        new_amt = round(old_amt + delta, 2)
        bill2.line_items[idx] = (label, new_amt)
        new_total = round(bill.total_amount_due + delta, 2)
        bill2.total_amount_due = new_total
        b1 = _patch_text(img, bboxes[f"line_item_{idx}"], fmt_inr(new_amt))
        b2 = _patch_text(img, bboxes["total_amount_due"], fmt_inr(new_total))
        events.append(
            TamperEvent(
                type="consistent_edit",
                field=f"line_items[{idx}]+total_amount_due",
                original=[old_amt, bill.total_amount_due],
                tampered=[new_amt, new_total],
                bbox=_union_bbox(b1, b2),
            )
        )

    elif tamper_type == "metadata_stamp":
        metadata_stamp = str(rng.choice(METADATA_STAMP_TOOLS))
        events.append(
            TamperEvent(
                type="metadata_stamp",
                field="_file_metadata",
                original="none",
                tampered=metadata_stamp,
            )
        )

    else:
        raise ValueError(f"unknown utility_bill tamper type {tamper_type!r}")

    final_bytes = _jpeg_bytes(img, GEN2_QUALITY, software=metadata_stamp)
    vf = bill_to_visible_fields(bill2)
    return final_bytes, vf, events, metadata_stamp


def tamper_bank_statement(
    rng: np.random.Generator,
    rows: list[Txn],
    tamper_type: str,
) -> tuple[list[Txn], list[TamperEvent]]:
    rows2 = [replace(r) for r in rows]
    events: list[TamperEvent] = []
    credit_idxs = [i for i, r in enumerate(rows2) if r.credit is not None]

    if tamper_type == "edited_credit_without_rebalancing":
        idx = int(rng.choice(credit_idxs))
        old = rows2[idx].credit
        new = round(old * float(rng.uniform(1.3, 2.0)), 2)
        rows2[idx] = replace(rows2[idx], credit=new)  # balance NOT recomputed -> chain breaks from here on
        events.append(
            TamperEvent(
                type="edited_credit_without_rebalancing",
                field=f"transactions[{idx}].credit",
                original=old,
                tampered=new,
            )
        )

    elif tamper_type == "inserted_fake_credit_with_rebalanced_chain":
        insert_at = int(rng.integers(1, len(rows2)))
        prior_balance = rows2[insert_at - 1].balance
        fake_amount = round(float(rng.uniform(2000, 9000)), 2)
        fake_ref = str(int(rng.integers(900000, 999999)))  # out-of-sequence ref: a corroboration cue, not a balance one
        fake_txn = Txn(
            txn_date=rows2[insert_at].txn_date,
            narration="UPI/CUSTOMER TRANSFER/IN",
            ref=fake_ref,
            debit=None,
            credit=fake_amount,
            balance=round(prior_balance + fake_amount, 2),
        )
        rows2.insert(insert_at, fake_txn)
        running = fake_txn.balance
        for k in range(insert_at + 1, len(rows2)):
            r = rows2[k]
            running = round(running - (r.debit or 0.0) + (r.credit or 0.0), 2)
            rows2[k] = replace(r, balance=running)
        events.append(
            TamperEvent(
                type="inserted_fake_credit_with_rebalanced_chain",
                field=f"transactions[{insert_at}]",
                original="absent",
                tampered=f"+₹{fake_amount:,.2f} inserted, chain rebalanced",
            )
        )

    else:
        raise ValueError(f"unknown bank_statement tamper type {tamper_type!r}")

    return rows2, events
