"""Hosting-neutral, read-only broker monitor and persistent email dispatcher.

Run once from a scheduler. No order endpoint, OAuth automation, startup DDL or
network activity on import. The independent watchdog must live elsewhere.
"""
import argparse
from datetime import datetime, timezone
from email.message import EmailMessage
import json
import os
import re
import smtplib
import ssl

from derivative_contracts import FoundationError, digest, stamp, number
from derivative_settlement import obligation, whole_units, validate_policy


class AuthRequired(FoundationError):
    pass


class UpstoxReader:
    """Fixed GET endpoints only. Analytics account calls require whitelisted IP."""
    def __init__(self, session, token, account_id):
        self.session, self.token, self.account_id = session, token, account_id

    def get(self, path):
        if not self.token:
            raise AuthRequired('Broker authentication required')
        response = self.session.get('https://api.upstox.com/v2/'+path,
            headers={'Authorization':'Bearer '+self.token,'Accept':'application/json'},
            timeout=(5,20), allow_redirects=False)
        if response.status_code in (401,403):
            raise AuthRequired('Broker authentication or IP authorization required')
        if response.status_code != 200:
            raise FoundationError('Broker data unavailable')
        body = response.json()
        if not isinstance(body,dict) or body.get('status') != 'success' or 'data' not in body:
            raise FoundationError('Invalid broker response')
        return body['data']

    def snapshot(self):
        profile = self.get('user/profile')
        if not isinstance(profile,dict) or str(profile.get('user_id','')) != self.account_id:
            raise AuthRequired('Broker account mismatch')
        positions = self.get('portfolio/short-term-positions')
        holdings = self.get('portfolio/long-term-holdings')
        funds = self.get('user/get-funds-and-margin')
        orders = self.get('order/retrieve-all')
        if not all(isinstance(x,list) for x in (positions,holdings,orders)) or not isinstance(funds,dict):
            raise FoundationError('Incomplete broker snapshot')
        normalized = []
        seen = set()
        for p in positions:
            if not isinstance(p,dict) or not isinstance(p.get('instrument_token'),str):
                raise FoundationError('Malformed broker position')
            key = p['instrument_token']
            if not key.startswith(('NSE_FO|','BSE_FO|')):
                continue
            if p.get('product') not in {'D','I','CO'} or number(p.get('multiplier')) != 1:
                raise FoundationError('Unsupported broker position units/product')
            identity = (key,p['product'])
            if identity in seen:
                raise FoundationError('Duplicate broker position')
            seen.add(identity)
            normalized.append(dict(instrument_key=key,product=p['product'],signed_units=whole_units(p['quantity'])))
        # Holdings are NOT assumed free/deliverable: pledges, unsettled shares and
        # pending sells need reconciliation. Margin is NOT cash funding capacity.
        return dict(positions=normalized, holdings=holdings, funds=funds, orders=orders)


def position_fingerprint(p):
    return digest({k:p[k] for k in ('account_key','instrument_key','product','signed_units','contract_version','rule_version')})


def valid_receipt(receipt, old, *, now, outcome):
    if not isinstance(receipt,dict):
        return False
    try:
        return (receipt.get('source_type') == 'BROKER_REPORT' and receipt.get('verified') is True
                and receipt.get('outcome') == outcome
                and receipt.get('position_fingerprint') == position_fingerprint(old)
                and bool(re.fullmatch('[a-f0-9]{64}',str(receipt.get('source_sha256',''))))
                and bool(receipt.get('broker_reference'))
                and stamp(old['last_broker_seen']) <= stamp(receipt['confirmed_at']) <= stamp(now))
    except (KeyError,TypeError,ValueError):
        return False


