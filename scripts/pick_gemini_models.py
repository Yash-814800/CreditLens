#!/usr/bin/env python3
"""Discovers real, currently-valid Gemini model IDs against the caller's own
API key and picks a cheap-but-accurate vision model (for document extraction)
and a cheap text model (for Phase 6's grounded summaries). Model IDs are never
hardcoded in the app -- Google's catalog changes over time (models get
deprecated for new callers with only a few weeks' notice, which this script
hit live during development: gemini-2.5-flash and gemini-2.5-flash-lite both
returned 404 "no longer available to new users" although they still appear
harmless in casual docs) -- so this script asks the live API what exists right
now, runs a tiny real probe against a shortlist of candidates, and writes the
winners into .env.

Run from the repo root:
    uv run --project backend python scripts/pick_gemini_models.py

Never prints GEMINI_API_KEY. Makes a small number of real, billed API calls
(a handful of single-token-scale probes) -- negligible cost (a small fraction
of a cent), but real.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import dotenv_values  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from google.genai.errors import ClientError  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pydantic import BaseModel  # noqa: E402

ENV_PATH = REPO_ROOT / ".env"

# Model families that are real Gemini catalog entries but are not general
# vision/text structured-output models -- never useful for this app's two LLM
# use cases (document extraction, plain-text summary).
_EXCLUDE_SUBSTRINGS = (
    "embed",
    "tts",
    "audio",
    "live",
    "transcribe",
    "image",  # image-generation models (Nano Banana etc.), not vision-understanding
    "imagen",
    "veo",
    "lyria",
    "robotics",
    "computer-use",
    "deep-research",
    "antigravity",
    "gemma",  # open-weight text models; excluded from this app's vision/structured-output path
    "embedding",
    "aqa",
)

PROBE_NUMBER = 742
PROBE_TIMEOUT_MS = 20_000
MAX_CANDIDATES_TRIED = 12  # bound worst-case runtime; cheapest-first ordering means we rarely need many


class NumberProbe(BaseModel):
    number: int


def _cheapness_rank(model_id: str) -> int:
    name = model_id.lower()
    if "flash-lite" in name:
        return 0
    if "flash" in name:
        return 1
    if "pro" in name:
        return 2
    return 3


def candidate_models(client: genai.Client) -> list[str]:
    all_models = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" not in actions:
            continue
        # model.name comes back as "models/gemini-3.5-flash-lite"
        model_id = m.name.split("/", 1)[-1]
        all_models.append(model_id)
    filtered = [m for m in all_models if not any(p in m.lower() for p in _EXCLUDE_SUBSTRINGS)]
    filtered.sort(key=lambda m: (_cheapness_rank(m), m))
    return filtered


def _make_probe_image_bytes() -> bytes:
    img = Image.new("RGB", (320, 160), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((60, 60), str(PROBE_NUMBER), fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def probe_vision(client: genai.Client, model: str) -> tuple[bool, dict]:
    image_bytes = _make_probe_image_bytes()
    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        "Read the number printed in this image and return it.",
    ]
    return _probe(client, model, contents)


def probe_text(client: genai.Client, model: str) -> tuple[bool, dict]:
    contents = [f"Return the number {PROBE_NUMBER} in the requested schema, nothing else."]
    return _probe(client, model, contents)


def _probe(client: genai.Client, model: str, contents: list) -> tuple[bool, dict]:
    sampling: dict = {}
    try:
        try:
            config = types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=NumberProbe,
            )
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            sampling["temperature"] = 0
        except ClientError as exc:
            if "temperature" not in str(exc).lower():
                raise
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=NumberProbe,
            )
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            sampling["temperature"] = "unsupported_by_model"
        ok = resp.parsed is not None and resp.parsed.number == PROBE_NUMBER
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            sampling["probe_tokens"] = getattr(usage, "total_token_count", None)
        return ok, sampling
    except Exception as exc:  # noqa: BLE001 -- probing deliberately swallows and reports
        return False, {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def write_env_var(name: str, value: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(f"{name}={value}", text, count=1)
    else:
        text += f"\n{name}={value}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    env = dotenv_values(ENV_PATH)
    api_key = env.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set in .env -- add it yourself, then re-run.", file=sys.stderr)
        return 1

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=PROBE_TIMEOUT_MS))

    print("Fetching model catalog from your account (client.models.list())...", flush=True)
    candidates = candidate_models(client)[:MAX_CANDIDATES_TRIED]
    print(
        f"{len(candidates)} candidate vision/text-capable model(s) after filtering, cheapest "
        f"first (capped at {MAX_CANDIDATES_TRIED} to bound worst-case runtime).",
        flush=True,
    )
    print(
        "About to run a small number of real, billed probe calls "
        "(tiny single-number extraction; negligible cost, a small fraction of a cent).",
        flush=True,
    )

    vision_model = None
    vision_sampling = None
    for model in candidates:
        print(f"  probing vision+structured-output on {model!r} ...", end=" ", flush=True)
        ok, info = probe_vision(client, model)
        print("OK" if ok else f"failed ({info.get('error', 'schema mismatch')})", flush=True)
        if ok:
            vision_model, vision_sampling = model, info
            break

    if vision_model is None:
        print("No candidate model passed the vision probe. Inspect the catalog manually.", file=sys.stderr)
        return 2

    summary_model = None
    summary_sampling = None
    for model in candidates:
        print(f"  probing text/structured-output on {model!r} ...", end=" ", flush=True)
        ok, info = probe_text(client, model)
        print("OK" if ok else f"failed ({info.get('error', 'schema mismatch')})", flush=True)
        if ok:
            summary_model, summary_sampling = model, info
            break

    if summary_model is None:
        print("No candidate model passed the text probe; falling back to the vision model.")
        summary_model, summary_sampling = vision_model, vision_sampling

    write_env_var("GEMINI_VISION_MODEL", vision_model)
    write_env_var("GEMINI_SUMMARY_MODEL", summary_model)

    print()
    print(f"GEMINI_VISION_MODEL={vision_model}  (sampling params actually used: {vision_sampling})")
    print(f"GEMINI_SUMMARY_MODEL={summary_model}  (sampling params actually used: {summary_sampling})")
    print("Written to .env (never committed; GEMINI_API_KEY was never printed above).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
