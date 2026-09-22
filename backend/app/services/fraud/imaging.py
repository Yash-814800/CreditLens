"""Pixel-level forensics building blocks: Error Level Analysis (ELA), a
noise-residual block-variance map, and a heatmap PNG renderer. Pure numpy/PIL,
no I/O beyond the image bytes handed in -- app/services/fraud/tamper_radar.py
turns these into policy-driven findings.

HONESTY ABOUT LIMITS (CLAUDE.md rule 4: no fake claims of capability):
- ELA only means something for images that have already been through at
  least one lossy (JPEG) compression. A single from-scratch render, or a
  lossless PNG, has no quantization-error history for a recompression to
  reveal a *local* mismatch in -- there is nothing to find, and this module
  says so via `ela_applicable()` rather than returning a meaningless number.
- Both signals detect a LOCALIZED difference in compression/noise generation
  between one region and the rest of the image. They are NOT expected to
  catch an edit where the tampered pixels went through the exact same final
  save as everything else (no local mismatch exists to find) -- see
  tamper_radar.py's docstring for which of Phase 2's tamper types this misses,
  confirmed with real numbers in docs/fraud_eval.md, not asserted here.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

ELA_QUALITY = 90
BLOCK_SIZE = 32


def ela_applicable(mime: str) -> bool:
    """ELA is meaningless for PNG (lossless) -- ImageIO screenshots in this
    corpus are exactly that case. Only JPEG/JPG source bytes carry a real
    prior compression generation for a recompression to differ against."""
    return mime in ("image/jpeg", "image/jpg")


def compute_ela_map(image: Image.Image, quality: int = ELA_QUALITY) -> np.ndarray:
    """Per-pixel summed-absolute-channel-difference between `image` and a
    fresh recompression of it at a fixed quality. Regions with a DIFFERENT
    compression generation than the rest of the image (i.e. pasted in after
    the image's last real save) diverge from the recompression differently
    than the rest of the image -- see the module docstring for what this can
    and cannot detect."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    recompressed = Image.open(buf).convert("RGB")
    orig = np.asarray(image.convert("RGB"), dtype=np.int16)
    recon = np.asarray(recompressed, dtype=np.int16)
    return np.abs(orig - recon).sum(axis=2).astype(np.float64)  # shape (H, W)


def compute_noise_residual_map(image: Image.Image) -> np.ndarray:
    """High-pass residual: image minus a mild Gaussian blur of itself. A
    region whose local noise/edge energy is markedly different from the rest
    of the image (smoothed-over during editing, or a different generation's
    compression blocking) shows up as a residual-variance outlier -- computed
    block-wise in `block_scores()` below."""
    gray = np.asarray(image.convert("L"), dtype=np.float64)
    blurred = np.asarray(
        image.convert("L").filter(ImageFilter.GaussianBlur(radius=2)), dtype=np.float64
    )
    return np.abs(gray - blurred)


@dataclass(frozen=True)
class BlockScore:
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1
    ela_zscore: float
    noise_zscore: float


def block_scores(
    ela_map: np.ndarray | None, noise_map: np.ndarray, *, block_size: int = BLOCK_SIZE
) -> list[BlockScore]:
    """Divides the map(s) into block_size x block_size tiles, computes each
    tile's mean, and z-scores every tile against the image's OWN global block
    mean/stdev -- normalising away the fact that different documents have
    entirely different baseline compression/noise levels, so one fixed
    absolute threshold can't work across documents."""
    h, w = noise_map.shape
    noise_means = []
    ela_means = []
    boxes: list[tuple[int, int, int, int]] = []
    for y0 in range(0, h, block_size):
        for x0 in range(0, w, block_size):
            y1, x1 = min(y0 + block_size, h), min(x0 + block_size, w)
            boxes.append((x0, y0, x1, y1))
            noise_means.append(float(noise_map[y0:y1, x0:x1].mean()))
            ela_means.append(float(ela_map[y0:y1, x0:x1].mean()) if ela_map is not None else 0.0)

    def _zscores(values: list[float]) -> list[float]:
        arr = np.asarray(values)
        std = arr.std()
        if std < 1e-9:
            return [0.0] * len(values)
        return list((arr - arr.mean()) / std)

    noise_z = _zscores(noise_means)
    ela_z = _zscores(ela_means) if ela_map is not None else [0.0] * len(boxes)

    return [
        BlockScore(bbox=box, ela_zscore=ela_z[i], noise_zscore=noise_z[i])
        for i, box in enumerate(boxes)
    ]


def generate_heatmap_png(image: Image.Image, scores: list[BlockScore]) -> bytes:
    """Renders a semi-transparent red overlay (opacity scaled by the block's
    combined z-score) on top of the original image, so Phase 7's UI can show
    exactly which regions triggered the radar without recomputing anything.
    Built as a numpy array (not per-pixel Python assignment) so this stays
    fast even on a full-resolution phone-screenshot-sized document."""
    base = image.convert("RGBA")
    w, h = base.size
    alpha = np.zeros((h, w), dtype=np.uint8)
    max_combined = max((max(s.ela_zscore, s.noise_zscore) for s in scores), default=1.0)
    max_combined = max(max_combined, 1e-6)
    for s in scores:
        combined = max(s.ela_zscore, s.noise_zscore)
        intensity = max(0.0, min(1.0, combined / max_combined))
        if intensity <= 0:
            continue
        x0, y0, x1, y1 = s.bbox
        alpha[y0:y1, x0:x1] = int(180 * intensity)

    overlay_arr = np.zeros((h, w, 4), dtype=np.uint8)
    overlay_arr[..., 0] = 255  # red
    overlay_arr[..., 3] = alpha
    overlay = Image.fromarray(overlay_arr, mode="RGBA")
    combined_img = Image.alpha_composite(base, overlay).convert("RGB")
    buf = io.BytesIO()
    combined_img.save(buf, format="PNG")
    return buf.getvalue()
