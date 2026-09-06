import datetime as dt

import numpy as np
import pandas as pd
import pytest

from research_features import (
    RESEARCH_DEFINITIONS_BY_NAME,
    iv_surface_shape_features,
    option_oi_skew_features,
    publish_research_features,
    unusual_option_activity_features,
)
from iv_surface import black_scholes_greeks, black_scholes_price, normalize_iv_surface


UTC = dt.timezone.utc


def option_row(*, key, available_at, option_type="CE", strike=100, years=0.05,
               log_moneyness=0.0, delta=0.5, iv=20.0, volume=100,
               open_interest=1000, valid=True, expiry="2026-09-24"):
    return {
        "instrument_key": key, "expiry": expiry, "strike": strike,
        "option_type": option_type, "years": years,
        "log_moneyness": log_moneyness, "model_iv": iv,
        "model_delta": delta, "volume": volume, "open_interest": open_interest,
        "effective_at": available_at, "available_at": available_at,
        "production_valid": valid,
    }


def test_option_research_definitions_are_registered_and_non_scoring():
    expected = {
        "option_volume_activity_robust_z", "option_oi_activity_robust_z",
        "unusual_option_activity_score", "put_call_oi_skew_near_money",
        "put_call_oi_skew_far_otm", "put_call_oi_skew_ntm_minus_fotm",
        "iv_term_structure_steepness", "iv_skew_steepness",
    }
    assert expected.issubset(RESEARCH_DEFINITIONS_BY_NAME)


def test_normalized_chain_preserves_pit_activity_inputs_without_weakening_iv_gate():
    now = pd.Timestamp("2026-09-07 10:00", tz="Asia/Kolkata")
    expiry = pd.Timestamp("2026-10-29 15:30", tz="Asia/Kolkata")
    years = (expiry - now).total_seconds() / (365 * 86400)
    price = black_scholes_price(100, 100, years, 0.25, option_type="CE")
    greeks = black_scholes_greeks(100, 100, years, 0.25, option_type="CE")
    chain = [{"strike_price": 100, "call_options": {
        "instrument_key": "NSE_FO|CALL",
        "market_data": {"bid_price": price - 0.01, "ask_price": price + 0.01,
                        "volume": 1200, "oi": 3400, "prev_oi": 3000},
        "option_greeks": {"iv": 0.25, **greeks},
    }}]
    surface = normalize_iv_surface(chain, 100, expiry, now=now)
    row = surface.iloc[0]
    assert row["instrument_key"] == "NSE_FO|CALL"
    assert row["volume"] == 1200 and row["open_interest"] == 3400
    assert bool(row["option_activity_data_valid"])
    assert bool(row["production_valid"])
    assert row["available_at"] == now.tz_convert("UTC")

    chain[0]["call_options"]["market_data"].pop("oi")
    incomplete = normalize_iv_surface(chain, 100, expiry, now=now)
    assert not bool(incomplete.iloc[0]["option_activity_data_valid"])
    assert bool(incomplete.iloc[0]["production_valid"])
    with pytest.raises(ValueError, match="cannot follow"):
        normalize_iv_surface(
            chain, 100, expiry, now=now,
            provider_observed_at=now + pd.Timedelta(seconds=1), available_at=now,
        )


def test_unusual_activity_uses_only_prior_same_context_rolling_history():
    as_of = dt.datetime(2026, 9, 21, 8, tzinfo=UTC)
    history = []
    for index in range(20):
        history.append({
            **option_row(
                key="NSE_FO|CALL", available_at=as_of - dt.timedelta(days=20-index),
                volume=100 + index * 2, open_interest=1000 + index * 10,
            ),
            "capture_context": "AFTERNOON_1437",
        })
    # A huge morning print must not contaminate an afternoon cumulative-volume baseline.
    history.append({
        **option_row(key="NSE_FO|CALL", available_at=as_of-dt.timedelta(hours=4),
                     volume=1_000_000, open_interest=1_000_000),
        "capture_context": "MORNING_1007",
    })
    current = pd.DataFrame([
        option_row(key="NSE_FO|CALL", available_at=as_of-dt.timedelta(seconds=1),
                   volume=300, open_interest=1800),
        option_row(key="NSE_FO|REJECTED", available_at=as_of-dt.timedelta(seconds=1),
                   volume=9_999_999, open_interest=9_999_999, valid=False),
    ])
    result = unusual_option_activity_features(
        current, pd.DataFrame(history), as_of=as_of,
        capture_context="AFTERNOON_1437", minimum_history=20,
    )
    assert len(result) == 1
    assert result.iloc[0]["feature_status"] == "PASS"
    assert result.iloc[0]["unusual_option_activity_score"] > 3
    assert result.attrs["validation_rejected"] == 1
    assert result.attrs["consumed_by_scoring"] is False


def test_unusual_activity_fails_closed_for_missing_oi_or_flat_baseline():
    as_of = dt.datetime(2026, 9, 21, 8, tzinfo=UTC)
    history = pd.DataFrame([{
        **option_row(key="NSE_FO|CALL", available_at=as_of-dt.timedelta(days=20-index)),
        "capture_context": "MORNING_1007",
    } for index in range(20)])
    missing = pd.DataFrame([option_row(
        key="NSE_FO|CALL", available_at=as_of-dt.timedelta(seconds=1),
        open_interest=np.nan,
    )])
    result = unusual_option_activity_features(
        missing, history, as_of=as_of, capture_context="MORNING_1007",
    )
    assert result.iloc[0]["feature_status"] == "UNAVAILABLE"
    assert pd.isna(result.iloc[0]["unusual_option_activity_score"])

    current = pd.DataFrame([option_row(
        key="NSE_FO|CALL", available_at=as_of-dt.timedelta(seconds=1), volume=200,
        open_interest=1200,
    )])
    flat = unusual_option_activity_features(
        current, history, as_of=as_of, capture_context="MORNING_1007",
    )
    assert flat.iloc[0]["feature_status"] == "UNAVAILABLE"
    assert "variation" in flat.iloc[0]["failure"]

    with pytest.raises(ValueError, match="at least 20"):
        unusual_option_activity_features(
            current, history, as_of=as_of, capture_context="MORNING_1007",
            minimum_history=19,
        )


