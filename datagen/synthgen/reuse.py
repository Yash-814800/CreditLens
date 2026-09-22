"""Reuse variants of a clean document image, for calibrating the Phase 4
perceptual-hash (pHash) collision threshold: each variant type simulates a
different way the SAME bill image might resurface under another identity
(re-saved, resized by a messaging app, screenshotted-of-a-screenshot, etc).
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter

REUSE_VARIANT_TYPES = [
    "exact_copy",
    "jpeg_q60",
    "resize_80pct",
    "crop_2pct",
    "blur_noise",
    "rotate_1deg",
]


def make_variant(img: Image.Image, variant_type: str, rng: np.random.Generator) -> Image.Image:
    if variant_type == "exact_copy":
        return img.copy()

    if variant_type == "jpeg_q60":
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=60)
        buf.seek(0)
        return Image.open(buf).convert("RGB")

    if variant_type == "resize_80pct":
        w, h = img.size
        small = img.resize((max(1, int(w * 0.8)), max(1, int(h * 0.8))))
        return small.resize((w, h))

    if variant_type == "crop_2pct":
        w, h = img.size
        dx, dy = int(w * 0.02), int(h * 0.02)
        cropped = img.crop((dx, dy, w - dx, h - dy))
        return cropped.resize((w, h))

    if variant_type == "blur_noise":
        # simulates "photo of a screenshot" -- a common reuse vector for image documents
        blurred = img.filter(ImageFilter.GaussianBlur(radius=1.2))
        arr = np.array(blurred).astype(np.int16)
        noise = rng.normal(0, 6, arr.shape).astype(np.int16)
        arr = np.clip(arr + noise, 0, 255).astype("uint8")
        return Image.fromarray(arr)

    if variant_type == "rotate_1deg":
        return img.convert("RGB").rotate(1.0, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))

    raise ValueError(f"unknown reuse variant type {variant_type!r}")
