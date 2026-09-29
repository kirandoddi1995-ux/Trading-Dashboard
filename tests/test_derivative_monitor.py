"""Synthetic offline broker/settlement tests. No credentials or hosted services."""
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from dataclasses import replace
import copy

import pytest

import test_derivative_foundations as foundation
from derivative_contracts import resolve_contract,resolve_historical_contract,FoundationError,digest
from derivative_settlement import obligation
from derivative_corporate_actions import validate_adjustment
from derivative_preflight import evaluate
from derivative_monitor import (run_once,AuthRequired,UpstoxReader,position_fingerprint,
                                deliver_alerts,watchdog,resource_context)

NOW = foundation.NOW


@pytest.fixture
def inputs():
    return foundation.inputs.__wrapped__()


@pytest.mark.parametrize('kind,units,receive,deliver',[('CE',10,10,0),('CE',-10,0,10),('PE',10,0,10),('PE',-10,10,0)])
def test_obligation_directions_decimal_adjusted_units(inputs,kind,units,receive,deliver):
    c = replace(resolve_contract(inputs['master'],inputs['rules'],now=NOW),kind=kind,strike=Decimal('123.45'))
    r = obligation(c,units)
    assert r['receive_units'] == receive and r['deliver_units'] == deliver
    assert r['funding_required'] == Decimal('1234.50') if receive else r['funding_required'] == 0
    assert isinstance(r['sale_consideration'],Decimal)
    assert r['settled'] is False and r['charges'] is None


def test_final_price_cash_physical_atm_and_futures(inputs):
    c = resolve_contract(inputs['master'],inputs['rules'],now=NOW)
    assert obligation(c,10,final_price=100)['receive_units'] == 0  # strict ITM
    assert obligation(c,10,final_price=101)['funding_required'] == Decimal(1000)
    cash = replace(c,settlement='CASH')
    assert obligation(cash,-10,final_price=101)['cash_exercise_amount'] == Decimal(-10)
    fut = replace(c,kind='FUT')
    assert obligation(fut,10)['funding_required'] is None
    assert obligation(fut,-10,final_price=99)['sale_consideration'] == Decimal(990)


def test_monitor_after_expiry_never_entry_fallback(inputs):
    later = NOW+timedelta(days=60)
    assert resolve_historical_contract(inputs['master'],inputs['rules'],now=later).key
    with pytest.raises(FoundationError):
        resolve_contract(inputs['master'],inputs['rules'],now=later)


@pytest.mark.parametrize('change',['missing','auth','stale','critical','cutoff','oldquote','version'])
def test_new_preflight_fail_closed(inputs,change):
    ctx = inputs['lifecycle']
    if change == 'missing': inputs['lifecycle'] = None
    if change == 'auth': ctx['status'] = 'AUTH_REQUIRED'
    if change == 'stale': ctx['valid_until'] = NOW
    if change == 'critical': ctx['unresolved_critical'] = True
    if change == 'cutoff': ctx['broker_policy']['entry_cutoff'] = NOW
    if change == 'oldquote': ctx['adjustment_review']['quotes_after'] = NOW
    if change == 'version': ctx['adjustment_review']['contract_version'] = '0'*64
    assert not evaluate(**inputs).eligible


def test_pricing_event_cannot_adjust_contract(inputs):
    old = inputs['master']
    new = dict(old,strike_price='50',lot_size=20)
    event = dict(kind='CONTRACT_ADJUSTMENT',reviewed=True,source='https://nsearchives.nseindia.com/circular.pdf',
                 source_sha256='a'*64,old_version=digest(old),new_version=digest(new),known_at=NOW,effective_at=NOW,
                 terms={k:new.get(k) for k in ('instrument_key','strike_price','lot_size','expiry','tick_size')})
    assert validate_adjustment(event,old,new)
    with pytest.raises(FoundationError): validate_adjustment(dict(event,kind='PRICING_EVENT'),old,new)
    with pytest.raises(FoundationError): validate_adjustment(event,old,dict(new,strike_price='51'))


class Repo:
    def __init__(self,inputs):
        self.inputs=inputs; self.rows={}; self.state=None; self.codes=set(); self.receipt=None
    @contextmanager
    def monitor_lock(self): yield
    def monitor_state(self): return self.state
    def set_monitor_state(self,account_key,status,now,ttl,critical=True):
        self.state=dict(account_key=account_key,status=status,checked_at=now,valid_until=now+timedelta(seconds=ttl),unresolved_critical=critical)
    def positions(self): return copy.deepcopy(self.rows)
    def save_position(self,k,p,now): self.rows[k]=p
    def historical(self,key,now): return resolve_historical_contract(self.inputs['master'],self.inputs['rules'],now=now)
    def reviewed(self,kind,key,now):
        return {'BROKER_POLICY':self.inputs['lifecycle']['broker_policy'],
                'ADJUSTMENT_REVIEW':self.inputs['lifecycle']['adjustment_review'],
                'RECONCILIATION':self.receipt}.get(kind)
    def alert(self,code,now): self.codes.add(code)
    def clear_alert(self,code): self.codes.discard(code)


class Broker:
    def __init__(self,rows): self.rows=rows
    def snapshot(self):
        if isinstance(self.rows,Exception): raise self.rows
        return {'positions':self.rows}


