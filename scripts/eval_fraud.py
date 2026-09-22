#!/usr/bin/env python3
"""Fraud/document-integrity evaluation harness (CLAUDE.md Phase 4, item 9).

Tunes two empirical thresholds on the DEV split ONLY, then reports honest
precision/recall/F1 on the held-out TEST split -- every number in
docs/fraud_eval.md comes from this script (CLAUDE.md rule 4), nothing is
hand-picked or asserted without a run backing it:

1. `tamper_radar` (ELA + noise-residual pixel forensics): HIGH/MEDIUM
   radar_score bands, tuned against ground-truth clean vs. tampered labels
   for GIG_PAYOUT + UTILITY_BILL (BANK_STATEMENT tampering has no pixel
   representation to forensically analyse; it is caught by the arithmetic
   checks instead, evaluated separately below).
2. `phash` near-duplicate Hamming-distance threshold T, using the four pair
   classes CLAUDE.md's Phase 4 spec calls for: reuse variants (positive
   class), same-template hard negatives (negative class -- the false-positive
   risk this whole check exists to manage), and unrelated documents.

Corpus scope note (a real, documented limitation, not a workaround): this
synthetic corpus generates only ONE utility-bill template, so every
UTILITY_BILL clean document is *simultaneously* a same-template hard negative
of every other one -- there is no genuinely "unrelated" UTILITY_BILL pair to
compare against. GIG_PAYOUT documents use two distinct platform templates
(ZipRide Partner / FoodDash Partner), so the "unrelated documents" class below
uses GIG_PAYOUT pairs instead.

Bank-statement arithmetic-check precision/recall (running-balance chain +
duplicate-ref + credit-spike checks) is reported on the same TEST split for
completeness, including the two documented "hard case" tamper types.

Run from the repo root:
    uv run --project backend python scripts/eval_fraud.py
"""

from __future__ import annotations

import csv
import itertools
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import yaml  # noqa: E402

from app.services.extraction.llm_client import build_extraction_from_truth  # noqa: E402
from app.services.extraction.rasterize import load_original_image  # noqa: E402
from app.services.fraud import semantic_checks  # noqa: E402
from app.services.fraud.phash import compute_phash_bits, hamming_distance  # noqa: E402
from app.services.fraud.policy import load_fraud_policy  # noqa: E402
from app.services.fraud.tamper_radar import run_tamper_radar  # noqa: E402
from app.services.ingestion.bank_parser import parse_bank_csv  # noqa: E402

MANIFEST = REPO_ROOT / "data" / "synth" / "manifest.csv"
DOCS_ROOT = REPO_ROOT / "data" / "synth" / "documents"
POLICY_PATH = BACKEND_DIR / "app" / "config" / "fraud_policy_v1.yaml"
OUT_PATH = REPO_ROOT / "docs" / "fraud_eval.md"

DOC_TYPE_DIR = {"UTILITY_BILL": "utility_bill", "GIG_PAYOUT": "gig_payout", "BANK_STATEMENT": "bank_statement"}
MIME_BY_SUFFIX = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf", ".csv": "text/csv"}


def load_manifest() -> list[dict]:
    with MANIFEST.open() as f:
        return list(csv.DictReader(f))


def resolve_path(row: dict) -> Path:
    subdir = "reuse" if row["split"] == "reuse" else ("clean" if row["clean"] == "True" else "tampered")
    return DOCS_ROOT / DOC_TYPE_DIR[row["doc_type"]] / subdir / row["filename"]


def mime_for(path: Path) -> str:
    return MIME_BY_SUFFIX[path.suffix.lower()]


def load_truth(path: Path) -> dict:
    truth_path = path.with_name(path.name + ".truth.json")
    import json

    return json.loads(truth_path.read_text())


# ---------------------------------------------------------------------------
# Part 1: tamper radar
# ---------------------------------------------------------------------------


@dataclass
class RadarSample:
    doc_id: str
    doc_type: str
    split: str
    tampered: bool
    tamper_type: str | None
    radar_score: float


