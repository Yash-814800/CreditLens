"""Phase 6 end-to-end pipeline tests (CLAUDE.md Phase 6, item 8): the full
process_application() pipeline exercised through the real API (demo persona
endpoints), against all 8 data/demo_pack personas, with MOCK_LLM=true (the
mode `make test` always runs in -- see backend/app/core/config.py's
production guard, which forbids MOCK_LLM=true when APP_ENV=production).

These tests share the same live Postgres every other integration test in
this suite does (no transaction-per-test isolation -- see test_audit.py's
own comment on this), so every test that creates an Applicant cleans it up
in a `finally` block (ON DELETE CASCADE removes every child row -- documents,
fraud_findings, scorecard_results, precedent_matches, decision_artifacts,
in one delete). Leftover rows from a crashed test run would otherwise
silently corrupt pHash-collision assertions in test_fraud_service.py and in
these tests themselves, exactly as happened during manual verification of
this phase (see docs/PROGRESS.md).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.models import (
    Applicant,
    Application,
    AuditLog,
    DecisionArtifact,
    PrecedentMatch,
    ScorecardResult,
    User,
)
from app.services.audit.service import verify_chain
from app.services.explain.grounding import is_grounded

pytestmark = pytest.mark.integration

EXPECTED_OUTCOMES = {
    "P01": "APPROVE",
    "P02": "REFER",
    "P03": "DECLINE",
    "P04": "DECLINE",
    "P07": "REFER",
    "P08": "REFER",
    "P09": "REFER",
    "P10": "REFER",
    "P11": "REFER",
}

# Protected attributes / PII that must NEVER reach the scoring layer
# (CLAUDE.md rule 7) -- checked directly against the persisted
# scorecard_results.features column, which IS the sanitizer's ScoringInput
# output (see app/pipeline.py's SCORING stage).
_FORBIDDEN_SCORING_KEYS = {
    "full_name",
    "name",
    "phone",
    "phone_hash",
    "declared_address",
    "address",
    "stated_vocation",
    "vocation",
    "gender",
    "age",
    "religion",
    "caste",
    "marital_status",
    "requested_line_inr",  # policy input, not a scorecard feature
}


async def _create_user(db_session, email, role, password="test-password-123"):
    user = User(email=email, password_hash=hash_password(password), role=role, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return user


async def _login(client, email, password="test-password-123") -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _submit_persona(client, token: str, persona_id: str) -> str:
    resp = await client.post(
        f"/api/v1/demo/personas/{persona_id}/submit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


async def _get_application(client, token: str, application_id: str) -> dict:
    resp = await client.get(
        f"/api/v1/applications/{application_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _applicant_id_for_application(db_session, application_id: str) -> uuid.UUID:
    app_row = await db_session.get(Application, uuid.UUID(application_id))
    assert app_row is not None
    return app_row.applicant_id


async def _cleanup_applicant(db_session, applicant_id: uuid.UUID) -> None:
    await db_session.execute(delete(Applicant).where(Applicant.id == applicant_id))
    await db_session.commit()


def _fresh_email() -> str:
    return f"test-{uuid.uuid4().hex[:12]}@creditlens.demo"


@pytest.fixture
async def underwriter_token(client, db_session):
    email = _fresh_email()
    await _create_user(db_session, email, "underwriter")
    return await _login(client, email)


@pytest.fixture
async def auditor_token(client, db_session):
    email = _fresh_email()
    await _create_user(db_session, email, "auditor")
    return await _login(client, email)


@pytest.mark.asyncio
@pytest.mark.parametrize("persona_id,expected_outcome", sorted(EXPECTED_OUTCOMES.items()))
async def test_persona_pipeline_reaches_expected_outcome(
    client, db_session, underwriter_token, persona_id, expected_outcome
):
    """The pipeline's own outcome for personas whose expected result depends
    only on score/completeness (not on the two collision personas, tested
    separately below since they must run as a P05-then-P06 pair)."""
    application_id = await _submit_persona(client, underwriter_token, persona_id)
    applicant_id = await _applicant_id_for_application(db_session, application_id)
    try:
        detail = await _get_application(client, underwriter_token, application_id)
        assert detail["stage"] == "COMPLETE", detail
        assert detail["outcome"] == expected_outcome, (
            f"{persona_id}: expected {expected_outcome}, got {detail['outcome']} "
            f"(score={detail['score']}, fraud={detail['fraud_report']['severity']}, "
            f"reasons={detail.get('decision', {}).get('reason_codes')})"
        )

        # Precedent panel: k<=50 matches, sample_size consistent, valid Wilson CI.
        if detail.get("precedents"):
            prec = detail["precedents"]
            assert 0 < prec["sample_size"] <= 50
            assert len(prec["matches"]) == prec["sample_size"]
            assert 0.0 <= prec["ci_lower"] <= prec["ci_upper"] <= 1.0
            if persona_id == "P10":
                rules = detail.get("decision", {}).get("rules_fired", [])
                assert any("TWO_SIGNAL_DOWNGRADE" in r for r in rules), rules
                assert prec["agrees_with_scorecard"] is False
            elif persona_id == "P11":
                rules = detail.get("decision", {}).get("rules_fired", [])
                assert any("TWO_SIGNAL_UPGRADE" in r for r in rules), rules
                assert prec["agrees_with_scorecard"] is False
            rows = (
                (
                    await db_session.execute(
                        select(PrecedentMatch).where(
                            PrecedentMatch.application_id == uuid.UUID(application_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == prec["sample_size"]

        # Sanitizer invariance, proven against the REAL pipeline (not just the
        # pure-function unit tests from Phase 5): the persisted ScoringInput
        # (scorecard_results.features) must contain none of the applicant's
        # PII/protected attributes, even though the pipeline's raw_context
        # (app/pipeline.py's SANITIZING stage) was built directly from them.
        scorecard_row = await db_session.scalar(
            select(ScorecardResult).where(
                ScorecardResult.application_id == uuid.UUID(application_id)
            )
        )
        assert scorecard_row is not None
        leaked = _FORBIDDEN_SCORING_KEYS & set(scorecard_row.features.keys())
        assert not leaked, f"sanitizer leaked protected keys into ScoringInput: {leaked}"

        # Audit chain integrity holds after a real pipeline run.
        verify_result = await verify_chain(db_session)
        assert verify_result["valid"] is True
    finally:
        await _cleanup_applicant(db_session, applicant_id)


@pytest.mark.asyncio
async def test_p06_collision_after_p05_produces_decline_with_high_severity(
    client, db_session, underwriter_token
):
    """THE syndicate collision demo, run through the real API in the order a
    human underwriter would: submit P05, then P06. P06's bill visibly reuses
    P05's on-file document under a different identity."""
    p05_id = await _submit_persona(client, underwriter_token, "P05")
    p05_applicant_id = await _applicant_id_for_application(db_session, p05_id)
    try:
        p05_detail = await _get_application(client, underwriter_token, p05_id)
        assert p05_detail["outcome"] == "APPROVE", p05_detail

        p06_id = await _submit_persona(client, underwriter_token, "P06")
        p06_applicant_id = await _applicant_id_for_application(db_session, p06_id)
        try:
            p06_detail = await _get_application(client, underwriter_token, p06_id)
            assert p06_detail["outcome"] == "DECLINE", p06_detail
            assert p06_detail["fraud_report"]["severity"] == "HIGH"
            collisions = [
                f
                for f in p06_detail["fraud_report"]["findings"]
                if f["check_name"] == "phash_collision" and f["severity"] == "HIGH"
            ]
            assert collisions, p06_detail["fraud_report"]["findings"]
            assert collisions[0]["evidence"]["other_applicant_id"] == str(p05_applicant_id)

            # The fraud/graph endpoint surfaces this same collision as an edge.
            graph_resp = await client.get(
                "/api/v1/fraud/graph", headers={"Authorization": f"Bearer {underwriter_token}"}
            )
            assert graph_resp.status_code == 200
            edges = graph_resp.json()["edges"]
            expected_pair = {str(p05_applicant_id), str(p06_applicant_id)}
            assert any({e["applicant_a"], e["applicant_b"]} == expected_pair for e in edges), edges
        finally:
            await _cleanup_applicant(db_session, p06_applicant_id)
    finally:
        await _cleanup_applicant(db_session, p05_applicant_id)


