"""Frozen proposal for the first private cash-equity data slice; never fetches."""
from __future__ import annotations

import hashlib
import json

COHORT = ("RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "ITC", "LT",
          "SUNPHARMA", "BHARTIARTL", "NTPC", "TATASTEEL", "M&M")


def proposal() -> dict[str, object]:
    """An engineering cohort, not picks, historical index membership or a licence."""
    body: dict[str, object] = {
        "format": "cash-equity-private-pilot-v1",
        "source_candidate": "UPSTOX_HISTORICAL_V3_DAILY",
        "cohort": list(COHORT), "cohort_basis": "PURPOSIVE_ENGINEERING_SET_NOT_PIT_UNIVERSE",
        "selection_warning": "Survivorship and selection limitations; not all-NSE performance",
        "start": "2022-01-01", "end": "2024-12-31", "unit": "days", "interval": 1,
        "annual_windows": [[f"{year}-01-01", f"{year}-12-31"] for year in (2022, 2023, 2024)],
        "equity_request_budget": 36, "maximum_rows_per_response": 1200,
        "storage": "PRIVATE_ORIGINAL_RESPONSES_PLUS_DERIVED_PARQUET_NOT_SUPABASE",
        "warmup": "2022; do not score insufficient-history rows",
        "evaluation": "2023-2024 retrospective chronological development, not untouched OOS",
        "prior_exposure": "KNOWN_USED_OR_UNKNOWN_NOT_UNSEEN",
        "baselines": ["CASH_NO_TRADE", "SAME_COHORT_BUY_HOLD", "EXISTING_FROZEN_RULE"],
        "index_reference": "NIFTY price reference optional; never relabel it total return",
        "flat_cost_stresses_bps": [30, 60, 100],
        "flat_cost_status": "SCENARIOS_NOT_ACCOUNT_CHARGES",
        "dated_fee_components": ["BUY_AND_SELL_STT", "BUY_STAMP", "EXCHANGE_AND_IPFT",
                                 "SEBI", "BROKERAGE_CAP_AND_MINIMUM", "GST_TAXABLE_BASE",
                                 "SELL_DP_PER_ISIN_DAY", "SLIPPAGE_AND_UNFILLED_ORDERS"],
        "fee_account_schedule_verified": False,
        "provider_clarification": "https://community.upstox.com/t/clarification-on-upstox-historical-candle-v3-data-usage-for-personal-backtesting-and-ml-research/18061/2",
        "rights_scope": "Provider reply supports private own-account research, not redistribution",
        "preconditions": ["OWNER_CONFIRMS_PRIVATE_SCOPE_AND_BOUNDED_ACQUISITION",
                          "RESOLVE_AND_FREEZE_SYMBOL_ISIN_BINDINGS_WITHOUT_SILENT_SUBSTITUTION",
                          "RECONCILE_PRICE_ADJUSTMENTS_ACTIONS_AND_DIVIDENDS",
                          "CHECK_CALENDAR_COVERAGE_DUPLICATES_AND_GAPS",
                          "FREEZE_EXISTING_RULE_AND_RECORD_ALL_TRIALS",
                          "SEPARATE_SCENARIO_COSTS_FROM_VERIFIED_DATED_FEES"],
        "credentials": "EXISTING_PRIVATE_READ_ONLY_ROUTE_ONLY; NEVER_GENERATE_OR_ROTATE_HERE",
        "data_admission_authorised": False, "training_eligible": False,
        "performance_claim_verified": False, "promotion_authorised": False,
        "network_calls": 0, "data_reads": 0, "writes": 0,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**body, "proposal_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
