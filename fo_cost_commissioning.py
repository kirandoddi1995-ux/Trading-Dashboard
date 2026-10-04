"""Offline component-level tariff commissioning. No live approval authority."""
import argparse
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from intraday_fo_costs import CostEvidenceError, amount

COMPONENTS = ('brokerage', 'stt_sell', 'exchange', 'ipft', 'sebi', 'stamp_buy', 'gst')
GST_COMPONENTS = ['brokerage', 'exchange', 'ipft', 'sebi']


def _date(value):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError()
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise CostEvidenceError('INVALID_EFFECTIVE_DATE') from None


def _record(record, review_as_of):
    """Publication and effective dates differ from retrospective review time."""
    if not isinstance(record, dict):
        raise CostEvidenceError('INVALID_EVIDENCE_RECORD')
    if _date(record.get('effective_from')) > _date(record.get('effective_to')):
        raise CostEvidenceError('INVALID_EFFECTIVE_RANGE')
    status = record.get('status')
    if status not in ('VERIFIED', 'ASSUMED'):
        raise CostEvidenceError('EVIDENCE_UNVERIFIED')
    try:
        reviewed = datetime.fromisoformat(record['reviewed_at'])
        if reviewed.tzinfo is None or reviewed > review_as_of:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise CostEvidenceError('REVIEW_TIMESTAMP_UNVERIFIED') from None
    if status == 'VERIFIED':
        url = urlsplit(str(record.get('source_url', '')))
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or
                not re.fullmatch(r'[0-9a-f]{64}', str(record.get('evidence_sha256', '')))):
            raise CostEvidenceError('SOURCE_EVIDENCE_MISSING')
        _date(record.get('published_on'))
    elif not isinstance(record.get('assumption'), str) or not record['assumption'].strip():
        raise CostEvidenceError('ASSUMPTION_DESCRIPTION_MISSING')


def select(records, day, review_as_of):
    if not isinstance(review_as_of, datetime) or review_as_of.tzinfo is None:
        raise CostEvidenceError('AWARE_REVIEW_TIME_REQUIRED')
    if not isinstance(records, list):
        raise CostEvidenceError('EVIDENCE_LIST_REQUIRED')
    selected = []
    ranges = []
    for record in records:
        if not isinstance(record, dict):
            raise CostEvidenceError('INVALID_EVIDENCE_RECORD')
        start, end = _date(record.get('effective_from')), _date(record.get('effective_to'))
        if start > end:
            raise CostEvidenceError('INVALID_EFFECTIVE_RANGE')
        if any(start <= prior_end and prior_start <= end for prior_start, prior_end in ranges):
            raise CostEvidenceError('OVERLAPPING_EVIDENCE_PERIODS')
        ranges.append((start, end))
        if start <= day <= end:
            _record(record, review_as_of)
            if record['status'] == 'VERIFIED' and _date(record['published_on']) > day:
                raise CostEvidenceError('SOURCE_NOT_PUBLISHED_BY_TRADING_DATE')
            selected.append(record)
    if len(selected) != 1:
        raise CostEvidenceError('DATED_EVIDENCE_MISSING')
    return selected[0]