def test_option_features_use_shared_research_publication_path_only():
    now = dt.datetime(2026, 9, 7, 8, tzinfo=UTC)

    class CapturingWriter:
        def __init__(self):
            self.calls = []

        def record(self, **kwargs):
            self.calls.append(kwargs)
            return {"stored": True}

    writer = CapturingWriter()
    outcome = publish_research_features(
        writer, instrument_key="NSE_INDEX|Nifty 50",
        values={
            "put_call_oi_skew_near_money": 0.25,
            "iv_skew_steepness": -30.0,
        },
        effective_at=now, available_at=now,
    )
    assert outcome == {"stored": 2, "rejected": 0, "consumed_by_scoring": False}
    assert {call["definition"].name for call in writer.calls} == {
        "put_call_oi_skew_near_money", "iv_skew_steepness",
    }
    assert all(call["observed_at"] == now for call in writer.calls)


def test_put_call_oi_skew_separates_delta_buckets_and_rejects_missing_oi():
    now = dt.datetime(2026, 9, 7, 8, tzinfo=UTC)
    rows = [
        option_row(key="near-c", available_at=now, option_type="CE", delta=0.50,
                   open_interest=100),
        option_row(key="near-p", available_at=now, option_type="PE", delta=-0.50,
                   open_interest=300),
        option_row(key="far-c", available_at=now, option_type="CE", delta=0.15,
                   log_moneyness=0.10, open_interest=400),
        option_row(key="far-p", available_at=now, option_type="PE", delta=-0.15,
                   log_moneyness=-0.10, open_interest=100),
        option_row(key="bad", available_at=now, option_type="PE", delta=-0.50,
                   open_interest=99_999, valid=False),
    ]
    result = option_oi_skew_features(pd.DataFrame(rows), as_of=now)
    assert result["status"] == "PASS"
    assert result["values"]["put_call_oi_skew_near_money"] == pytest.approx(0.5)
    assert result["values"]["put_call_oi_skew_far_otm"] == pytest.approx(-0.6)
    assert result["values"]["put_call_oi_skew_ntm_minus_fotm"] == pytest.approx(1.1)
    assert result["diagnostics"]["validation_rejected"] == 1

    rows[1]["open_interest"] = np.nan
    unavailable = option_oi_skew_features(pd.DataFrame(rows), as_of=now)
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["values"] == {}

    rows[1]["open_interest"] = 300
    rows[3]["open_interest"] = 0
    illiquid = option_oi_skew_features(pd.DataFrame(rows), as_of=now)
    assert illiquid["status"] == "UNAVAILABLE"
    assert any("positive" in failure for failure in illiquid["failures"])


def test_iv_surface_shape_uses_valid_rows_and_blocks_future_or_calendar_invalid_data():
    now = dt.datetime(2026, 9, 7, 8, tzinfo=UTC)
    rows = []
    for years, expiry, base_iv in ((0.05, "2026-09-24", 20.0),
                                   (0.20, "2026-11-26", 24.0)):
        for log_moneyness in (-0.10, -0.05, 0.0, 0.05, 0.10):
            side = "PE" if log_moneyness < 0 else "CE"
            rows.append(option_row(
                key=f"{expiry}|{side}|{log_moneyness}", available_at=now,
                option_type=side, years=years, expiry=expiry,
                log_moneyness=log_moneyness,
                delta=(-0.2 if side == "PE" else 0.2),
                iv=base_iv - 30 * log_moneyness,
            ))
        # Supply the opposite ATM side so term structure uses call and put evidence.
        rows.append(option_row(
            key=f"{expiry}|PE|ATM", available_at=now, option_type="PE",
            years=years, expiry=expiry, log_moneyness=0.0, delta=-0.5, iv=base_iv,
        ))
    rows.append(option_row(
        key="invalid-outlier", available_at=now, option_type="CE", years=0.05,
        log_moneyness=0.15, iv=9999, valid=False,
    ))
    result = iv_surface_shape_features(pd.DataFrame(rows), as_of=now)
    assert result["status"] == "PASS"
    assert result["values"]["iv_term_structure_steepness"] > 0
    assert result["values"]["iv_skew_steepness"] == pytest.approx(-30, rel=1e-6)
    assert result["diagnostics"]["validation_rejected"] == 1
    assert result["consumed_by_scoring"] is False

    future = pd.DataFrame(rows)
    future.loc[0, "available_at"] = now + dt.timedelta(seconds=1)
    with pytest.raises(ValueError, match="unavailable"):
        iv_surface_shape_features(future, as_of=now)

    calendar_bad = pd.DataFrame(rows)
    calendar_bad.loc[calendar_bad["years"].eq(0.20), "model_iv"] = 5.0
    blocked = iv_surface_shape_features(calendar_bad, as_of=now)
    assert "iv_term_structure_steepness" not in blocked["values"]
    assert any("calendar" in failure.lower() for failure in blocked["failures"])
