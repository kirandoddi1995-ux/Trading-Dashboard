"""Read-only adapters; reuse provider selection, never its SQL feature writer."""
import csv
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from zoneinfo import ZoneInfo

from market_context import ContextError, record, bundle, MAX_BYTES, MAX_RECORDS, stamp, number

IST = ZoneInfo('Asia/Kolkata')
VIX = 'NSE_INDEX|India VIX'
OI_COLUMNS = (
    'Future Index Long', 'Future Index Short', 'Future Stock Long', 'Future Stock Short',
    'Option Index Call Long', 'Option Index Put Long', 'Option Index Call Short', 'Option Index Put Short',
    'Option Stock Call Long', 'Option Stock Put Long', 'Option Stock Call Short', 'Option Stock Put Short',
    'Total Long Contracts', 'Total Short Contracts',
)


def now():
    return datetime.now(timezone.utc)


def provider_time(value):
    # Provider quote timestamp contract: ISO with zone or epoch milliseconds;
    # no local timezone assumption and never substitute receipt for source time.
    if isinstance(value, bool):
        raise ContextError('INVALID_PROVIDER_TIME')
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        if number(value) <= 0:
            raise ContextError('INVALID_PROVIDER_TIME')
        return datetime.fromtimestamp(float(value)/1000, timezone.utc)
    return stamp(value)


def quote_time(quote, field, received):
    """Field-specific fixed codes only; never echo response bodies or substitute receipt."""
    if quote.get(field) in (None, ''):
        raise ContextError(field.upper()+'_MISSING')
    try:
        result = provider_time(quote[field])
    except Exception:
        raise ContextError(field.upper()+'_INVALID') from None
    if result > received:
        raise ContextError(field.upper()+'_IN_FUTURE')
    return result


def collect_quotes(client, token, *, vix_history=None):
    from prospective_collection import (
        _fetch_instrument_master, _nearest_future, GLOBAL_INSTRUMENTS, NSE_INSTRUMENTS,
        DOMESTIC_CUE_PROXIES, fetch_global_quotes,
    )
    if not token:
        raise ContextError('AUTH_REQUIRED')
    instruments = [dict(instrument_key=VIX, kind='VIX')]
    issues = []
    try:
        masters = _fetch_instrument_master(client, GLOBAL_INSTRUMENTS)
        matches = [r for r in masters if r.get('segment') == 'GLOBAL_INDEX'
                   and str(r.get('name', '')).strip().upper() == 'GIFT NIFTY']
        if len(matches) != 1:
            raise ContextError('GIFT_MASTER_AMBIGUOUS')
        instruments.append(dict(matches[0], kind='GIFT'))
    except Exception:
        issues.append('GIFT_MASTER_UNAVAILABLE_OR_AMBIGUOUS')
    try:
        selected = _nearest_future(_fetch_instrument_master(client, NSE_INSTRUMENTS),
                                   DOMESTIC_CUE_PROXIES[0], as_of=now().astimezone(IST).date())
        if selected is None:
            raise ContextError('USDINR_PROXY_UNAVAILABLE')
        instruments.append(dict(selected, kind='USDINR'))
    except Exception:
        issues.append('USDINR_FUTURES_PROXY_UNAVAILABLE')
    quotes = fetch_global_quotes(client, token, [r['instrument_key'] for r in instruments])
    rows = []
    for instrument in instruments:
        key, kind = instrument['instrument_key'], instrument['kind']
        q = quotes['quotes'].get(key)
        if not q:
            issues.append(kind+'_QUOTE_UNAVAILABLE')
            continue
        try:
            received = stamp(q['_received_at'])
            # LTP age uses the last-trade timestamp, not a newly generated packet
            # wrapping an old price. Missing trade time remains unavailable.
            effective = quote_time(q, 'last_trade_time', received)
            packet_at = quote_time(q, 'timestamp', received)
            try:
                price = number(q.get('last_price'))
                if price <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ContextError('LAST_PRICE_MISSING_OR_INVALID') from None
            payload = dict(value=str(price), instrument_key=key,
                           provider_packet_at=packet_at.isoformat(),
                           declared_latency=instrument.get('latency'),
                           common_factor_group='GLOBAL_RISK_CONTEXT' if kind == 'GIFT' else 'LOCAL_CONTEXT')
            if kind == 'GIFT':
                payload.update(contract_id=None, contract_identity='UNVERIFIED_GLOBAL_INDICATOR',
                               note='Not an overnight gap forecast; do not add correlated cues as votes.')
            if kind == 'USDINR':
                payload.update(proxy=True, expiry=instrument['selected_expiry'],
                               note='NSE currency future, not USD/INR spot or FBIL reference rate.')
            rows.append(record(dict(kind=kind, series=key, source_at=effective.isoformat(),
                source_url='https://upstox.com/developer/api-documentation/market-quote/',
                unit={'GIFT': 'POINTS', 'VIX': 'VIX_POINTS', 'USDINR': 'INR_PER_USD'}[kind], payload=payload),
                received_at=received, origin='UPSTOX_OBSERVED'))
        except ContextError as exc:
            issues.append(kind+'_'+str(exc))  # Only fixed codes raised by our validators.
        except Exception:
            issues.append(kind+'_QUOTE_METADATA_OR_SCHEMA_UNVERIFIED')
    if vix_history is not None:
        try:
            frame = vix_history()
            receipt = now()
            for index, item in frame.tail(500).iterrows():
                # App cache uses naive IST wall times; aware inputs must first
                # be converted (UTC 18:30 is the FOLLOWING session in India).
                day = (index.astimezone(IST) if index.tzinfo is not None else index).date()
                if day >= receipt.astimezone(IST).date():
                    continue  # Exclude the current incomplete daily candle.
                effective = datetime.combine(day, datetime.min.time(), IST)
                rows.append(record(dict(kind='VIX_CLOSE', series=VIX, source_at=effective.isoformat(),
                    source_url='https://upstox.com/developer/api-documentation/historical-candle-data/',
                    unit='VIX_POINTS', payload=dict(value=str(item['Close']), session_date=str(day),
                    note='Historical daily candle retrieved now; not proof it was known historically.')),
                    received_at=receipt, origin='RETROSPECTIVE_HISTORY_RETRIEVAL'))
        except Exception:
            issues.append('VIX_HISTORY_UNAVAILABLE_OR_PARTIAL')
    return bundle(rows, now(), issues)


