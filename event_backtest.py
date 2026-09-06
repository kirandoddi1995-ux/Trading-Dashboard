"""Deterministic event-driven bracket backtesting with live-like order timing.

The engine is deliberately small: it supports one long bracket position at a
time, next-event market entry, conservative stop-first same-bar handling and a
complete event/transaction record.  It does not claim exchange queue fidelity.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestEvent:
    sequence: int
    kind: str
    available_at: str
    payload: dict


@dataclass(frozen=True)
class BracketIntent:
    maximum_holding_bars: int
    quantity: float = 1.0


def _timestamp(value, name: str) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.tz_convert("UTC")


def _finite(value, name: str, *, positive=False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        raise ValueError(f"{name} must be {'positive and ' if positive else ''}finite")
    return parsed


def _validated_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close"}
    if not isinstance(frame, pd.DataFrame) or frame.empty or not required.issubset(frame.columns):
        raise ValueError("Backtest requires non-empty Open/High/Low/Close bars")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Backtest bar index must be timezone-aware")
    bars = frame.copy().sort_index()
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("Backtest bar timestamps must be unique and increasing")
    for column in required:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    values = bars[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Backtest OHLC values must be positive and finite")
    invalid = (
        (bars["High"] < bars[["Open", "Close"]].max(axis=1))
        | (bars["Low"] > bars[["Open", "Close"]].min(axis=1))
        | (bars["High"] < bars["Low"])
    )
    if invalid.any():
        raise ValueError("Backtest OHLC relationships are invalid")
    bars.index = bars.index.tz_convert("UTC")
    return bars


def run_long_bracket_backtest(
    bars: pd.DataFrame,
    *,
    signal: Callable[[pd.DataFrame], bool],
    levels: Callable[[pd.DataFrame, float, int], tuple[float, float] | None],
    maximum_holding_bars: int,
    round_trip_cost_bps: float,
    quantity: float = 1.0,
) -> dict:
    """Replay a long-only strategy using next-event entries and append-only events.

    `signal` sees history only through the current completed bar.  A submitted
    order may fill only on a later bar open.  `levels` is evaluated atomically
    at that fill event using the actual fill price and pre-signal history.
    """
    frame = _validated_bars(bars)
    holding_limit = int(maximum_holding_bars)
    if holding_limit < 1:
        raise ValueError("maximum_holding_bars must be positive")
    cost_bps = _finite(round_trip_cost_bps, "round_trip_cost_bps")
    qty = _finite(quantity, "quantity", positive=True)
    if cost_bps < 0:
        raise ValueError("round_trip_cost_bps must be non-negative")

    events: list[BacktestEvent] = []
    trades: list[dict] = []
    sequence = 0
    pending: dict | None = None
    position: dict | None = None

    def append(kind: str, at, payload: Mapping):
        nonlocal sequence
        sequence += 1
        events.append(BacktestEvent(
            sequence=sequence,
            kind=str(kind),
            available_at=_timestamp(at, "event time").isoformat(),
            payload=dict(payload),
        ))

    def close_position(at, price, outcome):
        nonlocal position
        exit_price = _finite(price, "exit price", positive=True)
        gross = exit_price / position["entry_price"] - 1.0
        cost_fraction = cost_bps / 10_000.0
        net = gross - cost_fraction
        trade = {
            "entry_at": position["entry_at"].isoformat(),
            "exit_at": _timestamp(at, "exit_at").isoformat(),
            "entry_price": position["entry_price"],
            "exit_price": exit_price,
            "stop": position["stop"],
            "target": position["target"],
            "quantity": qty,
            "outcome": str(outcome),
            "gross_return": gross,
            "cost_bps": cost_bps,
            "net_return": net,
            "net_pnl": qty * position["entry_price"] * net,
        }
        trades.append(trade)
        append("POSITION_CLOSED", at, trade)
        position = None

    for bar_index, (bar_at, row) in enumerate(frame.iterrows()):
        bar_at = _timestamp(bar_at, "bar time")
        append("MARKET_BAR", bar_at, {
            name.lower(): float(row[name]) for name in ("Open", "High", "Low", "Close")
        })

        if pending is not None:
            if bar_at <= pending["submitted_at"]:
                raise AssertionError("An order cannot fill on or before its submission event")
            entry = float(row["Open"])
            resolved = levels(pending["history"].copy(), entry, holding_limit)
            if not resolved:
                append("ORDER_REJECTED", bar_at, {
                    "order_id": pending["order_id"], "reason": "INVALID_BRACKET_LEVELS",
                })
                pending = None
            else:
                stop, target = map(float, resolved)
                if not all(math.isfinite(value) for value in (stop, target)) or not (0 < stop < entry < target):
                    append("ORDER_REJECTED", bar_at, {
                        "order_id": pending["order_id"], "reason": "INVALID_BRACKET_LEVELS",
                    })
                    pending = None
                else:
                    position = {
                        "entry_at": bar_at,
                        "entry_index": bar_index,
                        "entry_price": entry,
                        "stop": stop,
                        "target": target,
                    }
                    append("ORDER_FILLED", bar_at, {
                        "order_id": pending["order_id"],
                        "submitted_at": pending["submitted_at"].isoformat(),
                        "side": "BUY", "quantity": qty, "price": entry,
                        "stop": stop, "target": target,
                    })
                    pending = None

        if position is not None:
            # Daily/intrabar OHLC does not reveal within-bar ordering. Stop-first
            # is the conservative deterministic rule when both levels touch.
            if float(row["Low"]) <= position["stop"]:
                close_position(bar_at, position["stop"], "STOP")
            elif float(row["High"]) >= position["target"]:
                close_position(bar_at, position["target"], "TARGET")
            elif bar_index - position["entry_index"] + 1 >= holding_limit:
                close_position(bar_at, float(row["Close"]), "TIMEOUT")

        if position is None and pending is None:
            history = frame.iloc[:bar_index + 1].copy()
            wants_entry = bool(signal(history))
            append("SIGNAL_EVALUATED", bar_at, {
                "action": "ENTER_LONG" if wants_entry else "NO_TRADE",
                "history_rows": len(history),
            })
            if wants_entry:
                order_id = f"order-{sequence + 1}"
                pending = {
                    "order_id": order_id,
                    "submitted_at": bar_at,
                    "history": history,
                    "intent": BracketIntent(holding_limit, qty),
                }
                append("ORDER_SUBMITTED", bar_at, {
                    "order_id": order_id,
                    "side": "BUY", "type": "MARKET_NEXT_EVENT", "quantity": qty,
                    "maximum_holding_bars": holding_limit,
                })

    if pending is not None:
        append("ORDER_CANCELLED", frame.index[-1], {
            "order_id": pending["order_id"], "reason": "END_OF_REPLAY",
        })
    if position is not None:
        final_at = frame.index[-1]
        close_position(final_at, float(frame.iloc[-1]["Close"]), "END_OF_REPLAY")

    if any(
        pd.Timestamp(event.available_at) <= pd.Timestamp(event.payload["submitted_at"])
        for event in events if event.kind == "ORDER_FILLED"
    ):
        raise AssertionError("Detected a non-causal fill")
    return {
        "status": "PASS",
        "engine": "event-driven-bracket-v1",
        "same_bar_rule": "stop_first_conservative",
        "trades": trades,
        "events": [asdict(event) for event in events],
        "event_count": len(events),
        "trade_count": len(trades),
    }
