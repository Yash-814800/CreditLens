from synthgen import tamper
from synthgen.documents import bank_statement
from synthgen.identity import make_persona
from synthgen.rng import rng_for


def _balance_chain_valid(rows):
    for i in range(1, len(rows)):
        prev = rows[i - 1].balance
        expected = round(prev - (rows[i].debit or 0.0) + (rows[i].credit or 0.0), 2)
        if abs(expected - rows[i].balance) > 0.01:
            return False, i
    return True, None


def _build(seed):
    persona = make_persona("BANK_STATEMENT", seed)
    rng = rng_for("test_bank_statement", seed)
    metadata, rows = bank_statement.build_bank_data(rng, persona, "1234", "ZipRide Partner")
    return rng, metadata, rows


def test_clean_running_balance_is_arithmetically_consistent():
    _, _, rows = _build(1)
    valid, break_idx = _balance_chain_valid(rows)
    assert valid, f"balance chain broke at row {break_idx}"
    assert len(rows) > 100  # ~180 days of activity


def test_csv_round_trips_metadata_then_header_then_rows():
    rng, metadata, rows = _build(2)
    csv_bytes = bank_statement.to_csv_bytes(metadata, rows)
    text = csv_bytes.decode("utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("account_holder,")
    blank_idx = lines.index("")
    assert lines[blank_idx + 1] == "date,narration,ref,debit,credit,balance"


def test_edited_credit_without_rebalancing_breaks_the_chain():
    rng, _, rows = _build(3)
    valid_before, _ = _balance_chain_valid(rows)
    assert valid_before
    rows2, events = tamper.tamper_bank_statement(rng, rows, "edited_credit_without_rebalancing")
    valid_after, _ = _balance_chain_valid(rows2)
    assert not valid_after
    assert len(events) == 1
    assert events[0].type == "edited_credit_without_rebalancing"


def test_inserted_fake_credit_keeps_chain_consistent_hard_case():
    rng, _, rows = _build(4)
    rows2, events = tamper.tamper_bank_statement(rng, rows, "inserted_fake_credit_with_rebalanced_chain")
    valid_after, break_idx = _balance_chain_valid(rows2)
    assert valid_after, f"chain should stay consistent (hard case), broke at {break_idx}"
    assert len(rows2) == len(rows) + 1
    assert len(events) == 1
