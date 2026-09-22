"""Font resolution.

Two independent font families are required: DejaVu Sans (ships with
matplotlib/most Linux distros) is the "house" font for every clean document,
and Liberation Sans is the second family used ONLY by the `font_swap` tamper
(a single line rendered in a visibly different font than the rest of the
document -- a classic paste-over tell). Both are verified (see
tests/test_fonts.py) to render the ₹ glyph correctly.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PIL import ImageFont

_CANDIDATES = {
    "dejavu": [
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "dejavu_bold": [
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "liberation": [
        "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "liberation_bold": [
        "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "mono": [
        "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ],
}


def _resolve(key: str) -> str:
    for candidate in _CANDIDATES[key]:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        f"No font file found for '{key}'. Install dejavu-sans-fonts and "
        f"liberation-sans-fonts (or the Debian equivalents fonts-dejavu-core / "
        f"fonts-liberation)."
    )


@cache
def font(family: str, size: int) -> ImageFont.FreeTypeFont:
    """family in {house, house_bold, tamper, tamper_bold, mono}."""
    mapping = {
        "house": "dejavu",
        "house_bold": "dejavu_bold",
        "tamper": "liberation",
        "tamper_bold": "liberation_bold",
        "mono": "mono",
    }
    return ImageFont.truetype(_resolve(mapping[family]), size)
