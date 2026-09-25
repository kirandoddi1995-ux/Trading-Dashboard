"""Offline acceptance coverage: fixtures are synthetic, never market evidence."""
import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from derivative_contracts import digest, resolve_contract, FoundationError
from derivative_quotes import QuotePolicy, decode_v3
from derivative_preflight import evaluate
from derivative_restrictions import parse_ban, ban_url, restriction

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 25, 5, tzinfo=timezone.utc)


@pytest.fixture
def inputs():
    master = dict(instrument_key="NSE_FO|123", exchange="NSE", segment="NSE_FO",
                  underlying_key="NSE_EQ|ABC", underlying_symbol="ABC", underlying_type="EQUITY",
                  weekly=False, instrument_type="CE", lot_size=10, tick_size="5",
                  strike_price="100", expiry=int(datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp()*1000))
    rules = dict(source="https://www.nseindia.com/reviewed-test-fixture", known_at=(NOW-timedelta(days=1)).isoformat(),
                 effective_from=NOW.isoformat(), effective_until=(NOW+timedelta(hours=5)).isoformat(),
                 expiry_at="2026-10-27T15:30:00+05:30", session_open="2026-09-25T09:15:00+05:30",
                 session_close="2026-09-25T15:30:00+05:30", session_date="2026-09-25",
                 settlement="PHYSICAL", delivery="LONG_CALL_RECEIVE_SHARES", corporate_action_version="test-none",
                 corporate_action_status="VERIFIED", tenor="MONTHLY", tick_scale="0.01",
                 instrument_key=master["instrument_key"], master_hash=digest(master), exchange="NSE",
                 segment="NSE_FO", trading_status="ACTIVE")
    q = dict(key=master["instrument_key"], source_at=NOW-timedelta(seconds=1),
             received_at=NOW-timedelta(seconds=.5), generation=1, source="UPSTOX_V3_FULL",
             bid="10", ask="10.05", bid_size=50, ask_size=50, reference=8,
             oi=1000, iv=".2", greeks=dict(delta=".5", gamma=".1", theta="-.1", vega=".2"))
    underlying = dict(q, key=master["underlying_key"], reference=80, bid="99.95", ask="100.05")
    ban = parse_ban(b"SYMBOL\n", trading_date=NOW.date(), source=ban_url(NOW.date()), received_at=NOW)
    return dict(master=master, rules=rules, quotes={q["key"]: q, underlying["key"]: underlying},
                now=NOW, generation=1, quantity=10, side="BUY",
                policy=QuotePolicy(5, 2, Decimal(".02"), "test-v1"), ban=ban)


def test_valid_snapshot_decimal_ask_not_ltp_and_not_approval(inputs):
    result = evaluate(**inputs)
    assert result.eligible, result.reasons
    assert result.snapshot["reference_price"] == Decimal("10.05")
    assert result.snapshot["quotes"][inputs["master"]["underlying_key"]]["reference"] == Decimal("100")
    assert not result.permits()
    assert not result.permits(now=NOW, governance_approved=False, manual_reviewed=True)
    assert not result.permits(now=NOW, governance_approved=True, manual_reviewed=False)
    assert result.permits(now=NOW, governance_approved=True, manual_reviewed=True)
    assert not result.permits(now=NOW+timedelta(seconds=6),governance_approved=True,manual_reviewed=True)
    inputs["side"] = "SELL"
    assert evaluate(**inputs).snapshot["reference_price"] == Decimal("10")


@pytest.mark.parametrize("field,value", [("exchange","NSE_IX"),("lot_size",0),("tick_size",0),
                                        ("expiry",1),("weekly",True),("underlying_key",None)])
def test_contract_changes_and_unsupported_venue_block(inputs, field, value):
    inputs["master"][field] = value
    assert not evaluate(**inputs).eligible


@pytest.mark.parametrize("field,value", [("corporate_action_status","UNKNOWN"),("trading_status","SUSPENDED"),
                                        ("session_date","2026-09-24"),("tenor","QUARTERLY"),
                                        ("settlement","UNKNOWN"),("source",None)])
def test_rule_failures_block(inputs, field, value):
    inputs["rules"][field] = value
    assert not evaluate(**inputs).eligible


@pytest.mark.parametrize("field,value", [("bid","11"),("ask",None),("ask_size",0),("bid_size",None),
    ("ask","10.011"),("source_at",NOW-timedelta(seconds=30)),("received_at",NOW+timedelta(seconds=1)),
    ("generation",0),("source","rest"),("iv",None),("greeks",{}),("oi",None)])
def test_bad_quotes_never_fallback(inputs, field, value):
    inputs["quotes"][inputs["master"]["instrument_key"]][field] = value
    assert not evaluate(**inputs).eligible


def test_alignment_size_and_reconnect(inputs):
    inputs["quotes"][inputs["master"]["underlying_key"]]["source_at"] = NOW-timedelta(seconds=4)
    assert not evaluate(**inputs).eligible
    inputs["quotes"][inputs["master"]["underlying_key"]]["source_at"] = NOW-timedelta(seconds=1)
    inputs["quantity"] = 60
    assert not evaluate(**inputs).eligible
    inputs["quantity"] = 11
    assert not evaluate(**inputs).eligible
    inputs["quantity"] = 10
    inputs["generation"] = 2
    assert not evaluate(**inputs).eligible


