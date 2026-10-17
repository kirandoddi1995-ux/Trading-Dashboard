"""Generated 2022 toy quotes only, not licensed market data or real returns."""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
from typing import cast

import pytest

from quote_faithful_futures_replay import (
    Contract, DatedCosts, Quote, ReplayPlan, ReplayResult, replay,
)

PIN = 'a'*64


def fixture() -> tuple[ReplayPlan, Contract, DatedCosts, tuple[Quote, ...]]:
    plan = ReplayPlan(PIN, PIN, '2022-01-03T09:50:00+05:30',
        '2022-01-03T09:15:00+05:30', '2022-01-03T15:30:00+05:30',
        '2022-01-03T10:00:00+05:30', '2022-01-03T10:05:00+05:30',
        1, 1, 100, 500, 'SYNTHETIC')
    contract = Contract('TOY_JAN', PIN, '2022-01-01T09:00:00+05:30',
                        '2022-01-01', '2022-01-27', '2022-01-27', '0.05', 10, 'INR', '1')
    costs = DatedCosts(PIN, '2022-01-01T09:00:00+05:30', '2022-01-01',
                       '2022-01-31', '0.001', '0.002', '1', 1, 'INR')
    entry = Quote('entry', 1, 'TOY_JAN', '2022-01-03T10:00:00.100+05:30',
                  '2022-01-03T10:00:00.200+05:30', '99.95', '100.05', 10, 10, PIN)
    exit_quote = Quote('exit', 1, 'TOY_JAN', '2022-01-03T10:05:00.100+05:30',
                       '2022-01-03T10:05:00.200+05:30', '101.95', '102.05', 10, 10, PIN)
    return plan, contract, costs, (entry, exit_quote)


def run(*, plan: ReplayPlan | None = None, contract: Contract | None = None,
        costs: DatedCosts | None = None, quotes: tuple[Quote, ...] | None = None) -> ReplayResult:
    p, c, k, q = fixture()
    return replay(p if plan is None else plan, c if contract is None else contract,
                  k if costs is None else costs, q if quotes is None else quotes)


def test_long_quote_sides_spread_slippage_dated_costs_exact_accounting() -> None:
    result = run()
    assert result.status == 'PAPER_ROUND_TRIP_UNADMITTED' and result.paper_flat
    entry, exit_fill = result.fills
    assert (entry.side, entry.touch_price, entry.price) == ('BUY', '100.05', '100.10')
    assert (exit_fill.side, exit_fill.touch_price, exit_fill.price) == ('SELL', '101.95', '101.90')
    assert Decimal(result.gross_reference_amount or '') == Decimal('18')
    assert Decimal(result.total_fees or '') == Decimal('5.039')
    assert Decimal(result.net_reference_amount or '') == Decimal('12.961')
    assert all(flag is False for flag in (result.training_eligible, result.promotable,
        result.approval_authority, result.fill_evidence, result.executable_pnl_verified))
    assert json.loads(result.manifest)['plan']['input_kind'] == 'SYNTHETIC'


def test_short_uses_bid_then_ask_with_adverse_slippage() -> None:
    plan, _, _, _ = fixture()
    result = run(plan=replace(plan, direction=-1))
    assert [f.side for f in result.fills] == ['SELL', 'BUY']
    assert [Decimal(f.price) for f in result.fills] == [Decimal('99.90'), Decimal('102.10')]
    assert Decimal(result.gross_reference_amount or '') == Decimal('-22')


def test_explicit_lots_point_value_and_zero_costs_not_defaults() -> None:
    plan, contract, costs, _ = fixture()
    result = run(plan=replace(plan, lots=2), contract=replace(contract, point_value='2'),
        costs=replace(costs, buy_rate='0', sell_rate='0', fee_per_order='0', adverse_ticks_per_side=0),
        quotes=tuple(replace(q, bid_units=20, ask_units=20) for q in fixture()[3]))
    assert result.fills[0].units == 20
    assert Decimal(result.gross_reference_amount or '') == Decimal('76')
    assert Decimal(result.total_fees or '') == 0


def test_later_revision_never_replaces_already_selected_quote() -> None:
    _, _, _, quotes = fixture()
    revision = replace(quotes[0], version=2, available_at='2022-01-03T10:00:00.300+05:30',
                       ask='150.05', payload_sha256='b'*64)
    base = run()
    revised = run(quotes=quotes+(revision,))
    assert revised.fills == base.fills
    assert revised.manifest_sha256 != base.manifest_sha256
    assert run(quotes=(revision, quotes[1], quotes[0])) == revised


