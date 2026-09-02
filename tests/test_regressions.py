import ast
import datetime
import hashlib
import math
import pathlib
import re
import time
import unittest

import numpy as np
import openpyxl
import pandas as pd

import technical_indicators as ta
import mf_research as mfr
import app_runtime as runtime
import logging


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
SOURCE = APP_PATH.read_text(encoding="utf-8")


class SourceRegressionTests(unittest.TestCase):
    def test_app_parses(self):
        ast.parse(SOURCE)

    def test_plaintext_credential_file_removed(self):
        self.assertFalse((ROOT / "API AND TOPKENS.txt").exists())

    def test_secret_and_database_files_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".streamlit/secrets.toml", ignored)
        self.assertIn("*.sqlite3", ignored)
        self.assertIn("API AND TOPKENS.txt", ignored)

    def test_no_browser_credential_widgets_or_fake_probability(self):
        self.assertNotIn('type="password"', SOURCE)
        self.assertNotIn("compute_walk_forward_probability", SOURCE)
        self.assertNotIn("out_of_sample_win_prob", SOURCE)
        self.assertNotIn("else 55.0", SOURCE)
        self.assertNotIn("else 24500.0", SOURCE)
        self.assertIn("A verified live or recent market price is unavailable", SOURCE)
        self.assertIn("Theoretical fallback values are hidden", SOURCE)

    def test_supported_provider_integrations(self):
        self.assertNotIn("google.generativeai", SOURCE)
        self.assertNotIn("/v2/historical-candle", SOURCE)
        self.assertIn("/v3/historical-candle", SOURCE)
        self.assertIn("google-genai", (ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.assertIn("ProviderCircuitBreaker", SOURCE)

    def test_mutual_fund_provider_fallbacks_and_failure_cache_safety(self):
        self.assertIn("https://portal.amfiindia.com/spages/NAVOpen.txt", SOURCE)
        self.assertIn("https://api.tigzig.com/mf/v1/download?format=latest.csv.gz", SOURCE)
        self.assertIn("https://api.tigzig.com/mf/v1/nav", SOURCE)
        self.assertIn("st.cache_data does not cache exceptions", SOURCE)

        tree = ast.parse(SOURCE)
        parser_node = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_parse_amfi_scheme_master"
        )
        namespace = {}
        exec(compile(ast.Module(body=[parser_node], type_ignores=[]), str(APP_PATH), "exec"), namespace)
        parsed = namespace["_parse_amfi_scheme_master"](
            "Example Mutual Fund\n"
            "Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date\n"
            "123456;INF000000001;;Example Flexi Cap;Direct Plan;Growth Option;42.10;29-Aug-2026\n"
        )
        self.assertEqual(parsed[0]["schemeCode"], "123456")
        self.assertEqual(parsed[0]["fundHouse"], "Example Mutual Fund")
        self.assertEqual(parsed[0]["schemeName"], "Example Flexi Cap - Direct Plan - Growth Option")

    def test_mutual_fund_advanced_metrics_and_forecast_are_coherent(self):
        tree = ast.parse(SOURCE)
        function_node = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "compute_mf_returns"
        )
        namespace = {
            "pd": pd,
            "np": np,
            "mfr": mfr,
            "datetime": datetime,
            "hashlib": hashlib,
            "LOGGER": __import__("logging").getLogger("test"),
        }
        exec(compile(ast.Module(body=[function_node], type_ignores=[]), str(APP_PATH), "exec"), namespace)
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=1500)
        trend = np.linspace(100.0, 240.0, len(dates))
        cycle = 8.0 * np.sin(np.arange(len(dates)) / 35.0)
        nav = np.maximum(10.0, trend + cycle)
        payload = {
            "meta": {"scheme_name": "Example Direct Growth", "fund_house": "Example AMC"},
            "data": [
                {"date": date.strftime("%d-%m-%Y"), "nav": float(value)}
                for date, value in zip(dates, nav)
            ],
        }
        result = namespace["compute_mf_returns"](payload)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result["cagr_5y"])
        self.assertLessEqual(result["max_drawdown"], 0.0)
        self.assertLessEqual(result["forecast_p10"], result["forecast_p50"])
        self.assertLessEqual(result["forecast_p50"], result["forecast_p90"])
        self.assertGreaterEqual(result["probability_positive"], 0.0)
        self.assertLessEqual(result["probability_positive"], 100.0)
        self.assertEqual(result["confidence_label"], "High")

    def test_mutual_fund_composite_ranking_is_bounded_and_ranked(self):
        tree = ast.parse(SOURCE)
        wanted = {"_normalize_mf_base_name", "mf_scoring_weights", "rank_mf_results"}
        nodes = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in wanted
        ]
        namespace = {"pd": pd, "np": np, "re": re}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec"), namespace)
        months = pd.date_range("2021-01-31", periods=60, freq="ME")
        base = {
            "fund_house": "Example AMC",
            "latest_nav": 100.0,
            "ret_1y": 10.0,
            "rolling_5y_median": 10.0,
            "forecast_p10": -5.0,
            "forecast_p50": 10.0,
            "forecast_p90": 25.0,
            "probability_positive": 70.0,
            "history_years": 5.5,
            "confidence_score": 90.0,
            "confidence_label": "High",
            "latest_date": "2026-08-31",
            "nav_df": pd.DataFrame(),
        }
        strong = dict(base, scheme_name="Strong Fund Direct Plan Growth", cagr_3y=18.0, cagr_5y=16.0,
                      volatility=12.0, downside_deviation=7.0, sortino=2.4, max_drawdown=-12.0,
                      rolling_1y_positive_pct=90.0, rolling_3y_median=17.0, rolling_3y_std=2.0,
                      aum_crore=5000.0, monthly_returns=pd.Series(np.full(60, 0.012), index=months))
        weak = dict(base, scheme_name="Weak Fund Direct Plan Growth", cagr_3y=5.0, cagr_5y=6.0,
                    volatility=20.0, downside_deviation=15.0, sortino=0.3, max_drawdown=-35.0,
                    rolling_1y_positive_pct=55.0, rolling_3y_median=5.5, rolling_3y_std=8.0,
                    aum_crore=300.0, monthly_returns=pd.Series(np.tile([0.03, -0.025], 30), index=months))
        ter = {
            "strong fund": {"ter": 0.5, "date": "2026-08-31"},
            "weak fund": {"ter": 1.5, "date": "2026-08-31"},
        }
        ranked = namespace["rank_mf_results"]([strong, weak], ter)
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[0]["scheme_name"], strong["scheme_name"])
        self.assertTrue(all(0.0 <= float(item["score"]) <= 100.0 for item in ranked))

    def test_amfi_ter_workbook_parser_keeps_latest_direct_cost(self):
        tree = ast.parse(SOURCE)
        wanted = {"_normalize_mf_base_name", "_parse_amfi_ter_workbook"}
        nodes = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in wanted
        ]
        namespace = {"pd": pd, "re": re, "io": __import__("io"), "openpyxl": openpyxl}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec"), namespace)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Scheme Name", "TER Date", "Direct Plan - Total TER (%)"])
        sheet.append(["Example Flexi Cap Fund", datetime.datetime(2026, 8, 1), 0.70])
        sheet.append(["Example Flexi Cap Fund", datetime.datetime(2026, 8, 31), 0.65])
        buffer = __import__("io").BytesIO()
        workbook.save(buffer)
        parsed = namespace["_parse_amfi_ter_workbook"](buffer.getvalue())
        self.assertEqual(parsed["example flexi cap fund"]["ter"], 0.65)
        self.assertEqual(parsed["example flexi cap fund"]["date"], "2026-08-31")

    def test_mutual_fund_peer_groups_and_profiles_are_distinct(self):
        tree = ast.parse(SOURCE)
        wanted = {"is_direct_growth_plan", "is_direct_growth_scheme", "shortlist_mf_schemes", "mf_scoring_weights"}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        namespace = {"LOGGER": __import__("logging").getLogger("test")}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec"), namespace)
        schemes = [
            {"schemeName": "Example Mid Cap", "schemePlan": "Direct", "schemeOption": "Growth", "categorySub": "Mid Cap Fund"},
            {"schemeName": "Example Large & Mid Cap", "schemePlan": "Direct", "schemeOption": "Growth", "categorySub": "Large & Mid Cap Fund"},
        ]
        matched = namespace["shortlist_mf_schemes"](schemes, ["mid cap"], category_name="Mid Cap")
        self.assertEqual(len(matched), 1)
        equity = namespace["mf_scoring_weights"]("Large Cap")
        debt = namespace["mf_scoring_weights"]("Liquid")
        self.assertAlmostEqual(sum(equity.values()), 1.0)
        self.assertAlmostEqual(sum(debt.values()), 1.0)
        self.assertGreater(debt["downside"], equity["downside"])
        self.assertNotIn("MF_MAX_ANALYZED = 40", SOURCE)
        self.assertIn("At least 90% coverage is required", SOURCE)

    def test_three_primary_sections_and_full_scan_quality_gate(self):
        self.assertIn('_primary_options = ["Today\'s Picks", "Research", "Settings"]', SOURCE)
        self.assertIn('quote_coverage_pct < 90.0', SOURCE)
        self.assertIn('"data_quality_failed"', SOURCE)

    def test_single_user_mode_does_not_require_oidc(self):
        self.assertIn('CURRENT_USER_ID = runtime.session_identity(st.session_state)', SOURCE)
        self.assertNotIn("st.login()", SOURCE)
        self.assertNotIn("ALLOW_INSECURE_LOCAL_DEV", SOURCE)

    def test_ltp_v3_previous_close_is_normalized_for_stage_one(self):
        tree = ast.parse(SOURCE)
        function_node = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_normalize_quote_response"
        )
        namespace = {"time": time}
        exec(compile(ast.Module(body=[function_node], type_ignores=[]), str(APP_PATH), "exec"), namespace)
        normalized = namespace["_normalize_quote_response"]({
            "NSE_EQ:TEST": {
                "instrument_token": "NSE_EQ|TESTKEY",
                "last_price": 101.5,
                "cp": 100.0,
                "volume": 1234,
            }
        })
        quote = normalized["NSE_EQ|TESTKEY"]
        self.assertEqual(quote["ohlc"]["close"], 100.0)
        self.assertEqual(quote["last_price"], 101.5)

    def test_quote_requests_use_url_safe_batches(self):
        self.assertIn("UPSTOX_QUOTE_BATCH_SIZE = 200", SOURCE)

    def test_connection_status_probes_and_handles_closed_market(self):
        self.assertIn("_rest_market_quotes([NIFTY_INDEX_KEY], access_token)", SOURCE)
        self.assertIn("WEBSOCKET: MARKET CLOSED · REST snapshot active", SOURCE)
        self.assertIn("UPSTOX REST API: TOKEN REJECTED / EXPIRED", SOURCE)

    def test_probability_uses_full_history_and_reports_sample_shortfall(self):
        self.assertIn("compute_historical_setup_probability(df, horizon_days=custom_days)", SOURCE)
        self.assertIn("days=1200", SOURCE)
        self.assertIn('Insufficient evidence (n={samples}; need {int(min_samples)})', SOURCE)
        self.assertIn("Evidence: {best['Sample Tier']}", SOURCE)
        self.assertNotIn("compute_historical_setup_probability(df_clean, horizon_days=custom_days)", SOURCE)

    def test_probability_can_reach_twenty_non_overlapping_samples(self):
        tree = ast.parse(SOURCE)
        function_node = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "compute_historical_setup_probability"
        )
        namespace = {"ta": ta, "np": np, "pd": pd, "math": math,
                     "runtime": runtime, "LOGGER": logging.getLogger("test")}
        derive = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "derive_long_trade_levels")
        exec(compile(ast.Module(body=[derive, function_node], type_ignores=[]), str(APP_PATH), "exec"), namespace)
        index = pd.bdate_range("2022-01-03", periods=700)
        close = pd.Series(np.linspace(100.0, 350.0, len(index)), index=index)
        frame = pd.DataFrame({
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
        })
        result = namespace["compute_historical_setup_probability"](frame, horizon_days=15)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["samples"], 20)
        self.assertIsNotNone(result["win_probability"])

    def test_scan_lock_is_reentrant_for_same_session(self):
        tree = ast.parse(SOURCE)
        class_node = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ScanCoordinator"
        )
        namespace = {"threading": __import__("threading"), "time": time}
        exec(compile(ast.Module(body=[class_node], type_ignores=[]), str(APP_PATH), "exec"), namespace)
        coordinator = namespace["ScanCoordinator"]()
        self.assertTrue(coordinator.try_start("session-a", lease_seconds=60))
        self.assertTrue(coordinator.try_start("session-a", lease_seconds=60))
        self.assertFalse(coordinator.try_start("session-b", lease_seconds=60))
        coordinator.finish("session-a")
        self.assertTrue(coordinator.try_start("session-b", lease_seconds=60))

    def test_scan_lock_releases_in_executor_cleanup(self):
        self.assertIn('_jobs.start(CURRENT_USER_ID, _signature', SOURCE)
        self.assertIn('_jobs.snapshot(CURRENT_USER_ID, _signature)', SOURCE)
        self.assertIn('@st.fragment(run_every=2.0)', SOURCE)
        self.assertNotIn('_scan_coordinator.try_start(_scan_owner', SOURCE)

    def test_personal_tables_are_user_scoped(self):
        self.assertIn("user_id TEXT NOT NULL", SOURCE)
        self.assertIn("CREATE TABLE IF NOT EXISTS user_watchlist", SOURCE)
        self.assertIn("WHERE user_id=?", SOURCE)


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        index = pd.date_range("2025-01-01", periods=260, freq="D")
        close = pd.Series(np.linspace(100.0, 180.0, len(index)), index=index)
        self.close = close
        self.high = close + 2.0
        self.low = close - 2.0

    def test_indicator_shapes_and_ranges(self):
        self.assertEqual(len(ta.ema(self.close, 20)), len(self.close))
        self.assertEqual(len(ta.atr(self.high, self.low, self.close, 14)), len(self.close))
        rsi = ta.rsi(self.close, 14).dropna()
        self.assertTrue(((rsi >= 0.0) & (rsi <= 100.0)).all())
        self.assertEqual(ta.adx(self.high, self.low, self.close, 14).shape[1], 3)
        self.assertEqual(ta.macd(self.close).shape[1], 3)
        self.assertEqual(ta.bbands(self.close).shape[1], 5)

    def test_supertrend_exposes_direction_column(self):
        result = ta.supertrend(self.high, self.low, self.close)
        direction_columns = [column for column in result.columns if "SUPERTd" in column]
        self.assertEqual(len(direction_columns), 1)
        self.assertEqual(float(result[direction_columns[0]].dropna().iloc[-1]), 1.0)


if __name__ == "__main__":
    unittest.main()
