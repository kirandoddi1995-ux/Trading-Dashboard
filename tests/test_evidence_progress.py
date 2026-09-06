import datetime as dt

from evidence_progress import ProgressPolicy, summarize_evidence_progress


UTC = dt.timezone.utc


def _equity_record(index, day, *, matured=True, eligible=True, feature=True,
                   strategy_id="equity-scanner-v19.0"):
    decision_at = dt.datetime.combine(day, dt.time(4, 30), tzinfo=UTC)
    return {
        "decision_id": f"decision-{index}",
        "decision_at": decision_at.isoformat(),
        "asset_class": "equity",
        "strategy_id": strategy_id,
        "target_version": "net-excess-execution-v2",
        "horizon_sessions": 5,
        "feature_names": ["scanner_composite_score"] if feature else [],
        "matured": matured,
        "outcome_at": (decision_at + dt.timedelta(days=7)).isoformat() if matured else None,
        "training_eligible": eligible if matured else False,
    }


def _asset(result, key):
    return next(row for row in result["assets"] if row["key"] == key)


def test_progress_is_honestly_zero_when_evidence_spine_is_empty():
    result = summarize_evidence_progress([], now=dt.datetime(2026, 9, 6, tzinfo=UTC))

    assert result["status"] == "PASS"
    assert [row["key"] for row in result["assets"]] == [
        "equity", "options", "futures", "mcx", "smc",
    ]
    for row in result["assets"]:
        assert row["raw_decisions"] == 0
        assert row["matured_observations"] == 0
        assert row["eligible_observations"] == 0
        assert row["oof_eligible"] == 0
        assert row["holdout_observations"] == 0
        assert row["distinct_trading_days"] == 0
        assert row["estimated_threshold_date"] is None
        assert row["status"] == "INSUFFICIENT_EVIDENCE"
        assert row["promotable"] is False


def test_progress_counts_only_real_matured_contract_eligible_rows():
    base = dt.date(2026, 8, 3)
    records = [
        _equity_record(1, base, matured=True, eligible=True),
        _equity_record(2, base + dt.timedelta(days=1), matured=True, eligible=True),
        _equity_record(3, base + dt.timedelta(days=2), matured=True, eligible=False),
        _equity_record(4, base + dt.timedelta(days=3), matured=False, eligible=False),
        _equity_record(5, base + dt.timedelta(days=4), matured=True, eligible=True, feature=False),
        _equity_record(6, base + dt.timedelta(days=5), strategy_id="older-equity-contract"),
    ]

    equity = _asset(
        summarize_evidence_progress(
            records, now=dt.datetime(2026, 8, 20, tzinfo=UTC),
        ),
        "equity",
    )

    assert equity["raw_decisions"] == 5
    assert equity["other_contract_decisions"] == 1
    assert equity["matured_observations"] == 4
    assert equity["eligible_observations"] == 2
    assert equity["rejected_matured_observations"] == 2
    assert equity["distinct_trading_days"] == 2
    assert equity["estimated_threshold_date"] is None
    assert equity["status"] == "INSUFFICIENT_EVIDENCE"
    assert equity["promotable"] is False


def test_progress_derives_partitions_and_date_only_from_observed_pace():
    base = dt.date(2026, 1, 5)
    records = []
    index = 0
    day = base
    while len({record["decision_at"][:10] for record in records}) < 40:
        if day.weekday() < 5:
            for _ in range(3):
                index += 1
                records.append(_equity_record(index, day))
        day += dt.timedelta(days=1)
    policy = ProgressPolicy(
        minimum_total_samples=60,
        minimum_oof_samples=20,
        minimum_holdout_samples=12,
        minimum_observation_days=30,
        minimum_holdout_dates=5,
        holdout_fraction=0.20,
        folds=2,
        minimum_fold_training_samples=10,
        embargo_sessions=1,
    )

    equity = _asset(
        summarize_evidence_progress(
            records,
            now=dt.datetime.combine(day, dt.time(12), tzinfo=UTC),
            policy=policy,
        ),
        "equity",
    )

    assert equity["eligible_observations"] == 120
    assert equity["distinct_trading_days"] == 40
    assert equity["oof_eligible"] > 0
    assert equity["holdout_observations"] > 0
    assert equity["observations_per_elapsed_weekday"] > 0
    assert equity["estimated_threshold_date"] is not None
    assert equity["promotable"] is False