def assess_position(repo, row, previous, account_key, *, now):
    p = dict(row, account_key=account_key, last_broker_seen=stamp(now).isoformat())
    key = row['instrument_key']
    try:
        contract = repo.historical(key,now=now)
        p.update(contract_version=contract.version,rule_version=contract.rule_version)
        p['underlying_key'] = contract.underlying
        # Daily session rule refresh is not a change to the position's economics.
        if previous and previous.get('state') not in {'EXIT_CONFIRMED','SETTLED'} and (
                previous.get('contract_version') != contract.version):
            receipt = repo.reviewed('RECONCILIATION',key,now=now)
            if not (valid_receipt(receipt,previous,now=now,outcome='ADJUSTED')
                    and receipt.get('new_contract_version') == contract.version
                    and receipt.get('new_rule_version') == contract.rule_version
                    and receipt.get('new_signed_units') == row['signed_units']):
                return dict(previous,state='ADJUSTMENT_PENDING',critical=True,
                            observed_signed_units=row['signed_units'], observed_at=p['last_broker_seen'])
        final_price = None
        final = repo.reviewed('FINAL_PRICE',key,now=now)
        if final and (final.get('source_type') == 'EXCHANGE_FINAL_PRICE' and final.get('verified') is True
                      and final.get('contract_version') == contract.version and final.get('rule_version') == contract.rule_version
                      and stamp(final['expiry_at']) == contract.expiry and stamp(now) >= contract.expiry
                      and bool(re.fullmatch('[a-f0-9]{64}',str(final.get('source_sha256',''))))):
            final_price = final['price']
        p.update(obligation(contract,row['signed_units'],final_price=final_price))
        p.update(state='OPEN',critical=False,expiry_at=contract.expiry.isoformat())
        review = repo.reviewed('ADJUSTMENT_REVIEW',key,now=now)
        if not review or review.get('status') != 'VERIFIED' or review.get('contract_version') != contract.version or review.get('rule_version') != contract.rule_version or not stamp(review['checked_at']) <= stamp(now) < stamp(review['valid_until']):
            p.update(state='ADJUSTMENT_PENDING',critical=True)
        if stamp(now) >= contract.expiry:
            p.update(state='SETTLEMENT_UNRESOLVED',critical=True)
        elif contract.settlement == 'PHYSICAL':
            policy = repo.reviewed('BROKER_POLICY',key,now=now)
            _, exit_by = validate_policy(contract,policy,now=now)
            p['exit_by'] = exit_by.isoformat()
            p['broker_deadline'] = policy['broker_deadline']
            if stamp(now) >= exit_by:
                p.update(state='EXIT_OVERDUE',critical=True)
        # Deliberately no portfolio netting or inference that margin == free cash.
        p['funding_shortfall'] = None
        p['deliverable_securities_shortfall'] = None
        return p
    except (FoundationError,KeyError,TypeError,ValueError,ArithmeticError):
        return dict(previous or p,state='REFERENCE_UNAVAILABLE',critical=True,
                    observed_signed_units=row['signed_units'], observed_at=p['last_broker_seen'])


def resource_context(data, position):
    """Small broker-reported context only, never guessed cash/share availability."""
    funds = data.get('funds', {}).get('equity', {})
    margin = funds.get('available_margin') if isinstance(funds,dict) else None
    matches = [h for h in data.get('holdings', []) if isinstance(h,dict)
               and h.get('instrument_token') == position.get('underlying_key')]
    holding = matches[0] if len(matches) == 1 else {}
    def numeric(value):
        return str(number(value)) if value is not None else None
    return dict(
        broker_available_margin_not_cash=numeric(margin),
        reported_holding_quantity=numeric(holding.get('quantity')),
        reported_t1_quantity=numeric(holding.get('t1_quantity')),
        reported_collateral_quantity=numeric(holding.get('collateral_quantity')),
        reported_cnc_used_quantity=numeric(holding.get('cnc_used_quantity')),
        broker_orders_seen=sum(1 for o in data.get('orders',[]) if isinstance(o,dict)
                              and o.get('instrument_token') == position['instrument_key']),
        resource_status='UNRECONCILED_NOT_PROOF_OF_DELIVERABLE_CASH_OR_SHARES')


def run_once(repo, broker, *, account_id, now, ttl_seconds=300):
    if not account_id or not 30 <= ttl_seconds <= 900:
        raise FoundationError('Reviewed monitor account/cadence required')
    account_key = digest({'upstox_account':account_id})
    with repo.monitor_lock():
        prior = repo.monitor_state()
        if prior and prior['account_key'] != account_key:
            raise FoundationError('Monitor account cannot change without review')
        repo.set_monitor_state(account_key,'POLLING',now,ttl_seconds)
        try:
            data = broker.snapshot()
            previous = repo.positions()
            seen = set()
            critical = False
            for row in data['positions']:
                key = digest({'account_key':account_key,'instrument_key':row['instrument_key'],'product':row['product']})
                if row['signed_units'] == 0:
                    continue  # Zero is handled as an unconfirmed disappearance below.
                seen.add(key)
                result = assess_position(repo,row,previous.get(key),account_key,now=now)
                result.update(resource_context(data,result))
                critical |= result['critical']
                repo.save_position(key,result,now)
            for key, old in previous.items():
                if old['account_key'] != account_key:
                    raise FoundationError('Stored monitor account mismatch')
                if key in seen or old.get('state') in {'EXIT_CONFIRMED','SETTLED'}:
                    continue
                receipt = repo.reviewed('RECONCILIATION',old['instrument_key'],now=now)
                outcome = 'SETTLED' if valid_receipt(receipt,old,now=now,outcome='SETTLED') else (
                    'EXIT_CONFIRMED' if valid_receipt(receipt,old,now=now,outcome='EXIT_FILLED') else 'MISSING_UNRECONCILED')
                unresolved = outcome == 'MISSING_UNRECONCILED'
                critical |= unresolved
                repo.save_position(key,dict(old,state=outcome,critical=unresolved),now)
            status = 'ATTENTION' if critical else 'READY'
            repo.set_monitor_state(account_key,status,now,ttl_seconds,critical)
            for code in ('AUTH_REQUIRED','DATA_UNAVAILABLE'):
                repo.clear_alert(code)
            if critical:
                repo.alert('SETTLEMENT_OR_RECONCILIATION_REQUIRED',now)
            else:
                repo.clear_alert('SETTLEMENT_OR_RECONCILIATION_REQUIRED')
            return status
        except Exception as exc:
            status = 'AUTH_REQUIRED' if isinstance(exc,AuthRequired) else 'DATA_UNAVAILABLE'
            # Never replace retained positions with an empty failed API response.
            repo.set_monitor_state(account_key,status,now,ttl_seconds)
            repo.alert(status,now)
            return status


