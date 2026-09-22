"""Regression tests for Phase 9 infra, config contracts, and security audits."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.config import settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/ on host, /app in container
_REPO_ROOT = _BACKEND_ROOT.parent if (_BACKEND_ROOT.parent / "deploy").exists() else _BACKEND_ROOT


def test_calibration_v1_config_contract():
    """CLAUDE.md domain contract: calibration_v1.json must exist in app/config/

    and contain valid calibration bands on synthetic history data.
    """
    config_path = _BACKEND_ROOT / "app" / "config" / "calibration_v1.json"
    assert config_path.exists(), f"Missing required config {config_path}"

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["version"] == "v1"
    assert data["split"] == "val"
    assert data["n_total"] > 0
    assert "SYNTHETIC" in data["note"]

    bands = data["bands"]
    assert len(bands) == 10, f"Expected 10 decile bands, got {len(bands)}"

    expected_lo = 0
    for b in bands:
        assert b["score_min"] == expected_lo
        assert b["score_max"] == expected_lo + 10
        assert b["n"] >= 0
        if b["default_rate"] is not None:
            assert 0.0 <= b["default_rate"] <= 1.0
        expected_lo += 10


def test_nginx_upload_limit_matches_configured_max():
    """frontend/nginx.conf must explicitly declare client_max_body_size >= MAX_UPLOAD_MB (15M)

    to prevent nginx from rejecting document uploads with HTTP 413 before reaching FastAPI.
    """
    nginx_conf = _REPO_ROOT / "frontend" / "nginx.conf"
    if not nginx_conf.exists():
        pytest.skip("frontend/nginx.conf not accessible in container environment")
    content = nginx_conf.read_text(encoding="utf-8")

    match = re.search(r"client_max_body_size\s+(\d+)([MmKkGg]?);", content)
    assert match is not None, "client_max_body_size directive missing from frontend/nginx.conf"

    size_val = int(match.group(1))
    unit = match.group(2).upper()
    size_mb = size_val if unit == "M" else (size_val // 1024 if unit == "K" else size_val * 1024)
    msg = f"nginx ({size_mb}M) < MAX_UPLOAD_MB ({settings.max_upload_mb}M)"
    assert size_mb >= settings.max_upload_mb, msg


def test_terraform_ecr_force_delete_enabled():
    """deploy/terraform/ecr.tf must set force_delete = true on both ECR repositories
    so that `terraform destroy` and teardown.sh succeed without RepositoryNotEmptyException.
    """
    ecr_tf = _REPO_ROOT / "deploy" / "terraform" / "ecr.tf"
    if not ecr_tf.exists():
        pytest.skip("deploy/terraform/ecr.tf not accessible in container environment")
    content = ecr_tf.read_text(encoding="utf-8")

    # Split by resource blocks
    backend_match = re.search(
        r'resource "aws_ecr_repository" "backend"\s*\{([\s\S]*?)\n\}\n', content
    )
    frontend_match = re.search(
        r'resource "aws_ecr_repository" "frontend"\s*\{([\s\S]*?)\n\}\n', content
    )

    assert backend_match and "force_delete" in backend_match.group(1), (
        "aws_ecr_repository.backend missing force_delete = true"
    )
    assert frontend_match and "force_delete" in frontend_match.group(1), (
        "aws_ecr_repository.frontend missing force_delete = true"
    )


def test_no_asserts_in_production_backend_code():
    """Security/robustness check: production app code must not use python `assert`

    for runtime invariant enforcement or type narrowing (Bandit B101 / CWE-703),
    since python -O strips asserts entirely.
    """
    app_dir = _BACKEND_ROOT / "app"
    violations: list[str] = []

    for py_file in app_dir.rglob("*.py"):
        lines = py_file.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Ignore comments
            if stripped.startswith("#"):
                continue
            if re.match(r"^assert\s+", stripped):
                rel_path = py_file.relative_to(_BACKEND_ROOT)
                violations.append(f"{rel_path}:{idx}: {stripped}")

    assert not violations, "Found assert statements in production code:\n" + "\n".join(violations)


def test_no_live_deployment_identifiers_in_tracked_docs():
    """Privacy/sanitization check: no live public IPs, personal user names, or instance IDs
    should be hardcoded in documentation or terraform files.
    """
    deployment_md_path = _REPO_ROOT / "docs" / "deployment.md"
    if not deployment_md_path.exists():
        pytest.skip("docs/deployment.md not present")

    deployment_md = deployment_md_path.read_text(encoding="utf-8")
    assert "15-252-202-224" not in deployment_md, "Live IP found in docs/deployment.md"
    assert "15.252.202.224" not in deployment_md, "Live IP found in docs/deployment.md"
    assert "i-0e2b79936838c1adf" not in deployment_md, "Live instance ID in docs/deployment.md"
    assert "the Yash user" not in deployment_md, "Personal username in docs/deployment.md"