def test_auth_failure_missing_and_partial_exit_preserve_positions(inputs):
    repo=Repo(inputs)
    row=dict(instrument_key=inputs['master']['instrument_key'],product='D',signed_units=10)
    assert run_once(repo,Broker([row]),account_id='fixture',now=NOW) == 'READY'
    assert run_once(repo,Broker([dict(row,signed_units=5)]),account_id='fixture',now=NOW) == 'READY'
    assert next(iter(repo.rows.values()))['receive_units'] == 5
    prior=copy.deepcopy(repo.rows)
    assert run_once(repo,Broker(AuthRequired('sensitive')),account_id='fixture',now=NOW) == 'AUTH_REQUIRED'
    assert repo.rows == prior
    assert run_once(repo,Broker([]),account_id='fixture',now=NOW) == 'ATTENTION'
    old=next(iter(prior.values()))
    repo.receipt=dict(source_type='MANUAL_CONFIRMATION',verified=True,outcome='EXIT_FILLED',
        position_fingerprint=position_fingerprint(old),source_sha256='a'*64,broker_reference='fixture',confirmed_at=NOW)
    assert run_once(repo,Broker([]),account_id='fixture',now=NOW) == 'ATTENTION'
    repo.receipt['source_type']='BROKER_REPORT'
    assert run_once(repo,Broker([]),account_id='fixture',now=NOW) == 'READY'
    assert next(iter(repo.rows.values()))['state'] == 'EXIT_CONFIRMED'


def test_expired_reference_failure_never_discards_position(inputs):
    repo=Repo(inputs)
    row=dict(instrument_key=inputs['master']['instrument_key'],product='D',signed_units=10)
    run_once(repo,Broker([row]),account_id='fixture',now=NOW)
    assert run_once(repo,Broker([row]),account_id='fixture',now=NOW+timedelta(days=60)) == 'ATTENTION'
    assert next(iter(repo.rows.values()))['state'] == 'SETTLEMENT_UNRESOLVED'


def test_reader_missing_token_no_network_and_sanitized_unauthorized():
    class Session:
        def get(self,*a,**kw):
            assert kw['allow_redirects'] is False
            return type('Response',(),{'status_code':401})()
    with pytest.raises(AuthRequired): UpstoxReader(None,None,'fixture').snapshot()
    with pytest.raises(AuthRequired): UpstoxReader(Session(),'secret-fixture','fixture').snapshot()


def test_email_failure_retry_and_watchdog(inputs):
    class MailRepo:
        def __init__(self): self.claims=[('key','AUTH_REQUIRED',1,'lease')]; self.results=[]
        def claim_email(self,now): return self.claims.pop() if self.claims else None
        def finish_email(self,*args,**kw): self.results.append(kw)
    repo=MailRepo()
    def fail(code): raise RuntimeError('secret must not be printed')
    assert deliver_alerts(repo,fail,now=NOW) == {'delivered':0,'failed':1}
    assert repo.results[0]['success'] is False
    alerts=[]
    monitor=Repo(inputs)
    assert not watchdog(monitor,alerts.append,now=NOW)
    assert alerts == ['MONITOR_HEARTBEAT_MISSING']


def test_resources_never_imply_free_cash_or_deliverable_shares():
    p=dict(instrument_key='NSE_FO|1',underlying_key='NSE_EQ|1')
    data=dict(funds={'equity':{'available_margin':100000}},holdings=[
        dict(instrument_token='NSE_EQ|1',quantity=100,collateral_quantity=80,t1_quantity=20)],
        orders=[dict(instrument_token='NSE_FO|1',status='open')])
    r=resource_context(data,p)
    assert r['broker_available_margin_not_cash']=='100000'
    assert r['reported_holding_quantity']=='100' and r['broker_orders_seen']==1
    assert r['resource_status'].startswith('UNRECONCILED')
    assert 'funding_available' not in r and 'deliverable_shares' not in r


def test_daily_rules_refresh_does_not_relabel_unchanged_contract_as_adjusted(inputs):
    repo=Repo(inputs)
    row=dict(instrument_key=inputs['master']['instrument_key'],product='D',signed_units=10)
    assert run_once(repo,Broker([row]),account_id='fixture',now=NOW)=='READY'
    inputs['rules']['source'] += '?new-session-review'
    inputs['lifecycle']['adjustment_review']['rule_version']=digest(inputs['rules'])
    assert run_once(repo,Broker([row]),account_id='fixture',now=NOW)=='READY'


def test_reference_failure_retains_previous_obligation_and_new_observed_quantity(inputs):
    repo=Repo(inputs)
    row=dict(instrument_key=inputs['master']['instrument_key'],product='D',signed_units=10)
    run_once(repo,Broker([row]),account_id='fixture',now=NOW)
    inputs['rules']['corporate_action_status']='UNKNOWN'
    assert run_once(repo,Broker([dict(row,signed_units=20)]),account_id='fixture',now=NOW)=='ATTENTION'
    p=next(iter(repo.rows.values()))
    assert p['receive_units']==10 and p['observed_signed_units']==20
    assert p['state']=='REFERENCE_UNAVAILABLE'


def test_watchdog_database_failure_alerts_without_database():
    class Broken:
        def monitor_state(self): raise RuntimeError('offline')
    alerts=[]
    assert not watchdog(Broken(),alerts.append,now=NOW)
    assert alerts==['MONITOR_HEARTBEAT_MISSING']
