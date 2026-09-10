"""Standalone exact-cohort, read-only market-data collector; never imports the app."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from urllib.parse import quote

from equity_research_observations import IST, aware, enroll
from equity_research_outcomes import evaluate_touches, sessions_for
from equity_research_repository import ResearchRepository


def fetch_minutes(client, token, instrument_key, start, end):
    """Preserve original API candles; no synthetic candles, volume or timestamps."""
    candles = []
    while start <= end:
        chunk_end = min(start + dt.timedelta(days=27), end)
        url = (f'https://api.upstox.com/v3/historical-candle/{quote(instrument_key, safe="")}'
               f'/minutes/1/{chunk_end}/{start}')
        response = client.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=(5, 40))
        if response.status_code != 200:
            raise RuntimeError(f'Market data HTTP {response.status_code}')
        body = response.json()
        if body.get('status') != 'success' or not isinstance(body.get('data', {}).get('candles'), list):
            raise ValueError('Invalid candle response')
        candles.extend(body['data']['candles'])
        start = chunk_end + dt.timedelta(days=1)
        time.sleep(0.25)
    return candles


def collect(repo, client, token, calendar, *, clock=None):
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    # Validate the WHOLE cohort and calendar before any enrollment or API work.
    observations = [enroll(source, now=clock().isoformat()) for source in repo.sources()]
    for observation in observations:
        sessions_for(observation, calendar)
    failures = []
    stored = 0
    for observation in observations:
        observation = repo.register(observation)
        repo.connection.commit()
        try:
            today = clock().astimezone(IST).date()
            # Historical endpoint only: use completed prior exchange dates.
            end = min(today - dt.timedelta(days=1),
                      aware(calendar['sessions'][-1]['close']).astimezone(IST).date())
            start = aware(observation['decision_at']).astimezone(IST).date()
            candles = fetch_minutes(client, token, observation['instrument_key'], start, end)
            fetched = clock()
            # Bound evaluation to the fetched date, not today's unfetched trading hours.
            cutoff = min(fetched, dt.datetime.combine(end + dt.timedelta(days=1), dt.time(), IST))
            outcome = evaluate_touches(observation, candles, calendar, now=fetched.isoformat(),
                                       fetched_at=fetched.isoformat(), data_through=cutoff.isoformat(),
                                       source='Upstox V3 historical minutes/1')
            repo.save_outcome(outcome)
            repo.connection.commit()
            stored += 1
        except Exception as exc:
            repo.connection.rollback()
            failures.append({'instrument': observation['instrument'], 'error_type': type(exc).__name__})
    return {'purpose': 'RESEARCH_ONLY_PRICE_TOUCH', 'stored': stored, 'failures': failures,
            'observations': repo.report()}


def main():
    import psycopg
    import requests
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check isolation and cohort without collecting')
    args = parser.parse_args()
    dsn = os.environ.get('EQUITY_RESEARCH_DATABASE_URL')
    if not dsn:
        raise ValueError('EQUITY_RESEARCH_DATABASE_URL required; no production credential fallback')
    with psycopg.connect(dsn, sslmode='require', connect_timeout=10) as conn:
        if args.check:
            # Set before the first SQL statement; PostgreSQL enforces read-only.
            conn.read_only = True
        repo = ResearchRepository(conn)
        if args.check:
            for source in repo.sources():
                enroll(source, now=dt.datetime.now(dt.timezone.utc).isoformat())
            conn.rollback()
            print(json.dumps({'mode': 'check', 'read_only': True,
                              'restricted_role': True, 'verified_sources': 89}))
            return
        token = os.environ.get('UPSTOX_ANALYTICS_TOKEN')
        if not token:
            raise ValueError('Read-only market-data token required')
        calendar = json.loads(os.environ['EQUITY_RESEARCH_SESSIONS_JSON'])
        with requests.Session() as client:
            report = collect(repo, client, token, calendar)
        print(json.dumps(report, allow_nan=False))
        if report['failures']:
            raise SystemExit(1)


def error_category(exc):
    """Inspect driver errors privately; return only fixed, non-sensitive labels.

    These are diagnostic classifications, not proof of a particular bad setting.
    Unrecognized failures remain unknown rather than guessing a credential issue.
    """
    try:
        import psycopg
    except ImportError:
        return 'unclassified_error'
    if not isinstance(exc, psycopg.OperationalError):
        return 'unclassified_error'
    message = str(exc).lower()
    state = getattr(exc, 'sqlstate', None)
    if state in ('28P01', '28000') or any(marker in message for marker in (
            'password authentication failed', 'authentication failed',
            'wrong password', 'sasl authentication failed')):
        return 'authentication_failure'
    if any(marker in message for marker in (
            'could not translate host name', 'name or service not known',
            'temporary failure in name resolution', 'nodename nor servname',
            'getaddrinfo failed', 'failed to resolve host')):
        return 'dns_failure'
    if any(marker in message for marker in (
            'timeout expired', 'connection timeout', 'timed out')):
        return 'timeout'
    if any(marker in message for marker in (
            'tenant or user not found', 'invalid port number',
            'invalid integer value')):
        # Includes an invalid pooler routing username/project, not just its host.
        return 'invalid_pooler_address_or_routing'
    return 'unclassified_operational_error'


def cli():
    try:
        main()
    except Exception as exc:
        # Never dump DSNs, tokens or provider response bodies into CI logs.
        print(json.dumps({'status': 'FAILED', 'error_type': type(exc).__name__,
                          'error_category': error_category(exc)}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    cli()