def commissioned_scenario(*, ledger, terms, contract_key, entry, exit, lots,
                          entered_at, exited_at, entry_side, review_as_of):
    """One executed order per side; no margin, fills, or live-policy permission.

    Historical review occurs NOW, not backdated to a historical decision. This
    deliberate research-only interface does not alter round_trip's live-time
    provenance guard. Assumptions permit sensitivity arithmetic but never a
    commissioned result. Explicit broker note verification remains mandatory.
    """
    if (not isinstance(ledger, dict) or ledger.get('exchange') != 'NSE'
            or ledger.get('segment') != 'FUTURE' or
            ledger.get('rounding') != 'PER_SIDE_PAISE_HALF_UP'):
        raise CostEvidenceError('COST_CONVENTIONS_UNVERIFIED')
    if type(lots) is not int or lots <= 0 or entry_side not in ('BUY', 'SELL'):
        raise CostEvidenceError('INVALID_ORDER')
    if any(not isinstance(t, datetime) or t.tzinfo is None for t in (entered_at, exited_at)):
        raise CostEvidenceError('AWARE_TRADE_TIMES_REQUIRED')
    day = entered_at.astimezone(ZoneInfo('Asia/Kolkata')).date()
    if exited_at <= entered_at or exited_at.astimezone(ZoneInfo('Asia/Kolkata')).date() != day:
        raise CostEvidenceError('SAME_DAY_ORDER_REQUIRED')
    if not isinstance(terms, list):
        raise CostEvidenceError('CONTRACT_TERMS_MISSING')
    if any(not isinstance(t, dict) for t in terms):
        raise CostEvidenceError('INVALID_CONTRACT_TERMS')
    term = select([t for t in terms if t.get('contract_key') == contract_key], day, review_as_of)
    if (term['status'] != 'VERIFIED' or type(term.get('lot_size')) is not int
            or term['lot_size'] <= 0 or day >= _date(term.get('expiry'))
            or term.get('exchange') != 'NSE' or term.get('segment') != 'FUTURE'
            or term.get('underlying_key') != 'NSE_INDEX|Nifty 50'):
        raise CostEvidenceError('CONTRACT_TERMS_OR_EXPIRY_UNVERIFIED')
    fees = ledger.get('components')
    if not isinstance(fees, dict):
        raise CostEvidenceError('COMPONENT_EVIDENCE_MISSING')
    records = {name: select(fees.get(name), day, review_as_of) for name in COMPONENTS}
    values = {name: amount(record.get('value')) for name, record in records.items()}
    taxable = records['gst'].get('taxable_components')
    if (not isinstance(taxable, list) or not taxable or any(not isinstance(v, str) for v in taxable)
            or len(set(taxable)) != len(taxable) or not set(taxable) <= set(GST_COMPONENTS)):
        raise CostEvidenceError('DATED_GST_BASIS_UNVERIFIED')
    brokerage = records['brokerage']
    if brokerage.get('basis') not in ('FLAT_PER_ORDER', 'MIN_CAP_TURNOVER'):
        raise CostEvidenceError('BROKERAGE_BASIS_UNVERIFIED')
    rate = amount(brokerage.get('turnover_rate')) if brokerage['basis'] == 'MIN_CAP_TURNOVER' else None
    for name in COMPONENTS[1:]:
        expected = 'FRACTION_OF_TAXABLE_FEES' if name == 'gst' else 'FRACTION_OF_TURNOVER'
        if records[name].get('basis') != expected:
            raise CostEvidenceError('CHARGE_BASIS_UNVERIFIED')
        if values[name] >= 1:
            raise CostEvidenceError('FRACTIONAL_RATE_UNITS_UNVERIFIED')
    if rate is not None and rate >= 1:
        raise CostEvidenceError('FRACTIONAL_RATE_UNITS_UNVERIFIED')
    quantity = lots * term['lot_size']
    prices = (amount(entry), amount(exit))
    if not all(prices):
        raise CostEvidenceError('POSITIVE_PRICES_REQUIRED')
    money = lambda value: value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    sides = []
    for side, price in zip(('BUY', 'SELL') if entry_side == 'BUY' else ('SELL', 'BUY'), prices):
        turnover = price * quantity
        charge = {'brokerage': money(values['brokerage'] if rate is None else min(values['brokerage'], turnover * rate)),
                  'stt': money(turnover * values['stt_sell']) if side == 'SELL' else Decimal('0'),
                  'stamp': money(turnover * values['stamp_buy']) if side == 'BUY' else Decimal('0')}
        charge.update({name: money(turnover * values[name]) for name in ('exchange', 'ipft', 'sebi')})
        charge['gst'] = money(sum(charge[name] for name in taxable) * values['gst'])
        sides.append(charge)
    charges = sum(sum(side.values()) for side in sides)
    gross = (prices[1] - prices[0]) * quantity * (1 if entry_side == 'BUY' else -1)
    assumptions = [name for name, record in records.items() if record['status'] == 'ASSUMED']
    return {'status': 'ASSUMPTION_ONLY' if assumptions else 'REVIEWED_RESEARCH_ONLY',
            'assumed_components': assumptions, 'cost_policy_commissioned': not assumptions,
            'quantity': quantity, 'lot_size': term['lot_size'], 'contract_key': contract_key,
            'entry_charges': sides[0], 'exit_charges': sides[1], 'charges': charges,
            'gross_scenario_pnl': gross, 'net_scenario_pnl': gross - charges,
            'fill_evidence': False, 'approval_authority': False,
            'provenance_sha256': hashlib.sha256(json.dumps(
                {'records': records, 'term': term, 'rounding': ledger['rounding'],
                 'gst_components': taxable}, sort_keys=True).encode()).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--terms', required=True, type=Path)
    parser.add_argument('--trade', required=True, type=Path, help='Private JSON research scenario, not an order')
    parser.add_argument('--review-as-of', required=True, type=datetime.fromisoformat)
    args = parser.parse_args(argv)
    try:
        ledger, terms, trade = [json.loads(p.read_text(encoding='utf-8-sig'))
                               for p in (args.ledger, args.terms, args.trade)]
        if not isinstance(trade, dict):
            raise CostEvidenceError('INVALID_RESEARCH_SCENARIO')
        result = commissioned_scenario(ledger=ledger, terms=terms, review_as_of=args.review_as_of,
            contract_key=trade['contract_key'], entry=trade['entry'], exit=trade['exit'], lots=trade['lots'],
            entered_at=datetime.fromisoformat(trade['entered_at']),
            exited_at=datetime.fromisoformat(trade['exited_at']), entry_side=trade['entry_side'])
        print(json.dumps(result, default=lambda value: str(value) if isinstance(value, Decimal) else value,
                         allow_nan=False))
        return 0
    except CostEvidenceError as error:
        print(json.dumps({'status': 'BLOCKED', 'code': str(error), 'approval_authority': False}))
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'status': 'BLOCKED', 'code': 'INVALID_LOCAL_INPUT', 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