def compute_radar_samples(rows: list[dict], policy: dict) -> list[RadarSample]:
    samples = []
    candidates = [r for r in rows if r["doc_type"] in ("GIG_PAYOUT", "UTILITY_BILL") and r["split"] != "reuse"]
    for i, row in enumerate(candidates):
        path = resolve_path(row)
        mime = mime_for(path)
        image = load_original_image(path.read_bytes(), mime)
        radar, _finding, _heatmap = run_tamper_radar(image, mime=mime, policy=policy)
        samples.append(
            RadarSample(
                doc_id=row["doc_id"],
                doc_type=row["doc_type"],
                split=row["split"],
                tampered=(row["clean"] == "False"),
                tamper_type=row["tamper_type"] or None,
                radar_score=radar.radar_score,
            )
        )
        if (i + 1) % 20 == 0:
            print(f"  tamper_radar: {i + 1}/{len(candidates)} documents scored", file=sys.stderr)
    return samples


def prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def sweep_best_f1(samples: list[RadarSample]) -> tuple[float, float, float, float]:
    """Returns (threshold, precision, recall, f1) maximising F1 over the given
    samples' radar_score vs. ground-truth tampered label."""
    candidate_thresholds = sorted({s.radar_score for s in samples})
    best = (0.0, 0.0, 0.0, 0.0)
    for t in candidate_thresholds:
        tp = sum(1 for s in samples if s.radar_score >= t and s.tampered)
        fp = sum(1 for s in samples if s.radar_score >= t and not s.tampered)
        fn = sum(1 for s in samples if s.radar_score < t and s.tampered)
        precision, recall, f1 = prf1(tp, fp, fn)
        if f1 > best[3]:
            best = (t, precision, recall, f1)
    return best


def zero_fp_threshold(samples: list[RadarSample]) -> float:
    """Smallest threshold with ZERO false positives among the given clean
    samples -- used for the HIGH band, since a single HIGH finding forces the
    whole application's fraud severity to HIGH (fraud_policy_v1.yaml's
    documented override): this check must not be the thing that does that to
    an honest applicant."""
    clean_scores = [s.radar_score for s in samples if not s.tampered]
    if not clean_scores:
        return 1.0
    return round(max(clean_scores) + 0.0001, 4)


def tune_and_evaluate_radar(rows: list[dict], policy: dict) -> dict:
    print("Scoring tamper_radar on the full clean+tampered corpus...", file=sys.stderr)
    all_samples = compute_radar_samples(rows, policy)
    dev = [s for s in all_samples if s.split == "dev"]
    test = [s for s in all_samples if s.split == "test"]

    medium_t, dev_p, dev_r, dev_f1 = sweep_best_f1(dev)
    high_t = zero_fp_threshold(dev)
    if high_t <= medium_t:
        high_t = round(medium_t + 0.05, 4)

    def evaluate(samples: list[RadarSample], threshold: float) -> dict:
        tp = sum(1 for s in samples if s.radar_score >= threshold and s.tampered)
        fp = sum(1 for s in samples if s.radar_score >= threshold and not s.tampered)
        fn = sum(1 for s in samples if s.radar_score < threshold and s.tampered)
        tn = sum(1 for s in samples if s.radar_score < threshold and not s.tampered)
        precision, recall, f1 = prf1(tp, fp, fn)
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1}

    test_medium = evaluate(test, medium_t)
    test_high = evaluate(test, high_t)

    per_tamper_type: dict[str, dict] = {}
    for tamper_type in sorted({s.tamper_type for s in test if s.tamper_type}):
        subset = [s for s in test if s.tamper_type == tamper_type or not s.tampered]
        per_tamper_type[tamper_type] = evaluate(subset, medium_t)

    return {
        "medium_threshold": medium_t,
        "high_threshold": high_t,
        "dev_medium": {"precision": dev_p, "recall": dev_r, "f1": dev_f1},
        "test_medium": test_medium,
        "test_high": test_high,
        "per_tamper_type_test": per_tamper_type,
        "n_dev": len(dev),
        "n_test": len(test),
    }


# ---------------------------------------------------------------------------
# Part 2: pHash Hamming-distance distributions
# ---------------------------------------------------------------------------


