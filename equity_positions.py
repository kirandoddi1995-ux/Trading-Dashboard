"""Compact manual position journal. Never execution/model evidence or order routing."""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import uuid


class PositionError(ValueError):
    pass


def owner_identity(subject, provider):
    if not isinstance(subject, str) or not subject.strip() or not isinstance(provider, str) or not provider.strip():
        raise PositionError('Stable authenticated subject and provider are required for persistent positions')
    return hashlib.sha256(json.dumps([provider, subject], separators=(',', ':')).encode()).hexdigest()


def money(value, name, *, positive=True):
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (positive and number == 0):
            raise InvalidOperation
        if number >= Decimal('100000000000000') or number != number.quantize(Decimal('.0001')):
            raise InvalidOperation
        return number
    except (InvalidOperation, TypeError, ValueError):
        raise PositionError(f'{name} must be finite, non-negative, and have at most four decimal places') from None


def validate_position(ticker, sector, entry, stop, target, quantity):
    ticker = str(ticker or '').strip().upper()
    sector = str(sector or '').strip()
    if not re.fullmatch(r'[A-Z0-9&.\-]{1,32}', ticker):
        raise PositionError('Enter a valid equity trading symbol')
    if not sector or len(sector) > 100:
        raise PositionError('A sector bucket is required')
    entry, stop, target = (money(v, n) for v, n in ((entry, 'Entry'), (stop, 'Stop'), (target, 'Target')))
    qty = money(quantity, 'Quantity')
    if qty != qty.to_integral_value() or qty > 2147483647:
        raise PositionError('Quantity must be a positive whole number')
    if not stop < entry < target:
        raise PositionError('For a long equity position, stop must be below entry and target above entry')
    return ticker, sector, entry, stop, target, int(qty)


def portfolio_heat(rows, capital, max_sector_pct):
    capital = money(capital, 'Capital', positive=False)
    limit = money(max_sector_pct, 'Sector limit', positive=False)
    if limit > 100:
        raise PositionError('Sector limit cannot exceed 100%')
    deployed, risk, sectors = Decimal(0), Decimal(0), {}
    for row in rows:
        if row.get('closed_at') is not None:
            continue
        _, sector, entry, stop, _, qty = validate_position(
            row['ticker'], row['sector'], row['entry_price'], row['stop_price'], row['target_price'], row['quantity'])
        cost = entry * qty
        deployed += cost
        risk += (entry - stop) * qty
        sectors[sector] = sectors.get(sector, Decimal(0)) + cost
    return dict(deployed=deployed, unallocated=capital-deployed, planned_risk=risk,
        heat_pct=risk/capital*100 if capital else None,
        sectors=[dict(sector=s, deployed=v, percent=v/capital*100 if capital else None,
                      overweight=(v/capital*100 > limit) if capital else None)
                 for s, v in sorted(sectors.items(), key=lambda pair: (-pair[1], pair[0]))])


COLUMNS = ('position_id', 'ticker', 'sector', 'entry_price', 'stop_price', 'target_price',
           'quantity', 'recorded_at', 'closed_at', 'exit_price')


class PositionRepository:
    def __init__(self, repository):
        self.repository = repository

    @contextmanager
    def _connection(self, owner):
        if not isinstance(owner, str) or not re.fullmatch('[0-9a-f]{64}', owner):
            raise PositionError('Persistent position owner is unavailable')
        if not self.repository.configured:
            raise PositionError('Persistent database is not configured; positions are unavailable')
        with self.repository.connect() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
                    role = cur.fetchone()
                    if not role or role[0] != 'quant_app_runtime' or role[1] or role[2]:
                        raise PositionError('Positions require the restricted quant_app_runtime database role')
                    cur.execute("SELECT set_config('app.position_owner',%s,true)", (owner,))
                    cur.execute("SET LOCAL statement_timeout='5s'")
                    cur.execute("SET LOCAL lock_timeout='3s'")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_open(self, owner):
        with self._connection(owner) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {','.join(COLUMNS)} FROM equity_operations.positions WHERE owner_id=%s AND closed_at IS NULL ORDER BY recorded_at,position_id", (owner,))
                return [dict(zip(COLUMNS, row)) for row in cur.fetchall()]

    def record(self, owner, request_id, *, ticker, sector, entry, stop, target, quantity, confirmed):
        if confirmed is not True:
            raise PositionError('Confirm that the entry and quantity describe a position you actually hold')
        request_id = str(uuid.UUID(str(request_id)))
        values = validate_position(ticker, sector, entry, stop, target, quantity)
        with self._connection(owner) as conn:
            with conn.cursor() as cur:
                # Serialize double clicks and competing browser tabs for this owner.
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('positions:'+owner,))
                cur.execute('SELECT ticker,sector,entry_price,stop_price,target_price,quantity FROM equity_operations.positions WHERE owner_id=%s AND position_id=%s', (owner, request_id))
                prior = cur.fetchone()
                if prior:
                    if tuple(prior) != values:
                        raise PositionError('This request was already stored with different values; refresh before retrying')
                    return request_id, False
                cur.execute('SELECT 1 FROM equity_operations.positions WHERE owner_id=%s AND ticker=%s AND closed_at IS NULL', (owner, values[0]))
                if cur.fetchone():
                    raise PositionError('An open position already exists for this ticker. Scale-ins are not supported by this journal')
                cur.execute('''INSERT INTO equity_operations.positions
                    (position_id,owner_id,ticker,sector,entry_price,stop_price,target_price,quantity)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''', (request_id, owner, *values))
                return request_id, True

    def close(self, owner, position_id, *, exit_price=None, confirmed=False):
        if confirmed is not True:
            raise PositionError('Confirm that the entire position has been exited')
        position_id = str(uuid.UUID(str(position_id)))
        price = None if exit_price is None else money(exit_price, 'Exit price')
        with self._connection(owner) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT closed_at,exit_price FROM equity_operations.positions WHERE owner_id=%s AND position_id=%s FOR UPDATE', (owner, position_id))
                prior = cur.fetchone()
                if not prior:
                    raise PositionError('Position not found for this account')
                if prior[0] is not None:
                    if prior[1] != price:
                        raise PositionError('Position is already closed with different exit details')
                    return False
                cur.execute('UPDATE equity_operations.positions SET closed_at=clock_timestamp(),exit_price=%s WHERE owner_id=%s AND position_id=%s AND closed_at IS NULL', (price, owner, position_id))
                return True