@pytest.mark.asyncio
async def test_override_preserves_system_outcome_and_records_final_outcome(
    client, db_session, underwriter_token
):
    application_id = await _submit_persona(client, underwriter_token, "P02")
    applicant_id = await _applicant_id_for_application(db_session, application_id)
    try:
        before = await _get_application(client, underwriter_token, application_id)
        system_outcome = before["outcome"]
        assert system_outcome == "REFER"

        resp = await client.post(
            f"/api/v1/applications/{application_id}/override",
            json={"outcome": "APPROVE", "reason": "Manually verified income with the applicant."},
            headers={"Authorization": f"Bearer {underwriter_token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["system_outcome"] == system_outcome
        assert body["final_outcome"] == "APPROVE"

        after = await _get_application(client, underwriter_token, application_id)
        assert after["outcome"] == system_outcome  # the system's own decision is never rewritten
        assert after["final_outcome"] == "APPROVE"
        assert after["override_reason"] == "Manually verified income with the applicant."

        events = (
            (
                await db_session.execute(
                    select(AuditLog).where(
                        AuditLog.application_id == uuid.UUID(application_id),
                        AuditLog.event_type == "DECISION_OVERRIDDEN",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].payload["final_outcome"] == "APPROVE"
    finally:
        await _cleanup_applicant(db_session, applicant_id)


@pytest.mark.asyncio
async def test_override_requires_underwriter_or_admin_role(client, db_session, auditor_token):
    """auditor is read-only (CLAUDE.md's role matrix); override is a write."""
    resp = await client.post(
        f"/api/v1/applications/{uuid.uuid4()}/override",
        json={"outcome": "APPROVE", "reason": "x"},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_killed_pipeline_mid_run_leaves_failed_not_partial_decision(
    client, db_session, underwriter_token, monkeypatch
):
    """A stage failure must never leave a half-written decision (CLAUDE.md
    Phase 6 requirement) -- simulated here by making the SCORING stage raise,
    well after FRAUD_CHECK has already committed real findings."""
    import app.pipeline as pipeline_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated crash mid-pipeline")

    monkeypatch.setattr(pipeline_module, "compute_score", _boom)

    application_id = await _submit_persona(client, underwriter_token, "P01")
    applicant_id = await _applicant_id_for_application(db_session, application_id)
    try:
        detail = await _get_application(client, underwriter_token, application_id)
        assert detail["stage"] == "FAILED", detail
        assert detail["error_code"] == "PIPELINE_UNEXPECTED_ERROR"
        assert detail["outcome"] is None
        assert detail["decision"] is None

        artifacts = (
            (
                await db_session.execute(
                    select(DecisionArtifact).where(
                        DecisionArtifact.application_id == uuid.UUID(application_id),
                        DecisionArtifact.kind == "decision",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert artifacts == []
    finally:
        await _cleanup_applicant(db_session, applicant_id)


def test_grounding_verifier_rejects_a_doctored_summary():
    """The LLM never gets to introduce a number the computed values don't
    contain -- CLAUDE.md's grounding requirement, tested directly against
    is_grounded() rather than through a live LLM call (MOCK_LLM=true never
    exercises the real Gemini summary path in this test suite)."""
    computed_values = {
        "outcome": "REFER",
        "score": 58,
        "max_score": 100,
        "fraud_severity": "LOW",
        "data_completeness": 1.0,
        "reason_codes": ["RC02"],
    }
    honest = "This application was referred, based on a scorecard total of 58 out of 100."
    ok, evidence = is_grounded(honest, computed_values)
    assert ok, evidence

    doctored = (
        "This application was referred, based on a scorecard total of 58 out of 100. "
        "The applicant has a strong repayment history with 92% on-time payments."
    )
    ok, evidence = is_grounded(doctored, computed_values)
    assert not ok
    assert "92%" in evidence["ungrounded_numbers"]

    forbidden = "This application was referred; note the applicant is male and Hindu."
    ok, evidence = is_grounded(forbidden, computed_values)
    assert not ok
    assert "male" in evidence["forbidden_terms_found"]
    assert "hindu" in evidence["forbidden_terms_found"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/v1/applications", None),
        ("GET", "/api/v1/applications", None),
        ("GET", f"/api/v1/applications/{uuid.uuid4()}", None),
        (
            "POST",
            f"/api/v1/applications/{uuid.uuid4()}/override",
            {"outcome": "APPROVE", "reason": "x"},
        ),
        ("GET", f"/api/v1/applications/{uuid.uuid4()}/notice", None),
        ("GET", "/api/v1/fraud/graph", None),
        ("GET", "/api/v1/meta/scorecard", None),
        ("GET", "/api/v1/audit", None),
        ("GET", "/api/v1/demo/personas", None),
        ("POST", "/api/v1/demo/personas/P01/submit", None),
    ],
)
async def test_every_phase6_endpoint_requires_authentication(client, method, path, body):
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


@pytest.mark.asyncio
async def test_audit_and_application_write_rbac_split(
    client, db_session, underwriter_token, auditor_token
):
    # GET /audit is auditor/admin only -- underwriter has NO audit-log access
    # at all (CLAUDE.md's role matrix, distinct from the read-everything-else
    # role most other endpoints grant it).
    resp = await client.get(
        "/api/v1/audit", headers={"Authorization": f"Bearer {underwriter_token}"}
    )
    assert resp.status_code == 403

    # Conversely, an auditor CAN read applications (read-only across the
    # board) but cannot create one (write-only for underwriter/admin).
    resp = await client.get(
        "/api/v1/applications", headers={"Authorization": f"Bearer {auditor_token}"}
    )
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/applications",
        data={"kyc": "{}"},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_p09_adversarial_injection_pipeline_flags_refer_and_preserves_features(
    client, db_session, underwriter_token
):
    """P09 demo persona contains an adversarial prompt injection in the utility bill.
    The full end-to-end pipeline must:
    1. Detect the injection via guardrails or suspected_instruction_text flag.
    2. Cap the final decision outcome at REFER with RC07 reason code.
    3. Scorecard features must NOT be distorted by the prompt payload.
    """
    application_id = await _submit_persona(client, underwriter_token, "P09")
    applicant_id = await _applicant_id_for_application(db_session, application_id)
    try:
        detail = await _get_application(client, underwriter_token, application_id)
        assert detail["stage"] == "COMPLETE", detail
        assert detail["outcome"] == "REFER", detail

        # Verify fraud findings contain prompt injection flag
        fraud_report = detail.get("fraud_report", {})
        findings = fraud_report.get("findings", [])
        check_names = [f["check_name"] for f in findings]
        assert any(
            name in ("prompt_injection_pattern", "model_flagged_instruction_text")
            for name in check_names
        ), f"Expected prompt injection finding in {check_names}"

        # Verify reason codes include RC07
        decision = detail.get("decision", {})
        assert "RC07" in decision.get("reason_codes", [])

        # Verify scorecard features exist and are numeric (not distorted)
        scorecard_row = await db_session.scalar(
            select(ScorecardResult).where(
                ScorecardResult.application_id == uuid.UUID(application_id)
            )
        )
        assert scorecard_row is not None
        feats = scorecard_row.features
        # Utility features must be present and valid
        assert feats.get("utility_tenure_months") is not None
        assert feats.get("utility_on_time_ratio") is not None
        # Must be invariant (10 months tenure, on-time ratio based on history, not 100 or infinite)
        assert feats["utility_tenure_months"] <= 24.0
        assert 0.0 <= feats["utility_on_time_ratio"] <= 1.0
    finally:
        await _cleanup_applicant(db_session, applicant_id)