def compute_phash_index(rows: list[dict]) -> dict[str, str]:
    """doc_id -> phash bits, for every non-reuse UTILITY_BILL/GIG_PAYOUT doc
    plus every reuse variant (reuse variants need their own phash to compare
    against their original)."""
    index: dict[str, str] = {}
    relevant = [r for r in rows if r["doc_type"] in ("GIG_PAYOUT", "UTILITY_BILL")]
    for i, row in enumerate(relevant):
        path = resolve_path(row)
        image = load_original_image(path.read_bytes(), mime_for(path))
        index[row["doc_id"]] = compute_phash_bits(image)
        if (i + 1) % 40 == 0:
            print(f"  phash: {i + 1}/{len(relevant)} documents hashed", file=sys.stderr)
    return index


DEMO_PACK_DIR = REPO_ROOT / "data" / "demo_pack"
# The one deliberately-designed document reuse in the demo pack (P06's bill IS
# P05's bill under a different identity -- the pHash collision demo). Every
# other cross-persona pair is a genuine hard negative and must be treated as
# one for threshold tuning, exactly like data/synth's hard_negative_group.
DEMO_PACK_REUSE_PAIRS = {frozenset({"P05", "P06"})}


def compute_demo_pack_hard_negative_distances() -> list[int]:
    """Real-world calibration check found during Phase 6 verification, not
    part of the original Phase 4 plan: data/demo_pack's hand-built personas
    are a SEPARATE corpus from data/synth's fraud-eval corpus (different
    generator code path, Phase 2 item C), and turned out NOT to share that
    corpus's hard-negative floor -- three unrelated persona pairs (P01/P05,
    P01/P06, P04/P07) were measured at Hamming distance 6, identical to the
    then-chosen threshold, while the actual designed reuse pair (P05/P06)
    sits at distance 2. Submitting P01 through the real API produced a false
    HIGH-severity phash finding as a direct result (see docs/PROGRESS.md).
    Folding these real distances into the DEV negative pool below (not just
    reporting them) means this gap gets caught automatically on any future
    `eval_fraud.py` re-run, e.g. after `make datagen` regenerates the eval
    corpus but demo_pack (committed, not regenerated) stays fixed -- a
    threshold tuned on the corpus alone would otherwise silently drift back
    into false-positive range on the actual demo data every time."""
    distances: list[int] = []
    for doc_stem in ("utility_bill", "gig_payout"):
        phashes: dict[str, str] = {}
        for persona_dir in sorted(DEMO_PACK_DIR.iterdir()):
            if not persona_dir.is_dir():
                continue
            matches = [
                p for p in persona_dir.glob(f"{doc_stem}.*") if p.suffix.lower() in MIME_BY_SUFFIX
            ]
            if not matches:
                continue
            path = matches[0]
            image = load_original_image(path.read_bytes(), mime_for(path))
            phashes[persona_dir.name] = compute_phash_bits(image)
        for a, b in itertools.combinations(sorted(phashes), 2):
            if frozenset({a, b}) in DEMO_PACK_REUSE_PAIRS:
                continue
            distances.append(hamming_distance(phashes[a], phashes[b]))
    return distances


