import io

import fitz
import pytest
from PIL import Image, ImageDraw

from app.services.fraud.imaging import (
    compute_ela_map,
    compute_noise_residual_map,
    ela_applicable,
    generate_heatmap_png,
)
from app.services.fraud.policy import load_fraud_policy
from app.services.fraud.tamper_radar import block_scores, run_tamper_radar

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def policy():
    return load_fraud_policy()


def _content_image(size=(400, 400)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), "Sample document text content", fill="black")
    d.rectangle([50, 200, 350, 250], outline="black", width=3)
    return img


def _pdf_bytes_from_image(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=img.width, height=img.height)
    page.insert_image(page.rect, stream=buf.getvalue())
    out = doc.tobytes()
    doc.close()
    return out


class TestElaApplicability:
    def test_jpeg_is_applicable(self):
        assert ela_applicable("image/jpeg") is True

    def test_png_is_not_applicable(self):
        assert ela_applicable("image/png") is False


class TestTamperRadarDoesNotCrash:
    @pytest.mark.parametrize("mime", ["image/png", "image/jpeg"])
    def test_runs_on_image_formats(self, policy, mime):
        img = _content_image()
        radar, finding, heatmap_bytes = run_tamper_radar(img, mime=mime, policy=policy)
        assert 0.0 <= radar.radar_score <= 1.0
        assert heatmap_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # a real PNG
        if finding is not None:
            assert finding.severity in ("MEDIUM", "HIGH")

    def test_runs_on_pdf_rasterized_page(self, policy):
        from app.services.extraction.rasterize import load_original_image

        pdf_bytes = _pdf_bytes_from_image(_content_image())
        img = load_original_image(pdf_bytes, "application/pdf")
        radar, _finding, heatmap_bytes = run_tamper_radar(
            img, mime="application/pdf", policy=policy
        )
        assert 0.0 <= radar.radar_score <= 1.0
        assert len(heatmap_bytes) > 0

    def test_is_idempotent(self, policy):
        img = _content_image()
        radar1, _, heatmap1 = run_tamper_radar(img, mime="image/png", policy=policy)
        radar2, _, heatmap2 = run_tamper_radar(img, mime="image/png", policy=policy)
        assert radar1.radar_score == radar2.radar_score
        assert heatmap1 == heatmap2

    def test_png_has_no_ela_in_applicable_checks(self, policy):
        radar, _, _ = run_tamper_radar(_content_image(), mime="image/png", policy=policy)
        assert "ela" not in radar.applicable_checks
        assert "noise_residual" in radar.applicable_checks

    def test_jpeg_has_ela_in_applicable_checks(self, policy):
        radar, _, _ = run_tamper_radar(_content_image(), mime="image/jpeg", policy=policy)
        assert "ela" in radar.applicable_checks


class TestBlockScores:
    def test_blank_image_has_low_zscores(self):
        img = Image.new("RGB", (200, 200), "white")
        noise_map = compute_noise_residual_map(img)
        scores = block_scores(None, noise_map)
        assert all(
            abs(s.noise_zscore) < 0.1 for s in scores
        )  # uniform image -> ~zero variance everywhere

    def test_ela_map_shape_matches_image(self):
        img = _content_image()
        ela = compute_ela_map(img)
        assert ela.shape == (img.height, img.width)


def test_generate_heatmap_png_is_a_valid_png():
    img = _content_image()
    noise_map = compute_noise_residual_map(img)
    scores = block_scores(None, noise_map)
    heatmap_bytes = generate_heatmap_png(img, scores)
    reopened = Image.open(io.BytesIO(heatmap_bytes))
    assert reopened.size == img.size
