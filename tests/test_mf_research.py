import ast
from contextlib import nullcontext
import datetime
import hashlib
import json
import logging
from pathlib import Path
import re
import unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd

import mf_research as mfr


APP = Path(__file__).resolve().parents[1] / "app.py"


def app_functions():
    wanted = {"compute_mf_returns", "rank_mf_results", "mf_scoring_weights", "_normalize_mf_base_name"}
    nodes = [n for n in ast.parse(APP.read_text(encoding="utf-8")).body
             if isinstance(n, ast.FunctionDef) and n.name in wanted]
    namespace = {"pd": pd, "np": np, "mfr": mfr, "datetime": datetime, "hashlib": hashlib,
                 "re": re, "LOGGER": logging.getLogger("mf-tests")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace["compute_mf_returns"], namespace["rank_mf_results"]


def mf_renderer(stub):
    wanted = {"render_mf_research_results", "mf_scoring_weights"}
    nodes = [n for n in ast.parse(APP.read_text(encoding="utf-8")).body
             if isinstance(n, ast.FunctionDef) and n.name in wanted]
    namespace = {
        "pd": pd, "np": np, "mfr": mfr, "st": stub,
        "runtime": SimpleNamespace(csv_bytes=lambda frame: frame.to_csv(index=False).encode()),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace["render_mf_research_results"]


class RenderStub:
    def __init__(self):
        self.session_state = {}
        self.frames = []
        self.messages = []
        self.column_config = SimpleNamespace(LinkColumn=lambda label: label)

    def columns(self, count):
        return [SimpleNamespace(metric=lambda *_args, **_kwargs: None) for _ in range(count)]

    def expander(self, *_args, **_kwargs):
        return nullcontext()

    def dataframe(self, frame, **_kwargs):
        self.frames.append(frame)

    def success(self, message):
        self.messages.append(message)

    def info(self, message):
        self.messages.append(message)

    def warning(self, message):
        self.messages.append(message)

    def caption(self, message):
        self.messages.append(message)

    def markdown(self, message):
        self.messages.append(message)

    def write(self, message):
        self.messages.append(message)

    def download_button(self, *_args, **_kwargs):
        return False


def history(name="Example Direct Growth", end="2026-01-31", phase=0):
    dates = pd.bdate_range("2014-01-01", end)
    returns = .00025 + .007 * np.sin(np.arange(len(dates)) / 23 + phase)
    navs = 100 * np.cumprod(1 + returns)
    return {"meta": {"scheme_name": name, "fund_house": "Example AMC"}, "data": [
        {"date": date.strftime("%d-%m-%Y"), "nav": float(nav)} for date, nav in zip(dates, navs)
    ]}


class DisclosureTests(unittest.TestCase):
    def xml(self, name="Example Fund"):
        rows = [("Fund Name", name), ("Riskometer (At the time of Launch)", "Low"),
                ("Riskometer (as on Date)", "Very High"), ("Benchmark (Tier 1)", "Nifty 100 TRI")]
        content = "".join("<Row><Cell><Data>1</Data></Cell><Cell><Data>" + label +
                          "</Data></Cell><Cell><Data>" + value + "</Data></Cell></Row>" for label, value in rows)
        return ('<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
                '<DocumentProperties><LastSaved>2026-04-10T05:18:21Z</LastSaved></DocumentProperties>'
                '<Worksheet><Table>' + content + '</Table></Worksheet></Workbook>').encode()

    def test_summary_matches_scheme_and_uses_current_not_launch_label(self):
        result = mfr.parse_scheme_summary(self.xml(), "Example Fund Direct Plan Growth")
        self.assertEqual(result["riskometer"], "Very High")
        self.assertEqual(result["benchmark_name"], "Nifty 100 TRI")
        self.assertEqual(result["document_date"], "2026-04-10")
        self.assertIsNone(result["risk_as_of"])
        self.assertFalse(result["risk_verified_current"])

    def test_summary_rejects_wrong_scheme_and_entities(self):
        with self.assertRaises(ValueError):
            mfr.parse_scheme_summary(self.xml("Other Fund"), "Example Fund")
        with self.assertRaises(ValueError):
            mfr.parse_scheme_summary(b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///secret">]><a/>', "Example Fund")

    def test_old_summary_is_not_presented_as_current_monthly_risk(self):
        record = mfr.parse_scheme_summary(self.xml(), "Example Fund")
        self.assertIn("Old summary", mfr.risk_disclosure_status(record, "2026-08-31"))
        record.update(risk_as_of="2026-01-01", imported=True)
        self.assertIn("Stale", mfr.risk_disclosure_status(record, "2026-08-31"))

    def test_field_named_amfi_xml_schema_and_risk_suffix(self):
        raw = b'<SchemeSummaryDocument><Fund_Name>HDFC Large Cap Fund</Fund_Name><Riskometer_At_the_time_of_Launch>Low</Riskometer_At_the_time_of_Launch><Riskometer_as_on_Date>Very High Risk</Riskometer_as_on_Date><Benchmark_Tier_1>NIFTY 100 (Total Returns Index)</Benchmark_Tier_1></SchemeSummaryDocument>'
        result = mfr.parse_scheme_summary(raw, "HDFC Large Cap Fund Direct Plan Growth")
        self.assertEqual(result["riskometer"], "Very High")
        self.assertEqual(result["benchmark_name"], "NIFTY 100 (Total Returns Index)")
        self.assertIsNone(result["document_date"])

    def test_directory_reads_json_without_executing_scripts(self):
        record = {"mf_id": "20", "mf_name": "Example Mutual Fund", "amc_riskometer_monthly": "https://example.com/risk"}
        stream = 'a:' + json.dumps(["$", "component", None, {"data": [record]}]) + '\n'
        html = '<script>self.__next_f.push(' + json.dumps([1, stream]) + ')</script>'
        result = mfr.parse_amfi_directory(html)
        self.assertEqual(result["example mutual fund"]["id"], "20")

    def test_comparison_uses_same_report_not_current_app_cagr(self):
        record = {"performance_as_of": "2026-08-28", "official_fund_3y": 12,
                  "official_benchmark_3y": 10, "cagr_3y": 99}
        self.assertEqual(mfr.benchmark_comparison(record, "2026-08-31")["excess_3y_pp"], 2)
        record["performance_as_of"] = "2025-08-28"
        self.assertIsNone(mfr.benchmark_comparison(record, "2026-08-31")["excess_3y_pp"])
        record["performance_as_of"] = "2027-08-28"
        self.assertIsNone(mfr.benchmark_comparison(record, "2026-08-31")["excess_3y_pp"])

    def test_import_is_unverified_validated_and_never_treats_zero_as_missing(self):
        csv = ("scheme_code,scheme_name,benchmark_name,performance_as_of,source_url,riskometer,risk_as_of,official_fund_1y,official_benchmark_1y\n"
               "123456,Example Fund,Nifty 100 TRI,2026-08-28,https://www.amfiindia.com/report,Very High,2026-07-31,0,-1\n")
        record = mfr.parse_disclosure_csv(csv.encode(), "2026-08-31")["123456"]
        self.assertTrue(record["imported"])
        self.assertFalse(record["risk_verified_current"])
        self.assertEqual(mfr.benchmark_comparison(record, "2026-08-31")["excess_1y_pp"], 1)
        for invalid in (csv.replace("Very High", "Guaranteed Safe"), csv.replace("2026-08-28", "2027-08-28"),
                        csv + csv.splitlines()[1] + "\n", csv.replace("https://www.amfiindia.com/report", "javascript:alert(1)")):
            with self.assertRaises(ValueError):
                mfr.parse_disclosure_csv(invalid.encode(), "2026-08-31")

    def test_performance_adapter_preserves_direct_returns_and_missing_risk_date(self):
        result = mfr.parse_performance_rows([{"schemeName": "Example Fund", "benchmark": "Nifty 100 TRI",
                    "return3YearDirect": 12, "return3YearRegular": 10, "return3YearBenchmark": 11,
                    "riskometerScheme": "High", "ir3YrDirect": "0.2"}], "2026-08-28")[0]
        self.assertEqual(result["official_fund_3y"], 12)
        self.assertEqual(result["official_ir_3y"], .2)
        self.assertIsNone(result["risk_as_of"])


class PredictiveValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compute, cls.rank = staticmethod(app_functions()[0]), staticmethod(app_functions()[1])

    def test_monthly_data_has_no_partial_month_or_filled_gaps(self):
        frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-30", "2026-03-31", "2026-04-15"]), "nav": [100, 103, 104]})
        nav = mfr.complete_monthly_nav(frame, "2026-04-15")
        self.assertNotIn(pd.Timestamp("2026-04-30"), nav.index)
        self.assertTrue(pd.isna(nav.loc["2026-02-28"]))
        self.assertTrue(pd.isna(nav.pct_change(fill_method=None).loc["2026-03-31"]))

    def test_compute_asof_has_no_future_records(self):
        result = self.compute(history(), as_of_date="2020-12-31")
        self.assertLessEqual(pd.Timestamp(result["latest_date"]), pd.Timestamp("2020-12-31"))
        self.assertLessEqual(result["monthly_returns"].index.max(), pd.Timestamp("2020-12-31"))
        self.assertLess(result["freshness_days"], 7)

    def test_ranked_samples_match_displayed_quantiles(self):
        stats = self.compute(history())
        stats["aum_crore"] = None
        result = self.rank([stats], {}, "Large Cap")[0]
        np.testing.assert_allclose(np.quantile(result["forecast_samples"], [.1, .5, .9]),
                                   [result["forecast_p10"], result["forecast_p50"], result["forecast_p90"]])

    def test_annual_holdouts_no_overlap_and_future_mutation_does_not_change_old_forecasts(self):
        histories = {"123456": history(), "123457": history("Peer Direct Growth", phase=1)}
        original = mfr.walk_forward_validate(histories, self.compute, self.rank, "Large Cap", as_of="2026-01-31")
        changed = json.loads(json.dumps(histories))
        for payload in changed.values():
            for point in payload["data"]:
                if pd.to_datetime(point["date"], format="%d-%m-%Y") >= pd.Timestamp("2024-01-01"):
                    point["nav"] *= 3
        after = mfr.walk_forward_validate(changed, self.compute, self.rank, "Large Cap", as_of="2026-01-31")
        old = [r for r in original["fold_rows"] if r["test_end"] <= "2023-12-31"]
        new = [r for r in after["fold_rows"] if r["test_end"] <= "2023-12-31"]
        self.assertGreater(len(old), 4)
        self.assertEqual(old, new)
        for code in histories:
            rows = [r for r in original["fold_rows"] if r["scheme_code"] == code]
            for previous, current in zip(rows, rows[1:]):
                self.assertLessEqual(previous["test_end"], current["training_end"])
            for row in rows:
                self.assertLessEqual(row["training_last_nav"], row["training_end"])
                self.assertLess(row["training_end"], row["test_end"])
            self.assertFalse(original["by_scheme"][code]["production_validated"])

    def test_cost_deduction_is_applied_once_to_forecasts_and_actuals(self):
        histories = {"123456": history()}
        free = mfr.walk_forward_validate(histories, self.compute, self.rank, "Large Cap", cost_pct=0, as_of="2026-01-31")
        paid = mfr.walk_forward_validate(histories, self.compute, self.rank, "Large Cap", cost_pct=1, as_of="2026-01-31")
        for left, right in zip(free["fold_rows"], paid["fold_rows"]):
            for key in ("actual_net_pct", "median_net_pct", "baseline_net_pct"):
                self.assertAlmostEqual(right[key], ((1 + left[key] / 100) * .99 - 1) * 100)

    def test_missing_test_end_is_not_filled_or_used_to_select_training_peers(self):
        histories = {"123456": history(), "123457": history("Peer Direct Growth", phase=1)}
        complete = mfr.walk_forward_validate(histories, self.compute, self.rank, "Large Cap", as_of="2026-01-31")
        histories["123457"]["data"] = [p for p in histories["123457"]["data"] if not p["date"].endswith("12-2025")]
        incomplete = mfr.walk_forward_validate(histories, self.compute, self.rank, "Large Cap", as_of="2026-01-31")
        first = next(r for r in complete["fold_rows"] if r["scheme_code"] == "123456" and r["test_end"] == "2025-12-31")
        second = next(r for r in incomplete["fold_rows"] if r["scheme_code"] == "123456" and r["test_end"] == "2025-12-31")
        self.assertEqual(first, second)
        self.assertFalse(any(r["scheme_code"] == "123457" and r["test_end"] == "2025-12-31" for r in incomplete["fold_rows"]))

    def test_insufficient_history_never_claims_validation(self):
        report = mfr.walk_forward_validate({"123456": history(end="2016-01-01")}, self.compute, self.rank,
                                          "Large Cap", as_of="2016-01-01")
        self.assertFalse(report["fold_rows"])
        self.assertEqual(report["by_scheme"]["123456"]["folds"], 0)

    def test_realistic_saved_mutual_fund_result_renders_without_governance_name(self):
        ui = RenderStub()
        saved = {
            "ranked": [{
                "rank": 1, "scheme_code": "123456", "scheme_name": "Example Direct Growth",
                "score": 72.0, "why_ranked": "Strong category-relative risk-adjusted evidence",
                "cagr_3y": 12.4, "cagr_5y": 11.1, "max_drawdown": -16.2,
                "sortino": 1.2, "ter": 0.45, "latest_date": "2026-09-04",
                "confidence_label": "Complete historical inputs",
            }],
            "category": "Large Cap",
            "disclosures": {"records": {}, "errors": []},
            "validation": {
                "model_version": "mf-scenario-v1", "cost_pct": 0.5,
                "by_scheme": {}, "fold_rows": [], "limitations": "Historical evidence only.",
            },
            "candidate_count": 1,
            "elapsed": 0.4,
        }

        mf_renderer(ui)(saved)

        self.assertEqual(ui.session_state["last_mf_top_picks"]["category"], "Large Cap")
        self.assertGreaterEqual(len(ui.frames), 3)
        self.assertTrue(any("Highest category score" in message for message in ui.messages))


if __name__ == "__main__":
    unittest.main()