def tune_and_evaluate_phash(rows: list[dict], phash_index: dict[str, str]) -> dict:
    by_id = {r["doc_id"]: r for r in rows}
    reuse_rows = [r for r in rows if r["split"] == "reuse"]
    hard_neg_rows = [r for r in rows if r["hard_negative_group"] and r["split"] != "reuse"]

    # Reuse-variant pairs (positive class): split by the ORIGINAL's split.
    reuse_pairs: dict[str, list[tuple[str, int]]] = defaultdict(list)  # split -> [(variant_type, distance)]
    for row in reuse_rows:
        original_split = by_id[row["reuse_of"]]["split"]
        dist = hamming_distance(phash_index[row["doc_id"]], phash_index[row["reuse_of"]])
        reuse_pairs[original_split].append((row["reuse_variant_type"], dist))

    # Hard-negative pairs (negative class): all same-split combinations.
    hard_neg_pairs: dict[str, list[int]] = defaultdict(list)
    by_split: dict[str, list[str]] = defaultdict(list)
    for row in hard_neg_rows:
        by_split[row["split"]].append(row["doc_id"])
    for split, doc_ids in by_split.items():
        for a, b in itertools.combinations(doc_ids, 2):
            hard_neg_pairs[split].append(hamming_distance(phash_index[a], phash_index[b]))

    # Unrelated-document pairs: clean GIG_PAYOUT documents (two real templates).
    gig_clean = [r for r in rows if r["doc_type"] == "GIG_PAYOUT" and r["clean"] == "True" and r["split"] != "reuse"]
    unrelated_pairs: dict[str, list[int]] = defaultdict(list)
    by_split_gig: dict[str, list[str]] = defaultdict(list)
    for row in gig_clean:
        by_split_gig[row["split"]].append(row["doc_id"])
    for split, doc_ids in by_split_gig.items():
        for a, b in itertools.combinations(doc_ids, 2):
            unrelated_pairs[split].append(hamming_distance(phash_index[a], phash_index[b]))

    def flat(pairs_by_split: dict, splits: list[str]) -> list[int]:
        out: list[int] = []
        for s in splits:
            out.extend(pairs_by_split.get(s, []))
        return out

    def flat_reuse(splits: list[str]) -> list[int]:
        out: list[int] = []
        for s in splits:
            out.extend(d for _vt, d in reuse_pairs.get(s, []))
        return out

    dev_positive = flat_reuse(["train", "dev"])
    demo_pack_negative = compute_demo_pack_hard_negative_distances()
    dev_negative = flat(hard_neg_pairs, ["train", "dev"]) + demo_pack_negative

    # Sweep T to maximise (recall on reuse variants) - (false-positive rate on
    # hard negatives), i.e. Youden's J statistic -- the standard way to pick an
    # operating point on an ROC curve without arbitrarily favouring one class.
    # `demo_pack_negative` is folded into the DEV negative pool (never TEST --
    # see compute_demo_pack_hard_negative_distances()'s docstring) so the
    # chosen threshold also respects the real demo_pack documents, not just
    # the separate data/synth eval corpus.
    candidate_ts = sorted(set(dev_positive) | set(dev_negative))
    best_t, best_j = 0, -1.0
    for t in candidate_ts:
        tpr = sum(1 for d in dev_positive if d <= t) / len(dev_positive) if dev_positive else 0.0
        fpr = sum(1 for d in dev_negative if d <= t) / len(dev_negative) if dev_negative else 0.0
        j = tpr - fpr
        if j > best_j:
            best_j, best_t = j, t

    test_positive = flat_reuse(["test"])
    test_negative = flat(hard_neg_pairs, ["test"])
    test_unrelated = flat(unrelated_pairs, ["test", "dev", "train"])

    def rate_at_or_below(values: list[int], t: int) -> float:
        return sum(1 for v in values if v <= t) / len(values) if values else 0.0

    per_variant_type_test: dict[str, list[int]] = defaultdict(list)
    for vt, d in reuse_pairs.get("test", []):
        per_variant_type_test[vt].append(d)

    return {
        "chosen_threshold": best_t,
        "test_reuse_recall": rate_at_or_below(test_positive, best_t),
        "test_hard_negative_false_positive_rate": rate_at_or_below(test_negative, best_t),
        "test_unrelated_false_positive_rate": rate_at_or_below(test_unrelated, best_t),
        "n_test_reuse_pairs": len(test_positive),
        "n_test_hard_negative_pairs": len(test_negative),
        "n_test_unrelated_pairs": len(test_unrelated),
        "per_variant_type_test": {vt: {"n": len(ds), "recall_at_t": rate_at_or_below(ds, best_t), "distances": sorted(ds)} for vt, ds in per_variant_type_test.items()},
        "distance_summary": {
            "reuse_variants_test": _summary(test_positive),
            "hard_negatives_test": _summary(test_negative),
            "unrelated_test": _summary(test_unrelated),
            "demo_pack_hard_negatives": _summary(demo_pack_negative),
        },
        "demo_pack_false_positive_rate_at_t": rate_at_or_below(demo_pack_negative, best_t),
        "n_demo_pack_negative_pairs": len(demo_pack_negative),
    }