def test_before_latency_event_is_not_reused_when_available_later() -> None:
    _, _, _, quotes = fixture()
    old = replace(quotes[0], quote_id='old', quoted_at='2022-01-03T10:00:00.050+05:30',
                  available_at='2022-01-03T10:00:00.150+05:30')
    result = run(quotes=(old,)+quotes)
    assert result.fills[0].quote_id == 'entry'


@pytest.mark.parametrize('kind', ['empty', 'exit_missing', 'stale', 'exit_stale', 'entry_depth', 'exit_depth', 'missing_bid', 'missing_ask'])
def test_failures_commit_no_paper_legs_no_fabricated_flatten_or_amount(kind: str) -> None:
    _, _, _, quotes = fixture()
    if kind == 'empty':
        quotes = ()
    elif kind == 'exit_missing':
        quotes = quotes[:1]
    elif kind == 'stale':
        quotes = (replace(quotes[0], available_at='2022-01-03T10:00:01+05:30'), quotes[1])
    elif kind == 'exit_stale':
        quotes = (quotes[0], replace(quotes[1], available_at='2022-01-03T10:05:01+05:30'))
    elif kind == 'entry_depth':
        quotes = (replace(quotes[0], ask_units=9), quotes[1])
    elif kind == 'exit_depth':
        quotes = (quotes[0], replace(quotes[1], bid_units=9))
    elif kind == 'missing_bid':
        quotes = (replace(quotes[0], bid=None), quotes[1])
    else:
        quotes = (quotes[0], replace(quotes[1], ask=None))
    result = run(quotes=quotes)
    assert result.status == 'WITHHELD_NO_PAPER_LEGS_COMMITTED' and result.paper_flat
    assert not result.fills
    assert result.net_reference_amount is result.gross_reference_amount is result.total_fees is None


def test_shallow_first_quote_is_not_skipped_for_better_depth() -> None:
    _, _, _, quotes = fixture()
    bad = replace(quotes[0], quote_id='bad', ask_units=0,
                  available_at='2022-01-03T10:00:00.150+05:30')
    assert run(quotes=(bad,)+quotes).reason == 'INSUFFICIENT_DISPLAYED_DEPTH'


@pytest.mark.parametrize('kind', ['late_entry', 'exit_after_close', 'exit_before_entry', 'cross_close', 'frozen_future'])
def test_intraday_time_order_no_overnight_or_recovery_invention(kind: str) -> None:
    plan, _, _, quotes = fixture()
    if kind == 'late_entry':
        quotes = (replace(quotes[0], quoted_at='2022-01-03T10:05:00.100+05:30',
                          available_at='2022-01-03T10:05:00.150+05:30'), quotes[1])
        assert run(quotes=quotes).reason == 'ENTRY_NOT_FILLED_BEFORE_EXIT_DECISION'
    elif kind == 'exit_after_close':
        quotes = (quotes[0], replace(quotes[1], quoted_at='2022-01-03T15:30:01+05:30',
                                    available_at='2022-01-03T15:30:01.100+05:30'))
        assert not run(quotes=quotes).fills
    else:
        if kind == 'exit_before_entry':
            plan = replace(plan, exit_decision_at=plan.entry_decision_at)
        elif kind == 'cross_close':
            plan = replace(plan, session_close='2022-01-04T15:30:00+05:30')
        else:
            plan = replace(plan, frozen_at=plan.exit_decision_at)
        with pytest.raises(ValueError, match='INTRADAY_PLAN_TIME_ORDER_REQUIRED'):
            run(plan=plan)


@pytest.mark.parametrize('kind', ['off_tick', 'lot_bool', 'depth_bool', 'lots_zero', 'expiry', 'contract_date',
                                 'cost_date', 'cost_known', 'contract_known', 'currency'])
def test_contract_tick_lot_expiry_and_dated_cost_gates(kind: str) -> None:
    p, c, k, q = fixture()
    if kind == 'off_tick':
        q = (replace(q[0], ask='100.01'), q[1])
    elif kind == 'lot_bool':
        c = replace(c, lot_size=cast(int, True))
    elif kind == 'depth_bool':
        q = (replace(q[0], ask_units=cast(int, True)), q[1])
    elif kind == 'lots_zero':
        p = replace(p, lots=0)
    elif kind == 'expiry':
        c = replace(c, expiry='2022-01-03', effective_until='2022-01-03')
    elif kind == 'contract_date':
        c = replace(c, effective_from='2022-01-04')
    elif kind == 'cost_date':
        k = replace(k, effective_until='2022-01-02')
    elif kind == 'cost_known':
        k = replace(k, known_at=p.exit_decision_at)
    elif kind == 'contract_known':
        c = replace(c, known_at=p.exit_decision_at)
    else:
        k = replace(k, currency='USD')
    with pytest.raises(ValueError):
        replay(p, c, k, q)


