import copy
import hashlib
import json

import pytest

from equity_daily_ingest import MAX_BYTES, MAX_ROWS, decode_daily
from equity_eod_pilot import COHORT, proposal

KEY = "NSE_EQ|INE009A01021"


def candle(day="2022-01-03"):
    return [day + "T00:00:00+05:30", 100, 110, 90, 105, 1000, 0]


def raw(rows=None):
    return json.dumps({"status": "success", "data": {"candles": rows or [candle()]}}).encode()


def decode(blob):
    return decode_daily(blob, instrument_key=KEY, start="2022-01-01", end="2024-12-31")


def test_pilot_is_stable_explicitly_selected_and_never_permission():
    plan = proposal()
    assert len(set(COHORT)) == 12
    assert plan == proposal()
    assert plan["equity_request_budget"] == 36
    assert plan["flat_cost_stresses_bps"] == [30, 60, 100]
    assert plan["data_admission_authorised"] is False
    assert plan["training_eligible"] is False
    assert plan["network_calls"] == plan["data_reads"] == plan["writes"] == 0
    assert "NOT_PIT_UNIVERSE" in plan["cohort_basis"]
    assert plan["fee_account_schedule_verified"] is False
    plan["cohort"].append("ALTERED")
    assert len(proposal()["cohort"]) == 12


def test_exact_original_binding_sorted_rows_and_no_authority():
    blob = raw([candle("2022-01-04"), candle()])
    result = decode(blob)
    assert result["source_sha256"] == hashlib.sha256(blob).hexdigest()
    assert [row["date"] for row in result["rows"]] == ["2022-01-03", "2022-01-04"]
    assert result["rows"][0]["open"] == "100"
    for flag in ("rights_verified", "data_admission_authorised", "training_eligible",
                 "performance_claim_verified", "corporate_actions_verified", "calendar_coverage_verified"):
        assert result[flag] is False
    assert result["availability_timestamp"] == "NOT_ESTABLISHED_BY_CANDLE_LABEL"


@pytest.mark.parametrize("position,value", [(1, True), (1, "100"), (1, 0), (1, -1), (1, 10**10),
    (2, 99), (3, 106), (4, None), (5, True), (5, -1), (5, 1.5), (5, 10**15), (6, -1)])
def test_bad_prices_shape_and_integer_types_rejected(position, value):
    row = candle()
    row[position] = value
    with pytest.raises(ValueError):
        decode(raw([row]))


@pytest.mark.parametrize("blob", [b"", b"x" * (MAX_BYTES + 1), b"{", b"\xff", b"[]",
    b'{"status":"success","status":"success"}', b'{"status":"error"}',
    b'{"status":"success","data":{"candles":[]}}', b'{"x":NaN}',
    b'{"status":"success","data":{"candles":null}}'],
    ids=["empty", "oversized", "truncated", "encoding", "array", "duplicate", "error-status",
         "empty-candles", "nan", "null-candles"])
def test_invalid_json_and_boundaries(blob):
    with pytest.raises(ValueError):
        decode(blob)


@pytest.mark.parametrize("day", ["2025-01-01", "2026-01-01", "2021-12-31"])
def test_sealed_or_outside_rows_rejected(day):
    with pytest.raises(ValueError):
        decode(raw([candle(day)]))


@pytest.mark.parametrize("key", ["NSE_INDEX|Nifty 50", "NSE_EQ|bad", "secret", None, True])
def test_no_guessed_or_wrong_segment_binding(key):
    with pytest.raises(ValueError):
        decode_daily(raw(), instrument_key=key, start="2022-01-01", end="2024-12-31")


def test_duplicates_and_rows_limit_and_wrong_timezone():
    for rows in ([candle(), candle()], [candle()] * (MAX_ROWS + 1)):
        with pytest.raises(ValueError):
            decode(raw(rows))
    row = candle()
    row[0] = "2022-01-03T00:00:00Z"
    with pytest.raises(ValueError):
        decode(raw([row]))


def test_decimal_numbers_not_rounded_into_binary_and_input_not_mutated():
    rows = [candle()]
    saved = copy.deepcopy(rows)
    result = decode(raw(rows))
    assert rows == saved
    blob = raw().replace(b"100,", b"100.125,", 1)
    assert decode(blob)["rows"][0]["open"] == "100.125"
    assert result["decoded_sha256"] != decode(blob)["decoded_sha256"]


@pytest.mark.parametrize("start,end", [("20220101", "2024-12-31"), ("2025-01-01", "2025-12-31"),
    ("2024-01-01", "2022-01-01"), ("bad", "2024-12-31")])
def test_request_date_contract(start, end):
    with pytest.raises(ValueError):
        decode_daily(raw(), instrument_key=KEY, start=start, end=end)


@pytest.mark.parametrize("stamp", ["2022-01-03T00:00:00", "2022-01-03T00:00:00+00:00",
    "2022-01-03T10:05:00+05:30", "2022-01-03T00:00:01+05:30", "not-a-time"])
def test_nonreviewed_timestamp_labels_cannot_be_silently_daily(stamp):
    row = candle()
    row[0] = stamp
    with pytest.raises(ValueError):
        decode(raw([row]))


def test_open_label_is_preserved_but_never_availability_or_fill_proof():
    row = candle()
    row[0] = "2022-01-03T09:15:00+05:30"
    result = decode(raw([row]))
    assert result["rows"][0]["provider_timestamp"] == row[0]
    assert result["availability_timestamp"].startswith("NOT_ESTABLISHED")
    assert result["price_basis"].startswith("NOT_VERIFIED")


@pytest.mark.parametrize("rows", [[candle()[:6]], [candle() + ["extra"]], [True]],
                         ids=["short", "long", "boolean"])
def test_candle_shape_is_exact(rows):
    with pytest.raises(ValueError):
        decode(raw(rows))


def test_nonfinite_and_huge_exponent_and_deep_payload_fail_closed():
    for number in (b"NaN", b"Infinity", b"-Infinity", b"1e1000000000"):
        with pytest.raises(ValueError):
            decode(raw().replace(b"100,", number + b",", 1))
    with pytest.raises(ValueError):
        decode(b"[" * 2000 + b"0" + b"]" * 2000)
