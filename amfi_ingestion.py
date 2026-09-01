"""Strict parser and downloader for AMFI's official open-ended NAV report."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
import openpyxl


AMFI_OPEN_NAV_URL = "https://portal.amfiindia.com/spages/NAVOpen.txt"
MAX_NAV_BYTES = 20_000_000


def _repair_text(value: str) -> str:
    value = value.strip().lstrip("\ufeff")
    if "â" in value or "Â" in value:
        try:
            value = value.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return " ".join(value.split())


def _is_direct_growth(plan: str, option: str) -> bool:
    return "direct" in plan.lower() and "growth" in option.lower()


@dataclass(frozen=True)
class AmfiParseResult:
    records: tuple[dict, ...]
    source_hash: str
    latest_date: dt.date
    latest_rows: int
    stale_over_365_days: int
    direct_growth_rows: int

    def summary(self) -> dict:
        return {
            "records": len(self.records), "source_hash": self.source_hash,
            "latest_date": self.latest_date.isoformat(), "latest_rows": self.latest_rows,
            "stale_over_365_days": self.stale_over_365_days,
            "direct_growth_rows": self.direct_growth_rows,
        }


def parse_amfi_open_nav(payload: bytes | str) -> AmfiParseResult:
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if not raw or len(raw) > MAX_NAV_BYTES:
        raise ValueError("AMFI NAV payload is empty or exceeds the safety limit")
    text = raw.decode("utf-8-sig", errors="replace")
    header = None
    current_category = None
    current_amc = None
    records = []
    seen = set()
    for raw_line in text.splitlines():
        line = _repair_text(raw_line)
        if not line:
            continue
        if line.lower().startswith("open ended schemes(") and line.endswith(")"):
            current_category = _repair_text(line[line.find("(") + 1:-1])
            continue
        if ";" not in line:
            if line.lower().endswith("mutual fund"):
                current_amc = line
            continue
        fields = [part.strip() for part in line.split(";")]
        if fields and fields[0].lower() == "scheme code":
            header = {name.strip().lower(): index for index, name in enumerate(fields)}
            required = {"scheme code", "scheme name", "net asset value", "date"}
            if not required.issubset(header):
                raise ValueError("AMFI NAV header is missing required fields")
            continue
        if header is None or not fields or not fields[0].isdigit():
            continue
        if len(fields) < len(header):
            continue

        def field(name, default=""):
            index = header.get(name)
            return fields[index].strip() if index is not None and index < len(fields) else default

        try:
            nav = Decimal(field("net asset value"))
            nav_date = dt.datetime.strptime(field("date"), "%d-%b-%Y").date()
        except (InvalidOperation, ValueError):
            continue
        if not nav.is_finite() or nav <= 0:
            continue
        code = field("scheme code")
        key = (code, nav_date)
        if key in seen:
            raise ValueError(f"Duplicate AMFI scheme/date record: {code} {nav_date}")
        seen.add(key)
        plan, option = field("plan"), field("option")
        records.append({
            "scheme_code": code,
            "isin_growth": field("isin div payout/ isin growth") or None,
            "isin_reinvestment": field("isin div reinvestment") or None,
            "scheme_name": _repair_text(field("scheme name")),
            "amc": current_amc,
            "category": current_category,
            "plan": plan,
            "option": option,
            "nav": str(nav),
            "nav_date": nav_date,
            "is_direct_growth": _is_direct_growth(plan, option),
        })
    if len(records) < 1000:
        raise ValueError(f"AMFI open-ended report unexpectedly contained only {len(records)} valid records")
    latest_date = max(record["nav_date"] for record in records)
    return AmfiParseResult(
        records=tuple(records), source_hash=hashlib.sha256(raw).hexdigest(), latest_date=latest_date,
        latest_rows=sum(record["nav_date"] == latest_date for record in records),
        stale_over_365_days=sum((latest_date - record["nav_date"]).days > 365 for record in records),
        direct_growth_rows=sum(record["is_direct_growth"] for record in records),
    )


def load_amfi_open_nav(path: str | Path) -> AmfiParseResult:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return parse_amfi_open_nav(path.read_bytes())


def download_amfi_open_nav(*, session=None) -> AmfiParseResult:
    client = session or requests.Session()
    response = client.get(
        AMFI_OPEN_NAV_URL,
        headers={"Accept": "text/plain", "User-Agent": "QuantTerminal/19.0 research-archive"},
        timeout=(5, 25),
    )
    response.raise_for_status()
    content_length = int(response.headers.get("Content-Length") or 0)
    if content_length > MAX_NAV_BYTES or len(response.content) > MAX_NAV_BYTES:
        raise ValueError("AMFI NAV response exceeded the safety limit")
    return parse_amfi_open_nav(response.content)


def current_ranking_records(result: AmfiParseResult, *, freshness_days=7) -> list[dict]:
    cutoff = result.latest_date - dt.timedelta(days=max(0, int(freshness_days)))
    return [
        record for record in result.records
        if record["is_direct_growth"] and record["nav_date"] >= cutoff
    ]


def canonical_scheme_name(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"\b(direct|regular)\s*(plan)?\b", " ", value)
    value = re.sub(r"\b(growth|idcw|dividend|bonus)\s*(option)?\b", " ", value)
    value = re.sub(r"\b(reinvestment|re-investment|payout)\b", " ", value)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def parse_amfi_ter_workbook(payload: bytes) -> list[dict]:
    if not payload or len(payload) > 20_000_000:
        raise ValueError("AMFI TER workbook is empty or exceeds the safety limit")
    workbook = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    try:
        rows = workbook.active.iter_rows(values_only=True)
        header = tuple(next(rows))
        aliases = {
            "name": ("Scheme Name",), "date": ("TER Date",),
            "direct": ("Direct Plan - Total TER (%)",),
            "regular": ("Regular Plan - Total TER (%)",),
        }
        indexes = {}
        for key, choices in aliases.items():
            indexes[key] = next((header.index(choice) for choice in choices if choice in header), None)
        if indexes["name"] is None or indexes["date"] is None or indexes["direct"] is None:
            raise ValueError("AMFI TER workbook schema changed")
        latest = {}
        for row in rows:
            if len(row) <= max(index for index in indexes.values() if index is not None):
                continue
            name = row[indexes["name"]]
            parsed_date = row[indexes["date"]]
            if not name or parsed_date is None:
                continue
            if not isinstance(parsed_date, (dt.date, dt.datetime)):
                try:
                    parsed_date = dt.datetime.strptime(str(parsed_date), "%d-%b-%Y").date()
                except ValueError:
                    continue
            if isinstance(parsed_date, dt.datetime):
                parsed_date = parsed_date.date()
            record = {
                "scheme_name": _repair_text(str(name)), "canonical_name": canonical_scheme_name(name),
                "effective_date": parsed_date,
                "ter": float(row[indexes["direct"]]) if row[indexes["direct"]] not in (None, "") else None,
                "regular_ter": (float(row[indexes["regular"]])
                                if indexes["regular"] is not None and row[indexes["regular"]] not in (None, "") else None),
            }
            existing = latest.get(record["canonical_name"])
            if existing is None or record["effective_date"] >= existing["effective_date"]:
                latest[record["canonical_name"]] = record
        return list(latest.values())
    finally:
        workbook.close()


def download_amfi_ter(*, session=None, as_of=None) -> list[dict]:
    client = session or requests.Session()
    today = as_of or dt.date.today()
    financial_year = f"{today.year}-{today.year + 1}" if today.month >= 4 else f"{today.year - 1}-{today.year}"
    months = client.get(
        "https://www.amfiindia.com/api/populate-ter-month",
        params={"year": financial_year}, timeout=(5, 20),
        headers={"User-Agent": "QuantTerminal/19.0 research-archive"},
    )
    months.raise_for_status()
    choices = months.json()
    if not isinstance(choices, list) or not choices:
        raise ValueError("AMFI returned no TER month")
    month = str(choices[0].get("MonthNumber") or "")
    if not re.fullmatch(r"\d{2}-\d{4}", month):
        raise ValueError("AMFI returned an invalid TER month")
    response = client.get(
        "https://www.amfiindia.com/api/populate-te-rdata-revised",
        params={"MF_ID": "All", "Month": month, "strCat": "-1", "strType": "-1", "excel": "true"},
        timeout=(5, 60), headers={"User-Agent": "QuantTerminal/19.0 research-archive"},
    )
    response.raise_for_status()
    return parse_amfi_ter_workbook(response.content)
