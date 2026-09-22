#!/usr/bin/env python3
"""Runs REAL Gemini extraction on the DEV split of the synthetic fraud-eval
corpus (data/synth/, built by `make datagen` in Phase 2) and compares the
result field-by-field against each document's own truth.json sidecar, writing
docs/extraction_eval.md with real field-level accuracy and confidence-
calibration numbers -- CLAUDE.md rule 4: no number in a doc is allowed to be
invented, every one must come from a script.

Prints an estimated cost BEFORE spending anything. Respects
GEMINI_MAX_CALLS_PER_RUN. Uses the extraction cache, so re-running this script
after a partial/failed run does not re-bill already-extracted documents.

Run from the repo root:
    uv run --project backend python scripts/eval_extraction.py
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from app.core.config import Settings  # noqa: E402
from app.services.extraction.factory import build_extraction_service  # noqa: E402
from app.services.ingestion.validation import sha256_hex  # noqa: E402

MANIFEST = REPO_ROOT / "data" / "synth" / "manifest.csv"
DOCS_ROOT = REPO_ROOT / "data" / "synth" / "documents"
OUT_PATH = REPO_ROOT / "docs" / "extraction_eval.md"

# Rough per-call cost ceiling used only for the pre-flight estimate printed to
# the operator -- deliberately conservative (a small vision call is typically
# well under this); actual spend is whatever Gemini bills for the real calls.
ASSUMED_MAX_COST_PER_CALL_USD = 0.01

SCALAR_FIELDS = {
    "GIG_PAYOUT": [
        "platform_name",
        "partner_name",
        "partner_id",
        "partner_since",
        "report_period_start",
        "report_period_end",
        "total_net_payout_period",
        "payout_account_last4",
    ],
    "UTILITY_BILL": [
        "utility_name",
        "consumer_name",
        "consumer_number",
        "service_address",
        "connection_date",
        "meter_number",
        "bill_date",
        "due_date",
        "billing_period_start",
        "billing_period_end",
        "units_consumed",
        "total_amount_due",
    ],
}
LIST_FIELDS = {"GIG_PAYOUT": "weeks", "UTILITY_BILL": "payment_history"}


def _values_match(expected, actual) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return abs(float(expected) - float(actual)) <= max(0.01, abs(float(expected)) * 0.01)
    return str(expected).strip() == str(actual).strip()


def load_dev_docs() -> list[dict]:
    with MANIFEST.open() as f:
        rows = list(csv.DictReader(f))
    return [
        r
        for r in rows
        if r["split"] == "dev" and r["clean"] == "True" and r["doc_type"] in SCALAR_FIELDS
    ]


async def main() -> int:
    settings = Settings()
    if settings.mock_llm:
        print("MOCK_LLM=true in .env -- set it to false to run a REAL extraction eval.", file=sys.stderr)
        return 1
    if not settings.gemini_vision_model:
        print("GEMINI_VISION_MODEL is empty -- run scripts/pick_gemini_models.py first.", file=sys.stderr)
        return 1

    docs = load_dev_docs()
    print(f"DEV split has {len(docs)} clean GIG_PAYOUT/UTILITY_BILL documents available.")
    n_calls = min(len(docs), settings.gemini_max_calls_per_run)
    if n_calls < len(docs):
        print(
            f"GEMINI_MAX_CALLS_PER_RUN={settings.gemini_max_calls_per_run} caps this run to "
            f"{n_calls} of {len(docs)} documents."
        )
    docs = docs[:n_calls]

    est_cost = n_calls * ASSUMED_MAX_COST_PER_CALL_USD
    print(
        f"About to make up to {n_calls} real Gemini extraction calls against "
        f"model={settings.gemini_vision_model!r}. Conservative worst-case cost estimate: "
        f"${est_cost:.2f} (extraction calls are cached by sha256+prompt+model, so a re-run "
        f"of this script after this one costs $0 for unchanged documents). Proceeding."
    )

    service = build_extraction_service(settings)

    per_field_correct: dict[str, int] = {}
    per_field_total: dict[str, int] = {}
    calibration_buckets: dict[str, list[int]] = {  # bucket label -> [n_correct, n_total]
        "0.0-0.5": [0, 0],
        "0.5-0.8": [0, 0],
        "0.8-0.95": [0, 0],
        "0.95-1.0": [0, 0],
    }
    row_count_matches = 0
    row_count_total = 0
    instruction_text_false_positives = 0
    doc_results = []

    for row in docs:
        doc_type = row["doc_type"]
        path = DOCS_ROOT / doc_type.lower() / "clean" / row["filename"]
        truth = json.loads((path.parent / f"{row['filename']}.truth.json").read_text())
        visible = truth["visible_fields"]
        file_bytes = path.read_bytes()
        mime = "application/pdf" if path.suffix == ".pdf" else "image/jpeg" if path.suffix in (".jpg", ".jpeg") else "image/png"

        outcome = await service.extract_document(
            doc_type=doc_type, file_bytes=file_bytes, mime=mime, sha256=sha256_hex(file_bytes)
        )
        data = outcome.data

        for field_name in SCALAR_FIELDS[doc_type]:
            expected = visible.get(field_name)
            actual_field = data.get(field_name, {})
            actual = actual_field.get("value") if isinstance(actual_field, dict) else actual_field
            confidence = actual_field.get("confidence", 0.0) if isinstance(actual_field, dict) else 1.0

            key = f"{doc_type}.{field_name}"
            per_field_total[key] = per_field_total.get(key, 0) + 1
            correct = _values_match(expected, actual)
            if correct:
                per_field_correct[key] = per_field_correct.get(key, 0) + 1

            bucket = (
                "0.95-1.0" if confidence >= 0.95 else
                "0.8-0.95" if confidence >= 0.8 else
                "0.5-0.8" if confidence >= 0.5 else
                "0.0-0.5"
            )
            calibration_buckets[bucket][1] += 1
            if correct:
                calibration_buckets[bucket][0] += 1

        list_field = LIST_FIELDS[doc_type]
        row_count_total += 1
        if len(data.get(list_field, [])) == len(visible.get(list_field, [])):
            row_count_matches += 1

        # Every document in this DEV split is `clean == "True"` (Phase 2 never adds
        # actual injected instruction text to a clean document), so any `True` here
        # is by definition a false positive from the model, not a real detection.
        # This metric exists because Gemini v1-prompt real extraction on persona P01
        # falsely flagged the "SYNTHETIC SAMPLE" demo watermark as instruction text --
        # see docs/PROGRESS.md. The v2 prompt (backend/app/prompts/*.v2.md) fixes the
        # wording; this counter is the regression signal that the fix actually holds
        # against the real model, since a MOCK_LLM-only test cannot exercise Gemini's
        # judgment on ambiguous text.
        if bool(data.get("suspected_instruction_text")):
            instruction_text_false_positives += 1

        doc_results.append(
            {
                "doc_id": row["doc_id"],
                "doc_type": doc_type,
                "extraction_confidence": outcome.extraction_confidence,
                "findings": len(outcome.findings),
                "source": outcome.source,
            }
        )
        print(f"  {row['doc_id']} ({doc_type}): confidence={outcome.extraction_confidence:.2f}, source={outcome.source}")

    write_report(
        per_field_correct,
        per_field_total,
        calibration_buckets,
        row_count_matches,
        row_count_total,
        instruction_text_false_positives,
        doc_results,
        settings,
    )
    print(f"\nWrote {OUT_PATH.relative_to(REPO_ROOT)}")
    if instruction_text_false_positives:
        print(
            f"WARNING: {instruction_text_false_positives}/{len(doc_results)} clean DEV documents "
            "were flagged suspected_instruction_text=true -- these are false positives by "
            "construction. See docs/extraction_eval.md.",
            file=sys.stderr,
        )
    return 0


def write_report(
    per_field_correct,
    per_field_total,
    calibration_buckets,
    row_count_matches,
    row_count_total,
    instruction_text_false_positives,
    doc_results,
    settings,
) -> None:
    lines = [
        "# Extraction evaluation (real Gemini extraction, DEV split)",
        "",
        f"Generated by `scripts/eval_extraction.py` on {datetime.now(UTC).isoformat()}.",
        f"Model: `{settings.gemini_vision_model}`. Documents: {len(doc_results)} clean synthetic "
        "GIG_PAYOUT/UTILITY_BILL documents from the DEV split of `data/synth/` (Phase 2's synthetic "
        "corpus). **All figures below come from this run; none are hand-typed.**",
        "",
        "## Field-level accuracy",
        "",
        "| Field | Correct | Total | Accuracy |",
        "|---|---|---|---|",
    ]
    for key in sorted(per_field_total):
        correct = per_field_correct.get(key, 0)
        total = per_field_total[key]
        lines.append(f"| {key} | {correct} | {total} | {correct / total:.1%} |")

    overall_correct = sum(per_field_correct.values())
    overall_total = sum(per_field_total.values())
    if overall_total:
        overall_line = (
            f"**Overall scalar-field accuracy: {overall_correct}/{overall_total} "
            f"({overall_correct / overall_total:.1%})**"
        )
    else:
        overall_line = "**No fields evaluated.**"

    if row_count_total:
        row_count_line = (
            "Row-count match (weeks / payment_history table length exactly matches truth): "
            f"{row_count_matches}/{row_count_total} ({row_count_matches / row_count_total:.1%})"
        )
    else:
        row_count_line = "Row-count match: N/A"

    lines += [
        "",
        overall_line,
        "",
        row_count_line,
        "",
        "## Confidence calibration",
        "",
        "Empirical accuracy of extracted fields, bucketed by the model's own reported confidence "
        "for that field. A well-calibrated model's accuracy in each bucket should roughly match "
        "the bucket's confidence range.",
        "",
        "| Confidence bucket | Correct | Total | Empirical accuracy |",
        "|---|---|---|---|",
    ]
    for bucket, (correct, total) in calibration_buckets.items():
        acc = f"{correct / total:.1%}" if total else "n/a"
        lines.append(f"| {bucket} | {correct} | {total} | {acc} |")

    n_docs = len(doc_results)
    fp_rate = f"{instruction_text_false_positives / n_docs:.1%}" if n_docs else "n/a"
    lines += [
        "",
        "## Prompt-injection flag false-positive rate (DEV split, clean docs)",
        "",
        "Every document in this run is `clean == True` in `data/synth/manifest.csv` -- Phase 2's "
        "generator never adds real injected instruction text to a clean document -- so any "
        "`suspected_instruction_text=true` returned here is a false positive by construction, "
        "not a real detection.",
        "",
        f"**{instruction_text_false_positives}/{n_docs} clean documents flagged ({fp_rate}).**",
        "",
        "## Per-document summary",
        "",
        "| Doc ID | Type | Extraction confidence | Guardrail findings | Source |",
        "|---|---|---|---|---|",
    ]
    for d in doc_results:
        lines.append(
            f"| {d['doc_id']} | {d['doc_type']} | {d['extraction_confidence']:.2f} | "
            f"{d['findings']} | {d['source']} |"
        )

    lines += [
        "",
        "## Notes / limitations",
        "",
        "- Field-level accuracy compares the model's `value` against the synthetic document's "
        "own ground truth (`visible_fields` in its `.truth.json` sidecar) -- i.e. what a "
        "perfect read of the rendered pixels would produce, not a hand-labelled real-world dataset.",
        "- Numeric fields are matched within a 1% relative tolerance (or ±₹0.01, whichever is "
        "larger) to absorb harmless rounding; every other field requires an exact string match.",
        "- Row-level fields inside `weeks`/`payment_history` are checked only for count, not "
        "cell-by-cell (see `docs/feature_definitions.md` / `app/schemas/extraction.py` for why "
        "row-level confidence isn't modelled).",
        "- This is a small (DEV-split) sample intended to sanity-check the extraction pipeline, "
        "not a statistically powered accuracy claim.",
        "- Observed failure pattern (Gemini, first real run): `GIG_PAYOUT.platform_name` was the "
        "one field with real, repeated misses -- the model consistently read the screenshot's "
        "brand header as e.g. `\"FoodDash\"`/`\"ZipRide\"` and dropped the trailing `\" Partner\"` "
        "that the synthetic layout renders as part of the same brand string, despite reporting "
        "confidence 1.0. Every miss was this exact truncation, not a hallucination or garbled "
        "read -- a real, reproducible extraction weakness (worth an explicit prompt example) "
        "rather than something to paper over.",
    ]

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
