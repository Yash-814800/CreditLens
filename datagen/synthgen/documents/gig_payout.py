"""GIG_PAYOUT document: a phone-screenshot PNG of a "weekly earnings" screen.

Layout: fake status bar -> platform header -> partner card (name/id/since) ->
12 weekly rows (week range, active days, trip/order count, gross, incentives,
deductions, net) -> period total -> SYNTHETIC SAMPLE footer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from PIL import Image, ImageDraw

from synthgen.brands import GIG_PLATFORMS, SYNTHETIC_FOOTER
from synthgen.calendar_utils import REFERENCE_DATE, last_n_weeks
from synthgen.fonts import font
from synthgen.schemas import PersonaMeta

WIDTH, HEIGHT = 1080, 2400
BG = (17, 18, 20)
CARD_BG = (27, 28, 32)
ROW_ALT = (22, 23, 26)
FG = (235, 236, 240)
MUTED = (145, 148, 158)
ACCENT = (64, 191, 130)
NEGATIVE = (214, 92, 92)
DIVIDER = (46, 47, 52)


@dataclass
class WeekRow:
    week_start: date
    week_end: date
    active_days: int
    activity_count: int
    gross_earnings: float
    incentives: float
    deductions: float
    net_payout: float


def build_weeks(
    rng: np.random.Generator,
    n_weeks: int,
    active_days_mean: float,
    earnings_cv: float,
    activity_per_day: tuple[int, int] = (3, 7),
    base_daily: float = 850.0,
    as_of: date = REFERENCE_DATE,
    bimodal: bool = False,
) -> list[WeekRow]:
    weeks = last_n_weeks(n_weeks, as_of)
    rows: list[WeekRow] = []
    for i, (week_start, week_end) in enumerate(weeks):
        if bimodal:
            scale = 1.55 if i % 2 == 0 else 0.45
            active_days = 6 if i % 2 == 0 else 4
        else:
            scale = 1.0
            active_days = int(np.clip(round(rng.normal(active_days_mean, 1.0)), 0, 7))
        activity_count = 0
        gross = 0.0
        if active_days > 0:
            daily_counts = rng.integers(activity_per_day[0], activity_per_day[1] + 1, size=active_days)
            activity_count = int(daily_counts.sum())
            cv = 0.05 if bimodal else earnings_cv
            daily_earn = base_daily * scale * (1 + rng.normal(0, cv, size=active_days))
            daily_earn = np.clip(daily_earn, 100, None)
            gross = float(daily_earn.sum())
        incentives = round(gross * float(rng.uniform(0.0, 0.08)), 2) if active_days else 0.0
        deductions = round(gross * float(rng.uniform(0.05, 0.12)), 2) if active_days else 0.0
        net = round(gross + incentives - deductions, 2)
        rows.append(
            WeekRow(
                week_start,
                week_end,
                active_days,
                activity_count,
                round(gross, 2),
                incentives,
                deductions,
                net,
            )
        )
    return rows


def _tb(d: ImageDraw.ImageDraw, xy, text, f, fill, bg, key, bboxes):
    bbox = d.textbbox(xy, text, font=f)
    d.text(xy, text, font=f, fill=fill)
    bboxes[key] = {"bbox": list(bbox), "bg": bg, "font": f, "fill": fill}


def render(
    persona: PersonaMeta,
    platform_key: str,
    partner_id: str,
    partner_since: date,
    weeks: list[WeekRow],
    payout_account_last4: str,
) -> tuple[Image.Image, dict]:
    """Returns (image, bboxes) where bboxes maps a semantic field key to
    {bbox, bg, font, fill} so tamper.py can surgically patch a single field
    (blackout + redraw) rather than re-rendering the whole document -- this is
    what makes the tamper realistic enough for later pixel-forensics checks.
    """
    bboxes: dict = {}
    platform = GIG_PLATFORMS[platform_key]
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    # fake status bar
    d.rectangle([0, 0, WIDTH, 56], fill=(10, 10, 12))
    d.text((32, 14), "9:41", font=font("house_bold", 26), fill=FG)
    d.text((WIDTH - 120, 14), "100%", font=font("house", 22), fill=MUTED)

    # header
    y = 90
    d.text((32, y), platform["name"], font=font("house_bold", 44), fill=FG)
    y += 56
    d.text((32, y), "Weekly earnings", font=font("house", 30), fill=MUTED)
    y += 60

    # partner card
    card_h = 190
    d.rounded_rectangle([32, y, WIDTH - 32, y + card_h], radius=18, fill=CARD_BG)
    d.text((60, y + 24), persona.full_name, font=font("house_bold", 34), fill=FG)
    d.text(
        (60, y + 74),
        f"{platform['role_label']} ID: {partner_id}",
        font=font("house", 26),
        fill=MUTED,
    )
    _tb(
        d,
        (60, y + 116),
        f"Partner since: {partner_since.isoformat()}",
        font("house", 26),
        MUTED,
        CARD_BG,
        "partner_since",
        bboxes,
    )
    d.text(
        (60, y + 152),
        f"Payout account ending {payout_account_last4}",
        font=font("house", 24),
        fill=MUTED,
    )
    y += card_h + 40

    d.text(
        (32, y),
        f"Last {len(weeks)} weeks · {weeks[0].week_start.isoformat()} to {weeks[-1].week_end.isoformat()}",
        font=font("house_bold", 28),
        fill=FG,
    )
    y += 50

    row_h = 132
    for i, w in enumerate(weeks):
        row_top = y
        if i % 2 == 0:
            d.rectangle([32, y, WIDTH - 32, y + row_h], fill=ROW_ALT)
        row_bg = ROW_ALT if i % 2 == 0 else BG
        bboxes[f"row_rect_{i}"] = {"bbox": [32, row_top, WIDTH - 32, row_top + row_h], "bg": row_bg}
        label = f"{w.week_start.strftime('%d %b')} – {w.week_end.strftime('%d %b')}"
        _tb(d, (48, y + 14), label, font("house_bold", 28), FG, row_bg, f"week_range_{i}", bboxes)
        d.text(
            (48, y + 54),
            f"{w.active_days} active days · {w.activity_count} {platform['activity_label']}",
            font=font("house", 22),
            fill=MUTED,
        )
        _tb(
            d,
            (48, y + 90),
            f"Gross ₹{w.gross_earnings:,.2f}",
            font("house", 22),
            MUTED,
            row_bg,
            f"week_gross_{i}",
            bboxes,
        )
        d.text(
            (WIDTH - 430, y + 92),
            f"Incentives +₹{w.incentives:,.2f}  Fees -₹{w.deductions:,.2f}",
            font=font("house", 17),
            fill=MUTED,
        )
        _tb(
            d,
            (WIDTH - 300, y + 40),
            f"₹{w.net_payout:,.2f}",
            font("house_bold", 32),
            ACCENT if w.net_payout > 0 else NEGATIVE,
            row_bg,
            f"week_net_{i}",
            bboxes,
        )
        y += row_h
        d.line([32, y, WIDTH - 32, y], fill=DIVIDER, width=2)

    y += 30
    total = round(sum(w.net_payout for w in weeks), 2)
    d.rounded_rectangle([32, y, WIDTH - 32, y + 110], radius=18, fill=CARD_BG)
    d.text((60, y + 28), "Period total net payout", font=font("house", 26), fill=MUTED)
    _tb(
        d,
        (WIDTH - 340, y + 22),
        f"₹{total:,.2f}",
        font("house_bold", 40),
        ACCENT,
        CARD_BG,
        "period_total",
        bboxes,
    )
    y += 150

    d.text((32, HEIGHT - 50), SYNTHETIC_FOOTER, font=font("house", 18), fill=(90, 92, 100))
    return img, bboxes


def to_visible_fields(
    platform_key: str,
    partner_name: str,
    partner_id: str,
    partner_since: date,
    weeks: list[WeekRow],
    payout_account_last4: str,
) -> dict:
    platform = GIG_PLATFORMS[platform_key]
    return {
        "platform_name": platform["name"],
        "partner_name": partner_name,
        "partner_id": partner_id,
        "partner_since": partner_since.isoformat(),
        "report_period_start": weeks[0].week_start.isoformat(),
        "report_period_end": weeks[-1].week_end.isoformat(),
        "weeks": [
            {
                "week_start": w.week_start.isoformat(),
                "week_end": w.week_end.isoformat(),
                "active_days": w.active_days,
                "trips_or_orders": w.activity_count,
                "gross_earnings": w.gross_earnings,
                "incentives": w.incentives,
                "deductions": w.deductions,
                "net_payout": w.net_payout,
            }
            for w in weeks
        ],
        "total_net_payout_period": round(sum(w.net_payout for w in weeks), 2),
        "payout_account_last4": payout_account_last4,
    }