def _summary(values: list[int]) -> dict:
    if not values:
        return {"n": 0}
    values = sorted(values)
    n = len(values)
    return {
        "n": n,
        "min": values[0],
        "median": values[n // 2],
        "max": values[-1],
        "p10": values[max(0, int(n * 0.10) - 1)],
        "p90": values[min(n - 1, int(n * 0.90))],
    }


# ---------------------------------------------------------------------------
# Part 3: bank-statement + gig-payout / utility-bill arithmetic checks
# ---------------------------------------------------------------------------


def evaluate_arithmetic_checks(rows: list[dict], policy: dict) -> dict:
    results: dict[str, dict] = {}
    for doc_type in ("GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"):
        test_rows = [r for r in rows if r["doc_type"] == doc_type and r["split"] == "test"]
        tp = fp = fn = tn = 0
        per_tamper_type: dict[str, list[bool]] = defaultdict(list)
        for row in test_rows:
            path = resolve_path(row)
            flagged = _arithmetic_flagged(doc_type, path, policy)
            tampered = row["clean"] == "False"
            if flagged and tampered:
                tp += 1
            elif flagged and not tampered:
                fp += 1
            elif not flagged and tampered:
                fn += 1
            else:
                tn += 1
            if tampered:
                per_tamper_type[row["tamper_type"]].append(flagged)
        precision, recall, f1 = prf1(tp, fp, fn)
        results[doc_type] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "per_tamper_type_recall": {
                tt: (sum(flags) / len(flags) if flags else 0.0) for tt, flags in per_tamper_type.items()
            },
        }
    return results


def _arithmetic_flagged(doc_type: str, path: Path, policy: dict) -> bool:
    truth = load_truth(path)
    if doc_type == "GIG_PAYOUT":
        extraction = build_extraction_from_truth("GIG_PAYOUT", truth["visible_fields"])
        return len(semantic_checks.check_gig_payout(extraction, policy=policy)) > 0
    if doc_type == "UTILITY_BILL":
        extraction = build_extraction_from_truth("UTILITY_BILL", truth["visible_fields"])
        return len(semantic_checks.check_utility_bill(extraction, policy=policy)) > 0
    if doc_type == "BANK_STATEMENT":
        stmt = parse_bank_csv(path.read_text())
        return len(semantic_checks.check_bank_statement(stmt, policy=policy)) > 0
    raise ValueError(doc_type)


# ---------------------------------------------------------------------------
# Report + policy update
# ---------------------------------------------------------------------------


def update_policy_file(radar_result: dict, phash_result: dict) -> None:
    with POLICY_PATH.open() as f:
        policy_text = f.read()
    policy = yaml.safe_load(policy_text)
    policy["tamper_radar"]["high_score"] = radar_result["high_threshold"]
    policy["tamper_radar"]["medium_score"] = radar_result["medium_threshold"]
    policy["phash"]["near_duplicate_threshold"] = phash_result["chosen_threshold"]
    header = policy_text.split("\nversion:")[0]  # preserve the hand-written header comment block
    body = yaml.safe_dump(policy, sort_keys=False, default_flow_style=False)
    empirical_note = "  # [EMPIRICAL] scripts/eval_fraud.py, see docs/fraud_eval.md\n"
    for key, value in (
        ("near_duplicate_threshold", policy["phash"]["near_duplicate_threshold"]),
        ("high_score", policy["tamper_radar"]["high_score"]),
        ("medium_score", policy["tamper_radar"]["medium_score"]),
    ):
        body = body.replace(f"{key}: {value}\n", f"{key}: {value}{empirical_note}", 1)
    POLICY_PATH.write_text(header + "\n" + body)


