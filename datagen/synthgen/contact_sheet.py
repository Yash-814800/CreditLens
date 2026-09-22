"""Builds docs/synth_contact_sheet.png: one grid image of sample documents so
a human can eyeball realism without opening 300+ files individually.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from synthgen.fonts import font

THUMB = (360, 640)


def _thumb(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img.thumbnail(THUMB)
    canvas = Image.new("RGB", THUMB, (255, 255, 255))
    canvas.paste(img, (0, 0))
    return canvas


def _csv_preview_image(csv_path: Path, title: str) -> Image.Image:
    lines = csv_path.read_text(encoding="utf-8").splitlines()[:26]
    img = Image.new("RGB", THUMB, (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((6, 6), title, font=font("house_bold", 16), fill=(0, 0, 0))
    y = 30
    for line in lines:
        d.text((6, y), line[:46], font=font("mono", 11), fill=(30, 30, 30))
        y += 15
    return img


def build_contact_sheet(data_dir: Path, out_path: Path) -> None:
    docs_base = data_dir / "synth" / "documents"
    samples: list[tuple[str, Image.Image]] = []

    gig_clean = sorted((docs_base / "gig_payout" / "clean").glob("*.png"))[0]
    gig_tampered = sorted((docs_base / "gig_payout" / "tampered").glob("*.jpg"))[0]
    bill_clean_jpgs = sorted((docs_base / "utility_bill" / "clean").glob("*.jpg"))
    bill_tampered = sorted((docs_base / "utility_bill" / "tampered").glob("*.jpg"))[0]
    reuse_sample = sorted((docs_base / "utility_bill" / "reuse").glob("*.jpg"))[0]
    bank_clean = sorted((docs_base / "bank_statement" / "clean").glob("*.csv"))[0]
    bank_tampered = sorted((docs_base / "bank_statement" / "tampered").glob("*.csv"))[0]

    samples.append(("GIG_PAYOUT clean", _thumb(Image.open(gig_clean))))
    samples.append(("GIG_PAYOUT tampered (amount edit etc)", _thumb(Image.open(gig_tampered))))
    if bill_clean_jpgs:
        samples.append(("UTILITY_BILL clean", _thumb(Image.open(bill_clean_jpgs[0]))))
    samples.append(("UTILITY_BILL tampered", _thumb(Image.open(bill_tampered))))
    samples.append(("UTILITY_BILL reuse variant (pHash test)", _thumb(Image.open(reuse_sample))))
    samples.append(("BANK_STATEMENT clean (CSV preview)", _csv_preview_image(bank_clean, "clean")))
    samples.append(("BANK_STATEMENT tampered (CSV preview)", _csv_preview_image(bank_tampered, "tampered")))

    cols = 4
    rows = (len(samples) + cols - 1) // cols
    pad, label_h = 16, 24
    cell_w, cell_h = THUMB[0], THUMB[1] + label_h
    sheet = Image.new("RGB", (cols * (cell_w + pad) + pad, rows * (cell_h + pad) + pad), (245, 245, 245))
    d = ImageDraw.Draw(sheet)
    for idx, (label, img) in enumerate(samples):
        r, c = divmod(idx, cols)
        x = pad + c * (cell_w + pad)
        y = pad + r * (cell_h + pad)
        d.text((x, y), label, font=font("house_bold", 14), fill=(20, 20, 20))
        sheet.paste(img, (x, y + label_h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