def parse_participant_oi(data, report_date, received_at):
    if not data or len(data) > 256*1024:
        raise ContextError('OI_FILE_SIZE_INVALID')
    text = data.decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(text)))
    normalize = lambda s: re.sub(r'\s+', ' ', s.strip())
    header_at = next((i for i, r in enumerate(rows) if r and normalize(r[0]) == 'Client Type'), None)
    if header_at is None:
        raise ContextError('OI_HEADER_MISSING')
    title = ' '.join(' '.join(r) for r in rows[:header_at])
    # The date must appear in the document, not only the requested URL.
    compact = re.sub(r'[\s,]+', ' ', title)
    dates = (report_date.strftime('%b %d %Y'), report_date.strftime('%d-%b-%Y'),
             report_date.strftime('%d/%m/%Y'), report_date.strftime('%d-%m-%Y'))
    if not any(d in compact for d in dates):
        raise ContextError('OI_REPORT_DATE_MISMATCH')
    headers = [normalize(h) for h in rows[header_at] if normalize(h)]
    if headers != ['Client Type', *OI_COLUMNS]:
        raise ContextError('OI_SCHEMA_CHANGED')
    participants, totals = {}, None
    for row in rows[header_at+1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        cells = [cell.strip() for cell in row]
        while cells and not cells[-1]:
            cells.pop()
        if len(cells) != len(headers) or cells[0] not in {'Client', 'DII', 'FII', 'Pro', 'TOTAL'}:
            raise ContextError('OI_ROW_INVALID')
        try:
            counts = [int(cell.replace(',', '')) for cell in cells[1:]]
            if any(v < 0 for v in counts):
                raise ValueError
        except ValueError:
            raise ContextError('OI_COUNT_INVALID') from None
        values = dict(zip(OI_COLUMNS, counts))
        for side in ('Long', 'Short'):
            if sum(v for k, v in values.items() if k.endswith(side)) != values['Total '+side+' Contracts']:
                raise ContextError('OI_TOTAL_MISMATCH')
        if cells[0] == 'TOTAL':
            if totals is not None:
                raise ContextError('OI_DUPLICATE_ROW')
            totals = values
        else:
            if cells[0] in participants:
                raise ContextError('OI_DUPLICATE_ROW')
            participants[cells[0]] = values
    if set(participants) != {'Client', 'DII', 'FII', 'Pro'} or totals is None:
        raise ContextError('OI_PARTICIPANTS_INCOMPLETE')
    if any(sum(v[k] for v in participants.values()) != totals[k] for k in OI_COLUMNS):
        raise ContextError('OI_TOTAL_MISMATCH')
    url = oi_url(report_date)
    sha = hashlib.sha256(data).hexdigest()
    effective = datetime.combine(report_date, datetime.min.time(), IST)
    records = [record(dict(kind='PARTICIPANT_OI', series='NSE_EQUITY_DERIVATIVES:'+p,
        source_url=url, source_at=effective.isoformat(), source_sha256=sha, unit='CONTRACTS',
        payload=dict(participant=p, report_date=str(report_date), counts=values,
                     note='Contract counts, not delta exposure; Client is not a retail classification.')),
        received_at=received_at, origin='NSE_FILE_OBSERVED') for p, values in participants.items()]
    # Retain the tiny original file, including its checksum, in the archive.
    result = bundle(records, received_at)
    result['source_files'] = [dict(url=url, sha256=sha, bytes_base64=base64.b64encode(data).decode('ascii'))]
    return result


def oi_url(day):
    return 'https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_'+day.strftime('%d%m%Y')+'.csv'


def collect_participant_oi(client, day):
    with client.get(oi_url(day), timeout=(5, 25), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise ContextError('OFFICIAL_OI_UNAVAILABLE')
        data = bytearray()
        for chunk in response.iter_content(8192):
            data.extend(chunk)
            if len(data) > 256*1024:
                raise ContextError('OI_FILE_SIZE_INVALID')
    return parse_participant_oi(bytes(data), day, now())


def import_manual(data, received_at):
    """No arbitrary URL fetching; domain validation is NOT verification of content."""
    if len(data) > MAX_BYTES:
        raise ContextError('CONTEXT_PAYLOAD_LIMIT_OR_SCHEMA')
    parsed = json.loads(data)
    rows = parsed.get('records') if isinstance(parsed, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise ContextError('CONTEXT_RECORD_LIMIT')
    return bundle([record(r, received_at=received_at) for r in rows], received_at,
                  ['MANUAL_SOURCE_VALUES_NOT_INDEPENDENTLY_VERIFIED'])