def send_email(code, config):
    allowed = {'AUTH_REQUIRED','DATA_UNAVAILABLE','SETTLEMENT_OR_RECONCILIATION_REQUIRED','MONITOR_HEARTBEAT_MISSING'}
    if code not in allowed:
        raise FoundationError('Unknown alert code')
    message = EmailMessage()
    message['Subject'] = 'Trading monitor: '+code
    message['From'], message['To'] = config['sender'],config['recipient']
    message.set_content('Action required: '+code+'. Check your broker and monitoring dashboard. '
                        'Do not assume positions are closed or settled. No orders were placed by this monitor.')
    # SSL-only SMTP; no debug output, no raw provider exception is logged.
    with smtplib.SMTP_SSL(config['host'],int(config.get('port',465)),timeout=20,
                          context=ssl.create_default_context()) as smtp:
        smtp.login(config['username'],config['password'])
        if smtp.send_message(message):
            raise FoundationError('Email delivery rejected')


def deliver_alerts(repo, sender, *, now, limit=10):
    delivered = failed = 0
    for _ in range(limit):
        claim = repo.claim_email(now)
        if not claim:
            break
        key,code,attempts,token = claim
        try:
            sender(code)
            success = True
            delivered += 1
        except Exception:
            success = False
            failed += 1
        repo.finish_email(key,token,now,success=success,attempts=attempts)
    return {'delivered':delivered,'failed':failed}


def watchdog(repo, sender, *, now):
    """Deploy independently. Direct email even when the monitor database is down."""
    try:
        state = repo.monitor_state()
        healthy = bool(state and stamp(state['checked_at']) <= stamp(now) < stamp(state['valid_until'])
                       and state['status'] != 'POLLING')
    except Exception:
        healthy = False
    if not healthy:
        sender('MONITOR_HEARTBEAT_MISSING')
    return healthy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watchdog',action='store_true')
    args = parser.parse_args()
    from derivative_repository import DerivativeRepository
    import psycopg
    import requests
    try:
        config = json.loads(os.environ['DERIVATIVE_ALERT_SMTP_JSON'])
        def connect():
            conn = psycopg.connect(os.environ['DERIVATIVE_MONITOR_DATABASE_URL'],connect_timeout=10)
            try:
                role, unsafe = conn.execute(
                    'SELECT rolname,rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication '
                    'FROM pg_roles WHERE rolname=current_user').fetchone()
                expected = 'quant_derivative_watchdog' if args.watchdog else 'quant_derivative_monitor'
                if role != expected or unsafe:
                    raise FoundationError('Restricted monitor role required')
                return conn
            except Exception:
                conn.close()
                raise
        repo = DerivativeRepository(connect)
        sender = lambda code: send_email(code,config)
        now = datetime.now(timezone.utc)
        if args.watchdog:
            healthy = watchdog(repo,sender,now=now)
            print(json.dumps({'status':'HEALTHY' if healthy else 'HEARTBEAT_MISSING'}))
            return 0 if healthy else 1
        with requests.Session() as session:
            account_id = os.environ['DERIVATIVE_MONITOR_ACCOUNT_ID']
            status = run_once(repo,UpstoxReader(session,os.environ.get('DERIVATIVE_MONITOR_TOKEN'),account_id),
                account_id=account_id,now=now,ttl_seconds=int(os.environ.get('DERIVATIVE_MONITOR_TTL_SECONDS','300')))
        delivery = deliver_alerts(repo,sender,now=datetime.now(timezone.utc))
        print(json.dumps({'status':status,'email':delivery}))
        return 0 if status == 'READY' and not delivery['failed'] else 1
    except Exception:
        print(json.dumps({'status':'FAILED','reason':'Monitor or notification unavailable; check independent watchdog'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
