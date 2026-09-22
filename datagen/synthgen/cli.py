"""CLI entry point: `python -m synthgen.cli <command>`. `make datagen` runs `all`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"


def cmd_corpus(_args: argparse.Namespace) -> None:
    from synthgen.corpus import build_corpus

    build_corpus(DATA_DIR)
    print(f"Wrote fraud-eval corpus + manifest to {DATA_DIR / 'synth' / 'documents'}")


def cmd_history(_args: argparse.Namespace) -> None:
    from synthgen.data_card import write_data_card
    from synthgen.history import generate_history

    df = generate_history()
    out = DATA_DIR / "synth" / "history.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    csv_out = DATA_DIR / "borrower_history.csv"
    df.to_csv(csv_out, index=False)
    write_data_card(df, DOCS_DIR / "data_card.md")
    print(f"Wrote {len(df)} historical borrower rows to {out} and {csv_out}")
    print(f"Wrote {DOCS_DIR / 'data_card.md'}")


def cmd_personas(_args: argparse.Namespace) -> None:
    from synthgen.demo_pack import build_demo_pack

    build_demo_pack(DATA_DIR)
    print(f"Wrote demo personas to {DATA_DIR / 'demo_pack'}")


def cmd_contact_sheet(_args: argparse.Namespace) -> None:
    from synthgen.contact_sheet import build_contact_sheet

    out = DOCS_DIR / "synth_contact_sheet.png"
    build_contact_sheet(DATA_DIR, out)
    print(f"Wrote {out}")


def cmd_injection(_args: argparse.Namespace) -> None:
    from synthgen.adversarial import build_all_adversarial
    from synthgen.demo_pack import build_demo_pack

    results = build_all_adversarial(DATA_DIR)
    n_docs = sum(len(pairs) * 2 for pairs in results.values())
    print(f"Wrote {n_docs} adversarial & clean-twin documents to {DATA_DIR / 'synth' / 'adversarial'}")

    build_demo_pack(DATA_DIR, persona_ids=["P09"])
    print(f"Wrote demo persona P09 to {DATA_DIR / 'demo_pack' / 'P09'}")


def cmd_all(args: argparse.Namespace) -> None:
    cmd_corpus(args)
    cmd_history(args)
    cmd_personas(args)
    cmd_contact_sheet(args)
    cmd_injection(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthgen")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("corpus", help="fraud-eval corpus: clean+tampered docs, reuse variants, manifest.csv").set_defaults(
        func=cmd_corpus
    )
    sub.add_parser("history", help="historical borrowers parquet + data card").set_defaults(func=cmd_history)
    sub.add_parser("personas", help="demo_pack P01-P09").set_defaults(func=cmd_personas)
    sub.add_parser("contact-sheet", help="docs/synth_contact_sheet.png").set_defaults(func=cmd_contact_sheet)
    sub.add_parser("injection", help="adversarial prompt-injection documents & P09").set_defaults(func=cmd_injection)
    sub.add_parser("all", help="everything, in dependency order").set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
