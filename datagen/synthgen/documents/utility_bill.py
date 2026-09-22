"""UTILITY_BILL document: rendered as an image (PNG) AND, for a documented
subset of the corpus, as a PDF via reportlab -- see build_bill_data's
`render_as_pdf` flag. Content is identical either way; only the container
format differs (pixel-forensics tamper checks in Phase 4 apply to the image
rendition, since a re-flowed PDF has no meaningful ELA/noise-residual signal).

Fields: consumer name/number, service address, connection date, meter number,
bill date, due date, billing period, units, line items, total due, and a
"payment history (last <=12 months)" table used for tenure/on-time features.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from synthgen.brands import SYNTHETIC_FOOTER, UTILITY_NAME
from synthgen.calendar_utils import REFERENCE_DATE, last_n_months
from synthgen.fonts import font
from synthgen.format_utils import fmt_inr
from synthgen.schemas import PersonaMeta

WIDTH, HEIGHT = 1240, 1754  # ~150dpi A4 portrait
BG = (250, 250, 248)
FG = (30, 30, 32)
MUTED = (100, 100, 108)
HEADER_BG = (20, 60, 110)
HEADER_FG = (245, 245, 250)
LINE = (210, 210, 214)
BAD = (180, 40, 40)


@dataclass
class PaymentHistoryRow:
    month_label: str
    amount: float
    due_date: date
    paid_date: date
    status: str  # "On-time" | "Late"


@dataclass
class BillData:
    consumer_name: str
    consumer_number: str
    service_address: str
    connection_date: date
    meter_number: str
    bill_date: date
    due_date: date
    billing_period_start: date
    billing_period_end: date
    units_consumed: int
    line_items: list[tuple[str, float]] = field(default_factory=list)
    total_amount_due: float = 0.0
    payment_history: list[PaymentHistoryRow] = field(default_factory=list)
    hard_negative_group: str = "template_A"


def build_bill_data(
    rng: np.random.Generator,
    persona: PersonaMeta,
    tenure_months: int,
    on_time_ratio: float,
    consumer_number: str,
    meter_number: str,
    as_of: date = REFERENCE_DATE,
) -> BillData:
    bill_date = as_of - timedelta(days=int(rng.integers(1, 6)))
    period_len = int(rng.integers(28, 32))
    period_end = bill_date - timedelta(days=int(rng.integers(1, 4)))
    period_start = period_end - timedelta(days=period_len)
    due_date = bill_date + timedelta(days=int(rng.integers(15, 22)))
    connection_date = bill_date - timedelta(days=30 * max(tenure_months, 1) + int(rng.integers(0, 20)))

    units = int(rng.integers(90, 320))
    rate = 6.8
    energy = round(units * rate, 2)
    fixed_charge = round(float(rng.uniform(60, 140)), 2)
    subtotal = energy + fixed_charge
    tax = round(subtotal * 0.05, 2)
    rebate = round(-abs(float(rng.uniform(0, 25))), 2) if rng.random() < 0.3 else 0.0
    line_items = [
        ("Energy charges", energy),
        ("Fixed charges", fixed_charge),
        ("Tax", tax),
    ]
    if rebate:
        line_items.append(("Prompt-payment rebate", rebate))
    total_due = round(sum(v for _, v in line_items), 2)

    n_history = int(np.clip(tenure_months, 1, 12))
    months = last_n_months(n_history, as_of=bill_date)
    history: list[PaymentHistoryRow] = []
    for y, m in months:
        h_due = date(y, m, 20) if m != 2 else date(y, m, 20)
        on_time = rng.random() < on_time_ratio
        offset = int(rng.integers(-3, 1)) if on_time else int(rng.integers(1, 15))
        h_paid = h_due + timedelta(days=offset)
        amt = round(total_due * float(rng.uniform(0.75, 1.2)), 2)
        history.append(
            PaymentHistoryRow(
                month_label=f"{y}-{m:02d}",
                amount=amt,
                due_date=h_due,
                paid_date=h_paid,
                status="On-time" if on_time else "Late",
            )
        )

    return BillData(
        consumer_name=persona.full_name,
        consumer_number=consumer_number,
        service_address=persona.declared_address,
        connection_date=connection_date,
        meter_number=meter_number,
        bill_date=bill_date,
        due_date=due_date,
        billing_period_start=period_start,
        billing_period_end=period_end,
        units_consumed=units,
        line_items=line_items,
        total_amount_due=total_due,
        payment_history=history,
    )


def _tb(d: ImageDraw.ImageDraw, xy, text, f, fill, bg, key, bboxes):
    bbox = d.textbbox(xy, text, font=f)
    d.text(xy, text, font=f, fill=fill)
    bboxes[key] = {"bbox": list(bbox), "bg": bg, "font": f, "fill": fill}


def render_image(bill: BillData) -> tuple[Image.Image, dict]:
    """Returns (image, bboxes); see gig_payout.render for why."""
    bboxes: dict = {}
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, WIDTH, 150], fill=HEADER_BG)
    d.text((50, 30), UTILITY_NAME, font=font("house_bold", 42), fill=HEADER_FG)
    d.text((50, 90), "Electricity bill (synthetic demo)", font=font("house", 24), fill=HEADER_FG)

    y = 190
    _tb(
        d,
        (50, y),
        f"Consumer name: {bill.consumer_name}",
        font("house", 24),
        FG,
        BG,
        "consumer_name",
        bboxes,
    )
    y += 40
    d.text((50, y), f"Consumer number: {bill.consumer_number}", font=font("house", 24), fill=FG)
    y += 40
    d.text((50, y), f"Service address: {bill.service_address}", font=font("house", 24), fill=FG)
    y += 40
    d.text(
        (50, y),
        f"Connection date: {bill.connection_date.isoformat()}",
        font=font("house", 24),
        fill=FG,
    )
    y += 40
    d.text((50, y), f"Meter number: {bill.meter_number}", font=font("house", 24), fill=FG)
    y += 40
    _tb(
        d,
        (50, y),
        f"Bill date: {bill.bill_date.isoformat()}",
        font("house", 24),
        FG,
        BG,
        "bill_date",
        bboxes,
    )
    y += 40
    _tb(
        d,
        (50, y),
        f"Due date: {bill.due_date.isoformat()}",
        font("house", 24),
        FG,
        BG,
        "due_date",
        bboxes,
    )
    y += 40
    d.text(
        (50, y),
        f"Billing period: {bill.billing_period_start.isoformat()} to {bill.billing_period_end.isoformat()}",
        font=font("house", 24),
        fill=FG,
    )
    y += 40
    d.text((50, y), f"Units consumed: {bill.units_consumed} kWh", font=font("house", 24), fill=FG)
    y += 40

    y += 20
    d.line([50, y, WIDTH - 50, y], fill=LINE, width=2)
    y += 30
    d.text((50, y), "Charges", font=font("house_bold", 28), fill=FG)
    y += 44
    for idx, (label, amount) in enumerate(bill.line_items):
        d.text((70, y), label, font=font("house", 24), fill=FG)
        _tb(
            d,
            (WIDTH - 260, y),
            fmt_inr(amount),
            font("house", 24),
            FG,
            BG,
            f"line_item_{idx}",
            bboxes,
        )
        y += 38
    y += 10
    d.line([50, y, WIDTH - 50, y], fill=LINE, width=2)
    y += 20
    d.text((50, y), "Total amount due", font=font("house_bold", 30), fill=FG)
    _tb(
        d,
        (WIDTH - 280, y),
        f"₹{bill.total_amount_due:,.2f}",
        font("house_bold", 30),
        FG,
        BG,
        "total_amount_due",
        bboxes,
    )
    y += 70

    d.text((50, y), "Payment history (last 12 months)", font=font("house_bold", 26), fill=FG)
    y += 40
    headers = ["Month", "Amount", "Due date", "Paid date", "Status"]
    col_x = [50, 300, 480, 680, 900]
    for h, x in zip(headers, col_x, strict=True):
        d.text((x, y), h, font=font("house_bold", 20), fill=MUTED)
    y += 30
    d.line([50, y, WIDTH - 50, y], fill=LINE, width=1)
    y += 10
    for idx, row in enumerate(bill.payment_history):
        color = BAD if row.status == "Late" else FG
        bboxes[f"history_row_rect_{idx}"] = {"bbox": [50, y - 4, WIDTH - 50, y + 26], "bg": BG}
        d.text((col_x[0], y), row.month_label, font=font("house", 20), fill=FG)
        _tb(
            d,
            (col_x[1], y),
            f"₹{row.amount:,.2f}",
            font("house", 20),
            FG,
            BG,
            f"history_{idx}_amount",
            bboxes,
        )
        _tb(
            d,
            (col_x[2], y),
            row.due_date.isoformat(),
            font("house", 20),
            FG,
            BG,
            f"history_{idx}_due_date",
            bboxes,
        )
        _tb(
            d,
            (col_x[3], y),
            row.paid_date.isoformat(),
            font("house", 20),
            FG,
            BG,
            f"history_{idx}_paid_date",
            bboxes,
        )
        _tb(
            d,
            (col_x[4], y),
            row.status,
            font("house", 20),
            color,
            BG,
            f"history_{idx}_status",
            bboxes,
        )
        y += 32

    d.text((50, HEIGHT - 40), SYNTHETIC_FOOTER, font=font("house", 16), fill=(140, 140, 145))
    return img, bboxes


def render_pdf(img: Image.Image) -> bytes:
    """Wraps the SAME rendered bill image (`render_image`'s output) as a
    full-page PDF, rather than an independently laid-out PDF page.

    This is deliberate, not merely simpler: a "PDF export" and an "image
    screenshot" of the same real bill show the same content pixel-for-pixel
    (module docstring: "content is identical either way; only the container
    format differs"). An earlier version of this function re-drew the bill
    from scratch with reportlab, producing a VISUALLY DIFFERENT rendering of
    the same data -- which silently broke Phase 4's pHash reuse-detection
    ground truth for every PDF-format document: comparing a PDF-original
    against its own PNG-derived "reuse variant" measured two unrelated-looking
    renderings, not a true near-duplicate, and their Hamming distances came
    back at random-chance level (~94-114/256 bits) instead of near-zero.
    Fixed by construction here: both container formats now derive from the
    exact same pixels, so `app/services/extraction/rasterize.py`'s PDF-page
    rasterization recovers (module SYNTHETIC_FOOTER included) the same image
    scripts/eval_fraud.py hashes for the PNG/JPG rendition, confirmed by that
    script's reuse-variant recall numbers in docs/fraud_eval.md.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    c.drawImage(ImageReader(img), 0, 0, width=page_w, height=page_h)
    c.showPage()
    c.save()
    return buf.getvalue()


def to_visible_fields(bill: BillData) -> dict:
    return {
        "utility_name": UTILITY_NAME,
        "consumer_name": bill.consumer_name,
        "consumer_number": bill.consumer_number,
        "service_address": bill.service_address,
        "connection_date": bill.connection_date.isoformat(),
        "meter_number": bill.meter_number,
        "bill_date": bill.bill_date.isoformat(),
        "due_date": bill.due_date.isoformat(),
        "billing_period_start": bill.billing_period_start.isoformat(),
        "billing_period_end": bill.billing_period_end.isoformat(),
        "units_consumed": bill.units_consumed,
        "line_items": [{"label": label, "amount": amount} for label, amount in bill.line_items],
        "total_amount_due": bill.total_amount_due,
        "payment_history": [
            {
                "month": row.month_label,
                "amount": row.amount,
                "due_date": row.due_date.isoformat(),
                "paid_date": row.paid_date.isoformat(),
                "status": row.status,
            }
            for row in bill.payment_history
        ],
    }
