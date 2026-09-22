import json

from synthgen.demo_pack import build_demo_pack
from synthgen.personas import PERSONAS


def test_demo_pack_builds_all_eleven_personas_with_expected_docs(tmp_path):
    build_demo_pack(tmp_path)
    demo_root = tmp_path / "demo_pack"
    assert sorted(p.name for p in demo_root.iterdir()) == [f"P{i:02d}" for i in range(1, 12)]

    for spec in PERSONAS:
        out_dir = demo_root / spec.persona_id
        kyc = json.loads((out_dir / "kyc.json").read_text())
        expected = json.loads((out_dir / "expected.json").read_text())
        assert kyc["full_name"] == spec.kyc_name
        assert expected["expected_outcome"] == spec.expected_outcome
        assert expected["docs_present"] == spec.docs

        if "GIG_PAYOUT" in spec.docs:
            assert any((out_dir / f"gig_payout.{ext}").exists() for ext in ("png", "jpg"))
        if "UTILITY_BILL" in spec.docs:
            assert (out_dir / "utility_bill.jpg").exists()
        if "BANK_STATEMENT" in spec.docs:
            assert (out_dir / "bank_statement.csv").exists()


def test_p08_is_a_thin_file_bank_only():
    spec = next(p for p in PERSONAS if p.persona_id == "P08")
    assert spec.docs == ["BANK_STATEMENT"]


def test_p06_reuses_p05_utility_bill():
    p05 = next(p for p in PERSONAS if p.persona_id == "P05")
    p06 = next(p for p in PERSONAS if p.persona_id == "P06")
    assert p06.reuse_utility_bill_of == "P05"
    assert p05.reuse_utility_bill_of is None


def test_p07_has_identity_mismatch_signals():
    spec = next(p for p in PERSONAS if p.persona_id == "P07")
    assert spec.document_name_override is not None
    assert spec.document_name_override != spec.kyc_name
    assert spec.account_last4_mismatch is True


def test_p09_has_adversarial_injection_utility():
    spec = next(p for p in PERSONAS if p.persona_id == "P09")
    assert spec.injection_utility == "visible"
    assert spec.expected_outcome == "REFER"


def test_p10_is_blind_spot_archetype():
    spec = next(p for p in PERSONAS if p.persona_id == "P10")
    assert spec.utility_tenure_months >= 16
    assert spec.gig_tenure_weeks <= 8
    assert spec.gig_earnings_cv >= 0.35
    assert spec.expected_outcome == "REFER"


def test_p11_is_resilient_archetype():
    spec = next(p for p in PERSONAS if p.persona_id == "P11")
    assert spec.utility_tenure_months <= 6
    assert spec.gig_tenure_weeks >= 50
    assert spec.gig_earnings_cv <= 0.20
    assert spec.expected_outcome == "REFER"
