"""Official daily ban status. Utilization estimates never set official status."""
from dataclasses import dataclass
from datetime import date, datetime
import csv
import hashlib
import io
import re

from derivative_contracts import FoundationError, number, stamp


@dataclass(frozen=True)
class BanSnapshot:
    trading_date: date
    symbols: frozenset[str]
    source: str
    sha256: str
    raw: bytes
    received_at: datetime


def ban_url(trading_date):
    return "https://nsearchives.nseindia.com/content/fo/fo_secban_" + trading_date.strftime("%d%m%Y") + ".csv"


def parse_ban(raw, *, trading_date, source, received_at):
    if source != ban_url(trading_date) or not isinstance(raw, bytes) or not raw or len(raw) > 1_000_000:
        raise FoundationError("Invalid official dated ban source")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeError, csv.Error):
        raise FoundationError("Unreadable ban file") from None
    if not rows or [s.strip().upper() for s in rows[0]] not in (["SYMBOL"], ["SECURITY"]):
        raise FoundationError("Unrecognized ban-file schema; manual source review required")
    symbols = []
    for row in rows[1:]:
        if not row or not any(x.strip() for x in row):
            continue
        if len(row) != 1 or not re.fullmatch(r"[A-Z0-9&_.-]+", row[0].strip()):
            raise FoundationError("Malformed ban member")
        symbols.append(row[0].strip())
    if len(symbols) != len(set(symbols)):
        raise FoundationError("Duplicate ban members")
    return BanSnapshot(trading_date, frozenset(symbols), source,
                       hashlib.sha256(raw).hexdigest(), raw, stamp(received_at))


def restriction(contract, ban, *, trading_date, now, action, exposure=None):
    """Exits need a complete signed CC-delta portfolio, not a per-leg label.

    This conservative check is not a substitute for clearing-member compliance.
    Missing positions/deltas leaves monitoring available, but denies automatic clearance.
    """
    if action not in {"ENTRY", "ROLL", "EXIT"}:
        raise FoundationError("Unknown derivative action")
    if contract.underlying_type != "EQUITY":
        if action == "EXIT":
            _exit_check(exposure, trading_date, now)
        return "NOT_APPLICABLE"
    if contract.exchange != "NSE":
        raise FoundationError("Stock restriction adapter unavailable for venue")
    if ban is None or ban.trading_date != trading_date or ban.received_at > stamp(now):
        raise FoundationError("Official ban status UNKNOWN")
    banned = contract.symbol in ban.symbols
    if action in {"ENTRY", "ROLL"} and banned:
        raise FoundationError("Official F&O ban: entries and rolls blocked")
    if action == "EXIT":
        _exit_check(exposure, trading_date, now)
    return "VALID_BANNED" if banned else "VALID_CLEAR"


def _exit_check(exposure, trading_date, now):
    if not exposure or exposure.get("complete") is not True or exposure.get("source") != "CLEARING_CORPORATION":
        raise FoundationError("Complete positions and clearing-house deltas required for exit review")
    if exposure.get("trading_date") != trading_date.isoformat() or stamp(exposure.get("valid_until")) <= stamp(now):
        raise FoundationError("Stale position/clearing delta evidence")
    positions = exposure.get("positions_before")
    proposed = exposure.get("positions_after")
    deltas = exposure.get("cc_deltas")
    if not isinstance(positions, dict) or not positions or not isinstance(proposed, dict) or not isinstance(deltas, dict):
        raise FoundationError("Complete per-contract positions and CC deltas required")
    # Quantity is signed underlying units, not lots. The trusted position adapter
    # must include every leg of this underlying, even zero/netting legs.
    if set(positions) != set(proposed) or not set(positions) <= set(deltas):
        raise FoundationError("Exit position universe is incomplete")
    before, after = number(0), number(0)
    for key in positions:
        old, new, delta = number(positions[key]), number(proposed[key]), number(deltas[key])
        if old != old.to_integral_value() or new != new.to_integral_value() or not -1 <= delta <= 1:
            raise FoundationError("Invalid position quantities or CC delta")
        if abs(new) > abs(old) or old * new < 0:
            raise FoundationError("An exit cannot open, increase or reverse a contract leg")
        before += old * delta
        after += new * delta
    if before == 0 or abs(after) > abs(before) or before * after < 0:
        raise FoundationError("Exit increases or reverses portfolio exposure")