def write_report(radar_result: dict, phash_result: dict, arithmetic_result: dict) -> None:
    lines = []
    lines.append("# Fraud / document-integrity evaluation")
    lines.append("")
    lines.append(f"Generated by `scripts/eval_fraud.py` on {datetime.now(UTC).isoformat(timespec='seconds')}.")
    lines.append(
        "All numbers below come directly from this script's run against the synthetic "
        "fraud-eval corpus in `data/synth/` (Phase 2). Thresholds are tuned on the DEV "
        "split only; every precision/recall/F1 number is reported on the held-out TEST "
        "split, which the tuning step never saw."
    )
    lines.append("")

    lines.append("## 1. Tamper radar (ELA + noise-residual pixel forensics)")
    lines.append("")
    lines.append(
        f"- Tuned on DEV ({radar_result['n_dev']} documents): MEDIUM threshold = "
        f"**{radar_result['medium_threshold']}** (best-F1 operating point; DEV precision="
        f"{radar_result['dev_medium']['precision']:.2f}, recall={radar_result['dev_medium']['recall']:.2f}, "
        f"F1={radar_result['dev_medium']['f1']:.2f})."
    )
    lines.append(
        f"- HIGH threshold = **{radar_result['high_threshold']}**, chosen as the smallest score with "
        "ZERO false positives on the DEV clean documents -- a single HIGH finding forces the whole "
        "application's fraud severity to HIGH, so this check must not be what does that to an honest applicant."
    )
    lines.append("")
    lines.append(f"### TEST split ({radar_result['n_test']} documents), MEDIUM threshold")
    lines.append("")
    lines.append("| | Predicted tampered | Predicted clean |")
    lines.append("|---|---|---|")
    tm = radar_result["test_medium"]
    lines.append(f"| **Actually tampered** | TP={tm['tp']} | FN={tm['fn']} |")
    lines.append(f"| **Actually clean** | FP={tm['fp']} | TN={tm['tn']} |")
    lines.append(f"\nPrecision={tm['precision']:.2f}, Recall={tm['recall']:.2f}, F1={tm['f1']:.2f}\n")

    th = radar_result["test_high"]
    lines.append(
        f"At the HIGH threshold: TP={th['tp']}, FP={th['fp']}, FN={th['fn']}, TN={th['tn']} "
        f"(Precision={th['precision']:.2f}, Recall={th['recall']:.2f}) -- by construction this "
        "should have zero (or near-zero) false positives; any FP here means the DEV-derived "
        "threshold did not generalise perfectly to TEST, reported honestly rather than hidden."
    )
    lines.append("")
    lines.append("### Recall by tamper type (TEST split, MEDIUM threshold)")
    lines.append("")
    lines.append("| Tamper type | TP | FP | FN | TN | Recall |")
    lines.append("|---|---|---|---|---|---|")
    for tt, r in sorted(radar_result["per_tamper_type_test"].items()):
        lines.append(f"| {tt} | {r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | {r['recall']:.2f} |")
    lines.append("")
    lines.append(
        "**Known misses, honestly reported (not guessed):** `consistent_edit` (utility bill: total AND "
        "line items edited together, so nothing looks arithmetically wrong) and "
        "`inserted_fake_credit_with_rebalanced_chain` (bank CSV: not an image, tamper_radar does not "
        "apply to it at all -- see the bank-statement arithmetic-check section below instead) are the "
        "two tamper types CLAUDE.md's Phase 4 spec calls out as hard cases. The table above shows "
        "tamper_radar's actual recall on each; where it is 0 or low for `consistent_edit`, that is because "
        "a coherent full-document edit that goes through the exact same final compression as the rest of "
        "the page leaves no localised compression-generation mismatch for ELA/noise-residual to find -- "
        "documented in `app/services/fraud/imaging.py` and `tamper_radar.py`, not asserted here without "
        "the numbers above backing it."
    )
    lines.append("")

    lines.append("## 2. pHash Hamming-distance distributions")
    lines.append("")
    lines.append(
        "Corpus limitation, stated plainly: this synthetic corpus renders only ONE utility-bill "
        "template, so every clean UTILITY_BILL document is a same-template hard negative of every "
        "other one -- there is no genuinely unrelated UTILITY_BILL pair available. Reuse-variant and "
        "hard-negative pairs below are therefore UTILITY_BILL; the 'unrelated documents' class uses "
        "GIG_PAYOUT pairs instead (two real platform templates -- ZipRide Partner / FoodDash Partner)."
    )
    lines.append("")
    lines.append(
        f"- Chosen threshold T (tuned on DEV/train reuse + hard-negative pairs via Youden's J, "
        f"PLUS `data/demo_pack`'s real cross-persona pairs -- see below) = "
        f"**{phash_result['chosen_threshold']}**"
    )
    lines.append("")
    lines.append("### Real-world calibration gap found against data/demo_pack")
    lines.append("")
    lines.append(
        "`data/demo_pack`'s 8 hand-built personas (Phase 2 item C) are generated by a separate code "
        "path from this eval corpus (Phase 2 item A), and were found NOT to share the corpus's "
        "hard-negative distance floor: submitting persona P01 through the real API during Phase 6 "
        "verification produced a false HIGH fraud severity, traced to P01's utility bill landing at "
        "Hamming distance 6 from both P05's and P06's bills -- identical to the threshold the corpus "
        "alone would have chosen, while the actual designed reuse pair (P06 deliberately reusing P05's "
        "bill) sits at distance 2. `compute_demo_pack_hard_negative_distances()` measures every "
        "cross-persona UTILITY_BILL and GIG_PAYOUT pair in the demo pack (excluding the one designed "
        "P05/P06 reuse pair) and folds them into the DEV negative pool above, so the chosen threshold "
        "is safe against both corpora, and stays safe on any future re-run even after `make datagen` "
        "regenerates the eval corpus (demo_pack is committed, not regenerated)."
    )
    lines.append("")
    dp = phash_result["distance_summary"]["demo_pack_hard_negatives"]
    if dp["n"] > 0:
        lines.append(
            f"Demo-pack cross-persona pairs (n={dp['n']}, excluding P05/P06): min={dp['min']}, "
            f"median={dp['median']}, max={dp['max']}. False-positive rate at the chosen threshold = "
            f"**{phash_result['demo_pack_false_positive_rate_at_t']:.2%}** ({phash_result['n_demo_pack_negative_pairs']} pairs)."
        )
    lines.append("")
    lines.append("### TEST-split distance distributions")
    lines.append("")
    lines.append("| Pair class | n pairs | min | p10 | median | p90 | max |")
    lines.append("|---|---|---|---|---|---|---|")
    for label, key in [
        ("Reuse variants (same doc, re-encoded)", "reuse_variants_test"),
        ("Hard negatives (same template, different consumer)", "hard_negatives_test"),
        ("Unrelated documents (different platform template)", "unrelated_test"),
    ]:
        s = phash_result["distance_summary"][key]
        if s["n"] == 0:
            lines.append(f"| {label} | 0 | - | - | - | - | - |")
        else:
            lines.append(f"| {label} | {s['n']} | {s['min']} | {s['p10']} | {s['median']} | {s['p90']} | {s['max']} |")
    lines.append("")
    lines.append(
        f"At T={phash_result['chosen_threshold']} on the TEST split: reuse-variant recall (fraction "
        f"correctly flagged as near-duplicate) = **{phash_result['test_reuse_recall']:.2%}** "
        f"({phash_result['n_test_reuse_pairs']} pairs); hard-negative false-positive rate = "
        f"**{phash_result['test_hard_negative_false_positive_rate']:.2%}** ({phash_result['n_test_hard_negative_pairs']} pairs); "
        f"unrelated-document false-positive rate = "
        f"**{phash_result['test_unrelated_false_positive_rate']:.2%}** ({phash_result['n_test_unrelated_pairs']} pairs)."
    )
    lines.append("")
    hn_fpr = phash_result["test_hard_negative_false_positive_rate"]
    if hn_fpr > 0:
        lines.append(
            f"This is exactly the false-positive risk CLAUDE.md's Phase 4 spec warns about: a "
            f"{hn_fpr:.2%} hard-negative false-positive rate means near-duplicate pHash alone WOULD "
            "wrongly flag some legitimate same-template bills at this threshold. This is precisely why "
            "HIGH severity additionally requires corroboration (a matching identifier or holder name "
            "under a different applicant identity) -- an uncorroborated near-duplicate is capped at "
            "MEDIUM, never HIGH, in `app/services/fraud/service.py`."
        )
    else:
        lines.append(
            "At this threshold, hard negatives produced zero false positives on the TEST split -- but "
            "the corroboration gate in `app/services/fraud/service.py` (HIGH requires a matching "
            "identifier or holder name under a different applicant identity, not just image similarity) "
            "still applies regardless, since a larger or more diverse real-world template population "
            "than this synthetic corpus's single template would very plausibly push some same-template "
            "pairs under T -- this check's severity design does not rely on the false-positive rate "
            "staying at zero."
        )
    lines.append("")
    lines.append("### Recall by reuse-variant type (TEST split)")
    lines.append("")
    lines.append("| Variant type | n | recall at T |")
    lines.append("|---|---|---|")
    for vt, r in sorted(phash_result["per_variant_type_test"].items()):
        lines.append(f"| {vt} | {r['n']} | {r['recall_at_t']:.2%} |")
    lines.append("")
    weak_variants = [vt for vt, r in phash_result["per_variant_type_test"].items() if r["recall_at_t"] < 1.0]
    if weak_variants:
        lines.append(
            f"**Reuse variants that partially or fully defeat pHash at this threshold:** {', '.join(sorted(weak_variants))} "
            "-- geometric transforms (crop/rotate) perturb the frequency-domain hash more than recompression "
            "or resizing do; this is a known pHash limitation, not a bug in this implementation."
        )
    else:
        lines.append("All reuse-variant types were recalled at this threshold on the TEST split.")
    lines.append("")

    lines.append("## 3. Semantic / arithmetic checks (per document type, TEST split)")
    lines.append("")
    lines.append("| Doc type | TP | FP | FN | TN | Precision | Recall | F1 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for doc_type, r in arithmetic_result.items():
        lines.append(
            f"| {doc_type} | {r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | "
            f"{r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} |"
        )
    lines.append("")
    lines.append("### Recall by tamper type")
    lines.append("")
    for doc_type, r in arithmetic_result.items():
        lines.append(f"**{doc_type}**")
        lines.append("")
        lines.append("| Tamper type | Recall |")
        lines.append("|---|---|")
        for tt, recall in sorted(r["per_tamper_type_recall"].items()):
            lines.append(f"| {tt} | {recall:.2%} |")
        lines.append("")
    lines.append(
        "`inserted_fake_credit_with_rebalanced_chain` and `consistent_edit` are the two tamper types "
        "CLAUDE.md's spec calls out as hard cases for pixel forensics; the tables above show whether the "
        "arithmetic layer catches them instead where it can (a rebalanced chain by construction has NO "
        "running-balance break -- see the recall number for that row above, reported honestly whatever it is)."
    )
    lines.append("")

    lines.append("## 4. Limitations")
    lines.append("")
    lines.append(
        "- ELA/noise-residual pixel forensics fundamentally cannot detect an edit that goes through the "
        "exact same final compression generation as the rest of the document (see `imaging.py`); the "
        "`consistent_edit` and `inserted_fake_credit_with_rebalanced_chain` hard cases are designed to "
        "probe exactly this, and the tables above report the real, sometimes-zero recall this produces."
    )
    lines.append(
        "- The pHash near-duplicate threshold is tuned on this synthetic corpus's single utility-bill "
        "template and two gig-payout templates; a production deployment with many real utility providers "
        "and gig platforms would need to re-tune T (and likely make it per-template) against real template "
        "diversity."
    )
    lines.append(
        "- Metadata forensics (EXIF Software / PDF Producer) has an inherent false-positive risk: some "
        "legitimate scanning apps stamp a real editor tag during honest use. It is weighted as a minor, "
        "corroborating-only signal for exactly this reason (see `fraud_policy_v1.yaml`'s penalty for "
        "`metadata_suspicious`)."
    )
    lines.append(
        "- All numbers above are on SYNTHETIC data (CLAUDE.md rule 4: never claim real-world predictive "
        "accuracy from this corpus)."
    )
    lines.append("")

    OUT_PATH.write_text("\n".join(lines))


def main() -> None:
    rows = load_manifest()
    policy = load_fraud_policy()

    radar_result = tune_and_evaluate_radar(rows, policy)
    print("Hashing corpus for pHash evaluation...", file=sys.stderr)
    phash_index = compute_phash_index(rows)
    phash_result = tune_and_evaluate_phash(rows, phash_index)
    print("Evaluating semantic/arithmetic checks...", file=sys.stderr)
    arithmetic_result = evaluate_arithmetic_checks(rows, policy)

    update_policy_file(radar_result, phash_result)
    write_report(radar_result, phash_result, arithmetic_result)
    print(f"Wrote {OUT_PATH} and updated {POLICY_PATH}", file=sys.stderr)
    print(
        f"tamper_radar: medium={radar_result['medium_threshold']} high={radar_result['high_threshold']} "
        f"test_f1={radar_result['test_medium']['f1']:.2f}",
        file=sys.stderr,
    )
    print(
        f"phash: T={phash_result['chosen_threshold']} test_reuse_recall={phash_result['test_reuse_recall']:.2%} "
        f"test_hard_negative_fpr={phash_result['test_hard_negative_false_positive_rate']:.2%}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
