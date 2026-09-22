"""Builds the bulk fraud-eval corpus used by Phase 4's evaluation harness:
40 clean + 40 tampered documents per DocType, a 50/25/25 train/dev/test split
(applied separately within the clean pool and the tampered pool, so every
split has both classes -- see docs/data_card.md), pHash reuse variants, and
manifest.csv.

Deviation from the prompt pack's literal "reuse variants of ONE clean bill":
variants are generated for every clean utility bill (40, not 1) so Phase 4 can
report a real Hamming-distance *distribution* rather than 6 data points --
documented in docs/data_card.md.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from synthgen import tamper
from synthgen.brands import GIG_PLATFORMS
from synthgen.calendar_utils import REFERENCE_DATE
from synthgen.documents import bank_statement, gig_payout, utility_bill
from synthgen.identity import make_persona
from synthgen.reuse import REUSE_VARIANT_TYPES, make_variant
from synthgen.rng import rng_for
from synthgen.schemas import TruthSidecar

N_CLEAN = 40
N_TAMPERED = 40


@dataclass
class ManifestRow:
    doc_type: str
    doc_id: str
    filename: str
    split: str
    clean: bool
    tamper_type: str
    reuse_of: str
    reuse_variant_type: str
    hard_negative_group: str


def _split_for_index(i: int, n: int) -> str:
    if i < round(n * 0.5):
        return "train"
    if i < round(n * 0.75):
        return "dev"
    return "test"


def _write_sidecar(path: Path, sidecar: TruthSidecar) -> None:
    path.write_text(sidecar.model_dump_json(indent=2), encoding="utf-8")


def _gen_gig_payout(base: Path, manifest: list[ManifestRow]) -> None:
    out_clean = base / "gig_payout" / "clean"
    out_tampered = base / "gig_payout" / "tampered"
    out_clean.mkdir(parents=True, exist_ok=True)
    out_tampered.mkdir(parents=True, exist_ok=True)

    def build_one(seed_index: int):
        persona = make_persona("GIG_PAYOUT", seed_index)
        rng = rng_for("corpus_gig", seed_index)
        active_days_mean = float(rng.uniform(3.2, 6.6))
        earnings_cv = float(rng.uniform(0.08, 0.45))
        platform_key = str(rng.choice(["ride", "food"]))
        partner_id = f"{GIG_PLATFORMS[platform_key]['name'][:3].upper()}-{seed_index:04d}"
        partner_since = REFERENCE_DATE - timedelta(weeks=int(rng.integers(8, 150)))
        payout_last4 = f"{int(rng.integers(1000, 9999))}"
        weeks = gig_payout.build_weeks(rng, 12, active_days_mean, earnings_cv)
        img, bboxes = gig_payout.render(persona, platform_key, partner_id, partner_since, weeks, payout_last4)
        return (
            persona,
            rng,
            platform_key,
            partner_id,
            partner_since,
            payout_last4,
            weeks,
            img,
            bboxes,
        )

    for i in range(N_CLEAN):
        persona, rng, platform_key, partner_id, partner_since, payout_last4, weeks, img, _ = build_one(i)
        doc_id = f"GIGPAY-CLEAN-{i:04d}"
        img.save(out_clean / f"{doc_id}.png")
        vf = gig_payout.to_visible_fields(
            platform_key, persona.full_name, partner_id, partner_since, weeks, payout_last4
        )
        sidecar = TruthSidecar(
            doc_type="GIG_PAYOUT",
            doc_id=doc_id,
            split=_split_for_index(i, N_CLEAN),
            clean=True,
            visible_fields=vf,
            original_fields=vf,
            tamper_manifest=[],
            persona=persona,
        )
        _write_sidecar(out_clean / f"{doc_id}.png.truth.json", sidecar)
        manifest.append(ManifestRow("GIG_PAYOUT", doc_id, f"{doc_id}.png", sidecar.split, True, "", "", "", ""))

    for i in range(N_TAMPERED):
        persona, rng, platform_key, partner_id, partner_since, payout_last4, weeks, img, bboxes = build_one(1000 + i)
        tamper_type = tamper.IMAGE_TAMPER_TYPES[i % len(tamper.IMAGE_TAMPER_TYPES)]
        orig_vf = gig_payout.to_visible_fields(
            platform_key, persona.full_name, partner_id, partner_since, weeks, payout_last4
        )
        img_bytes, vf, events, meta_stamp = tamper.tamper_gig_payout(
            rng,
            img,
            bboxes,
            weeks,
            platform_key,
            persona.full_name,
            partner_id,
            partner_since,
            payout_last4,
            tamper_type,
        )
        doc_id = f"GIGPAY-TAMPER-{i:04d}"
        (out_tampered / f"{doc_id}.jpg").write_bytes(img_bytes)
        sidecar = TruthSidecar(
            doc_type="GIG_PAYOUT",
            doc_id=doc_id,
            split=_split_for_index(i, N_TAMPERED),
            clean=False,
            visible_fields=vf,
            original_fields=orig_vf,
            tamper_manifest=events,
            persona=persona,
            metadata_stamp=meta_stamp,
        )
        _write_sidecar(out_tampered / f"{doc_id}.jpg.truth.json", sidecar)
        manifest.append(
            ManifestRow("GIG_PAYOUT", doc_id, f"{doc_id}.jpg", sidecar.split, False, tamper_type, "", "", "")
        )


def _gen_utility_bill(base: Path, manifest: list[ManifestRow]) -> list[tuple[str, object]]:
    out_clean = base / "utility_bill" / "clean"
    out_tampered = base / "utility_bill" / "tampered"
    out_reuse = base / "utility_bill" / "reuse"
    for d in (out_clean, out_tampered, out_reuse):
        d.mkdir(parents=True, exist_ok=True)

    clean_images: list[tuple[str, object]] = []  # (doc_id, PIL.Image) for reuse-variant generation

    def build_one(seed_index: int):
        persona = make_persona("UTILITY_BILL", seed_index)
        rng = rng_for("corpus_bill", seed_index)
        tenure = int(rng.integers(1, 40))
        on_time = float(rng.uniform(0.45, 1.0))
        consumer_number = f"CN{seed_index:05d}"
        meter_number = f"MT{seed_index:05d}"
        bill = utility_bill.build_bill_data(rng, persona, tenure, on_time, consumer_number, meter_number)
        img, bboxes = utility_bill.render_image(bill)
        return persona, rng, bill, img, bboxes

    for i in range(N_CLEAN):
        persona, rng, bill, img, _ = build_one(i)
        doc_id = f"UTILBILL-CLEAN-{i:04d}"
        vf = utility_bill.to_visible_fields(bill)
        if i % 2 == 0:
            (out_clean / f"{doc_id}.pdf").write_bytes(utility_bill.render_pdf(img))
            filename = f"{doc_id}.pdf"
        else:
            img.convert("RGB").save(out_clean / f"{doc_id}.jpg", format="JPEG", quality=90)
            filename = f"{doc_id}.jpg"
        sidecar = TruthSidecar(
            doc_type="UTILITY_BILL",
            doc_id=doc_id,
            split=_split_for_index(i, N_CLEAN),
            clean=True,
            visible_fields=vf,
            original_fields=vf,
            tamper_manifest=[],
            persona=persona,
            hard_negative_group="template_A",
        )
        _write_sidecar(out_clean / f"{filename}.truth.json", sidecar)
        manifest.append(ManifestRow("UTILITY_BILL", doc_id, filename, sidecar.split, True, "", "", "", "template_A"))
        clean_images.append((doc_id, img))

    for i in range(N_TAMPERED):
        persona, rng, bill, img, bboxes = build_one(2000 + i)
        tamper_type = tamper.IMAGE_TAMPER_TYPES[i % len(tamper.IMAGE_TAMPER_TYPES)]
        if tamper_type == "row_clone" and len(bill.payment_history) < 2:
            tamper_type = "amount_edit"  # not enough payment-history rows to clone one onto another
        orig_vf = utility_bill.to_visible_fields(bill)
        img_bytes, vf, events, meta_stamp = tamper.tamper_utility_bill(rng, img, bboxes, bill, tamper_type)
        doc_id = f"UTILBILL-TAMPER-{i:04d}"
        (out_tampered / f"{doc_id}.jpg").write_bytes(img_bytes)
        sidecar = TruthSidecar(
            doc_type="UTILITY_BILL",
            doc_id=doc_id,
            split=_split_for_index(i, N_TAMPERED),
            clean=False,
            visible_fields=vf,
            original_fields=orig_vf,
            tamper_manifest=events,
            persona=persona,
            metadata_stamp=meta_stamp,
        )
        _write_sidecar(out_tampered / f"{doc_id}.jpg.truth.json", sidecar)
        manifest.append(
            ManifestRow(
                "UTILITY_BILL",
                doc_id,
                f"{doc_id}.jpg",
                sidecar.split,
                False,
                tamper_type,
                "",
                "",
                "",
            )
        )

    reuse_rng = rng_for("corpus_bill_reuse", "main")
    for source_doc_id, img in clean_images:
        for variant_type in REUSE_VARIANT_TYPES:
            variant_img = make_variant(img, variant_type, reuse_rng)
            doc_id = f"{source_doc_id}-REUSE-{variant_type}"
            filename = f"{doc_id}.jpg"
            variant_img.convert("RGB").save(out_reuse / filename, format="JPEG", quality=88)
            manifest.append(
                ManifestRow(
                    "UTILITY_BILL",
                    doc_id,
                    filename,
                    "reuse",
                    True,
                    "",
                    source_doc_id,
                    variant_type,
                    "template_A",
                )
            )

    return clean_images


def _gen_bank_statement(base: Path, manifest: list[ManifestRow]) -> None:
    out_clean = base / "bank_statement" / "clean"
    out_tampered = base / "bank_statement" / "tampered"
    out_clean.mkdir(parents=True, exist_ok=True)
    out_tampered.mkdir(parents=True, exist_ok=True)

    def build_one(seed_index: int):
        persona = make_persona("BANK_STATEMENT", seed_index)
        rng = rng_for("corpus_bank", seed_index)
        account_last4 = f"{int(rng.integers(1000, 9999)):04d}"
        platform_name = GIG_PLATFORMS[str(rng.choice(["ride", "food"]))]["name"]
        opening_balance = float(rng.uniform(800, 12000))
        metadata, rows = bank_statement.build_bank_data(
            rng, persona, account_last4, platform_name, opening_balance=opening_balance
        )
        return persona, rng, metadata, rows

    for i in range(N_CLEAN):
        persona, rng, metadata, rows = build_one(i)
        doc_id = f"BANKSTMT-CLEAN-{i:04d}"
        (out_clean / f"{doc_id}.csv").write_bytes(bank_statement.to_csv_bytes(metadata, rows))
        vf = bank_statement.to_visible_fields(metadata, rows)
        sidecar = TruthSidecar(
            doc_type="BANK_STATEMENT",
            doc_id=doc_id,
            split=_split_for_index(i, N_CLEAN),
            clean=True,
            visible_fields=vf,
            original_fields=vf,
            tamper_manifest=[],
            persona=persona,
        )
        _write_sidecar(out_clean / f"{doc_id}.csv.truth.json", sidecar)
        manifest.append(ManifestRow("BANK_STATEMENT", doc_id, f"{doc_id}.csv", sidecar.split, True, "", "", "", ""))

    for i in range(N_TAMPERED):
        persona, rng, metadata, rows = build_one(3000 + i)
        tamper_type = tamper.BANK_TAMPER_TYPES[i % len(tamper.BANK_TAMPER_TYPES)]
        orig_vf = bank_statement.to_visible_fields(metadata, rows)
        rows2, events = tamper.tamper_bank_statement(rng, rows, tamper_type)
        doc_id = f"BANKSTMT-TAMPER-{i:04d}"
        (out_tampered / f"{doc_id}.csv").write_bytes(bank_statement.to_csv_bytes(metadata, rows2))
        vf = bank_statement.to_visible_fields(metadata, rows2)
        sidecar = TruthSidecar(
            doc_type="BANK_STATEMENT",
            doc_id=doc_id,
            split=_split_for_index(i, N_TAMPERED),
            clean=False,
            visible_fields=vf,
            original_fields=orig_vf,
            tamper_manifest=events,
            persona=persona,
        )
        _write_sidecar(out_tampered / f"{doc_id}.csv.truth.json", sidecar)
        manifest.append(
            ManifestRow(
                "BANK_STATEMENT",
                doc_id,
                f"{doc_id}.csv",
                sidecar.split,
                False,
                tamper_type,
                "",
                "",
                "",
            )
        )


def build_corpus(data_dir: Path) -> None:
    base = data_dir / "synth" / "documents"
    manifest: list[ManifestRow] = []
    _gen_gig_payout(base, manifest)
    _gen_utility_bill(base, manifest)
    _gen_bank_statement(base, manifest)

    manifest_path = data_dir / "synth" / "manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "doc_type",
                "doc_id",
                "filename",
                "split",
                "clean",
                "tamper_type",
                "reuse_of",
                "reuse_variant_type",
                "hard_negative_group",
            ]
        )
        for row in manifest:
            w.writerow(
                [
                    row.doc_type,
                    row.doc_id,
                    row.filename,
                    row.split,
                    row.clean,
                    row.tamper_type,
                    row.reuse_of,
                    row.reuse_variant_type,
                    row.hard_negative_group,
                ]
            )