@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-1', '0', '0.000000001', cast(str, True), cast(str, math.nan)])
def test_bad_nonfinite_boolean_prices_rejected(bad: str) -> None:
    _, _, _, q = fixture()
    with pytest.raises(ValueError):
        run(quotes=(replace(q[0], ask=bad), q[1]))


@pytest.mark.parametrize('kind', ['duplicate', 'tie', 'reverse_revision', 'changed_event', 'crossed', 'contract',
                                 'cross_day', 'before_event', 'naive'])
def test_ambiguous_or_invalid_quote_streams_rejected(kind: str) -> None:
    _, _, _, q = fixture()
    other = replace(q[0], quote_id='other')
    if kind == 'duplicate':
        other = q[0]
    elif kind == 'reverse_revision':
        other = replace(q[0], version=2, available_at='2022-01-03T10:00:00.150+05:30')
    elif kind == 'changed_event':
        other = replace(q[0], version=2, quoted_at='2022-01-03T10:00:00.110+05:30',
                        available_at='2022-01-03T10:00:00.300+05:30')
    elif kind == 'crossed':
        other = replace(other, bid='200', available_at='2022-01-03T10:00:00.300+05:30')
    elif kind == 'contract':
        other = replace(other, contract_id='OTHER')
    elif kind == 'cross_day':
        other = replace(other, available_at='2022-01-04T10:00:00+05:30')
    elif kind == 'before_event':
        other = replace(other, available_at='2022-01-03T09:00:00+05:30')
    elif kind == 'naive':
        other = replace(other, available_at='2022-01-03T10:00:00')
    with pytest.raises(ValueError):
        run(quotes=q+(other,))


def test_bounds_hashbinding_ambient_decimal_context_and_frozen_result() -> None:
    p, c, k, q = fixture()
    with pytest.raises(ValueError, match='QUOTE_BOUND'):
        run(quotes=q*2049)
    base = run()
    assert hashlib.sha256(base.manifest).hexdigest() == base.manifest_sha256
    assert run(plan=replace(p, decision_input_sha256='b'*64)).plan_sha256 != base.plan_sha256
    assert run(costs=replace(k, fee_per_order='2')).plan_sha256 != base.plan_sha256
    assert run(quotes=(replace(q[0], payload_sha256='b'*64), q[1])).manifest_sha256 != base.manifest_sha256
    with localcontext() as ctx:
        ctx.prec = 6
        ctx.Emax = 2
        assert replay(p, c, k, q) == base
    with pytest.raises(FrozenInstanceError):
        setattr(base, 'training_eligible', True)


def test_pure_stdlib_no_existing_module_or_activation_imports() -> None:
    tree = ast.parse((Path(__file__).resolve().parents[1]/'quote_faithful_futures_replay.py').read_text(encoding='utf-8'))
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imports.update(a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names)
    assert imports <= {'__future__', 'dataclasses', 'datetime', 'decimal', 'hashlib', 'json', 're'}
    assert not any(isinstance(n, ast.If) for n in tree.body)


def test_negative_adverse_sell_and_out_of_bound_costs_are_not_priced() -> None:
    _, _, costs, quotes = fixture()
    result = run(costs=replace(costs, adverse_ticks_per_side=100),
                 quotes=(quotes[0], replace(quotes[1], bid='0.05', ask='0.10')))
    assert result.reason == 'NONPOSITIVE_ADVERSE_PRICE' and not result.fills
    with pytest.raises(ValueError, match='FEE_RATE_BOUND'):
        run(costs=replace(costs, buy_rate='1.01'))


def test_explicit_hash_and_no_real_input_promotion() -> None:
    plan, _, _, _ = fixture()
    with pytest.raises(ValueError, match='INVALID_SHA256'):
        run(plan=replace(plan, decision_input_sha256='missing'))
    with pytest.raises(ValueError, match='UNAUTHENTICATED_INPUT_KIND_REQUIRED'):
        run(plan=replace(plan, input_kind='REAL'))