@pytest.mark.parametrize("raw", [b"", b"<html>error</html>", b"SYMBOL\nA,B", b"SYMBOL\nABC\nABC\n"])
def test_invalid_ban_is_not_empty_clear(raw):
    with pytest.raises(FoundationError):
        parse_ban(raw, trading_date=NOW.date(), source=ban_url(NOW.date()), received_at=NOW)


def test_ban_date_entries_rolls_and_unknown(inputs):
    for action in ("ENTRY", "ROLL"):
        inputs["action"] = action
        inputs["ban"] = parse_ban(b"SYMBOL\nABC\n", trading_date=NOW.date(), source=ban_url(NOW.date()), received_at=NOW)
        assert not evaluate(**inputs).eligible
    inputs["ban"] = None
    assert not evaluate(**inputs).eligible
    yesterday = NOW.date()-timedelta(days=1)
    inputs["ban"] = parse_ban(b"SYMBOL\n", trading_date=yesterday, source=ban_url(yesterday), received_at=NOW)
    assert not evaluate(**inputs).eligible


def test_exit_hedge_removal_sign_reversal_and_missing_positions(inputs):
    contract = resolve_contract(inputs["master"], inputs["rules"], now=NOW)
    banned = parse_ban(b"SYMBOL\nABC\n", trading_date=NOW.date(), source=ban_url(NOW.date()), received_at=NOW)
    exposure = dict(complete=True, source="CLEARING_CORPORATION", trading_date=NOW.date().isoformat(),
                    valid_until=(NOW+timedelta(seconds=10)).isoformat(),
                    positions_before={'long':20,'short':-10}, positions_after={'long':15,'short':-10},
                    cc_deltas={'long':1,'short':1})
    assert restriction(contract,banned,trading_date=NOW.date(),now=NOW,action="EXIT",exposure=exposure)=="VALID_BANNED"
    for value in ({'long':20,'short':-5}, {'long':5,'short':-10}):
        with pytest.raises(FoundationError):
            restriction(contract,banned,trading_date=NOW.date(),now=NOW,action="EXIT",exposure=dict(exposure,positions_after=value))
    for invalid in (None, dict(exposure,source="MANUAL_CONFIRMATION"), dict(exposure,source="RESEARCH")):
        with pytest.raises(FoundationError):
            restriction(contract,banned,trading_date=NOW.date(),now=NOW,action="EXIT",exposure=invalid)


def test_v3_timestamp_provenance_and_partial_update():
    message = {"currentTs":int(NOW.timestamp()*1000), "feeds":{"K":{"fullFeed":{"marketFF":{
        "ltpc":{"ltp":10,"ltt":123}, "marketLevel":{"bidAskQuote":[{"bidP":9,"askP":10,"bidQ":5,"askQ":6}]},
        "oi":100, "iv":.2, "optionGreeks":{"delta":.5}}}}}}
    q = decode_v3(message,received_at=NOW,generation=3)["K"]
    assert q["ask"] == 10 and q["ask_size"] == 6
    assert q["source_at"] == NOW and q["last_trade_at"] == 123 and q["exchange_at"] is None
    message["feeds"]["K"] = {"ltpc":{"ltp":11}}
    assert decode_v3(message,received_at=NOW,generation=3)["K"]["ask"] is None


def test_all_three_app_paths_wired_no_quick_ltp_bypass():
    tree = ast.parse((ROOT/"app.py").read_text(encoding="utf-8"))
    functions = {n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    for name in ("_quick_top_trade_ideas","build_option_recommendation"):
        calls = [n.func.id for n in ast.walk(functions[name]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
        assert "derivative_entry_preflight" in calls
    quick = ast.unparse(functions["_quick_top_trade_ideas"])
    assert 'get(\'ltp\')' not in quick and "Target (+25%)" not in quick and "RESEARCH ONLY" in quick
    source = (ROOT/"app.py").read_text(encoding="utf-8")
    assert 'not futures_foundation.eligible or fut_bias' in source
    assert 'entry = float(futures_foundation.snapshot["reference_price"])' in source
    preflight = ast.unparse(functions['derivative_entry_preflight'])
    assert "phase != 'NORMAL_OPEN'" in preflight
    assert 'self.derivative_segment_status.clear()' in source


def test_existing_equity_gateway_still_accepts_original_receipt_shape():
    from market_data_gateway import MarketDataGateway
    assert MarketDataGateway.annotate_quote({"last_price":100,"_ts":10},now=11)["_age_seconds"] == 1


def test_research_or_manual_payload_cannot_supply_missing_contract(inputs):
    inputs["rules"] = {"manual_confirmation":True,"equity_capture":inputs["rules"]}
    assert not evaluate(**inputs).eligible


def test_jsonb_numeric_representation_is_not_a_contract_change():
    assert digest({'lot':10,'tick':5.0}) == digest({'lot':10.0,'tick':5})
    assert digest({'lot':10}) != digest({'lot':11})
    assert digest({'lot':1}) != digest({'lot':True})
    assert digest({'lot':10}) != digest({'lot':'10'})


def test_index_reference_has_no_executable_book_but_needs_value_timestamp(inputs):
    inputs['master']['underlying_type'] = 'INDEX'
    inputs['rules']['master_hash'] = digest(inputs['master'])
    q = inputs['quotes'][inputs['master']['underlying_key']]
    q.update(bid=None, ask=None, last_trade_at=int(NOW.timestamp()*1000))
    assert evaluate(**inputs).eligible
    q['last_trade_at'] -= 100_000
    assert not evaluate(**inputs).eligible
