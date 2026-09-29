"""Explicit adjustment lineage. Pricing dividends cannot rewrite contract terms."""
from urllib.parse import urlparse
import re

from derivative_contracts import FoundationError, digest, stamp


def validate_adjustment(event, old_master, new_master):
    if event.get('kind') != 'CONTRACT_ADJUSTMENT' or event.get('reviewed') is not True:
        raise FoundationError('Reviewed exchange adjustment required')
    url = urlparse(str(event.get('source', '')))
    venue = new_master.get('exchange')
    hosts = {'NSE': {'nseindia.com', 'www.nseindia.com', 'nsearchives.nseindia.com', 'archives.nseindia.com'},
             'BSE': {'bseindia.com', 'www.bseindia.com'}}
    if url.scheme != 'https' or url.hostname not in hosts.get(venue, set()):
        raise FoundationError('Official venue-specific adjustment notice required')
    if (event.get('old_version') != digest(old_master) or event.get('new_version') != digest(new_master)
            or old_master.get('exchange') != venue):
        raise FoundationError('Adjustment lineage mismatch')
    if not re.fullmatch('[a-f0-9]{64}', str(event.get('source_sha256',''))):
        raise FoundationError('Retained adjustment source hash required')
    stamp(event['known_at'])
    stamp(event['effective_at'])
    # Never infer a generic split/dividend ratio: exact exchange terms are retained.
    if event.get('terms') != {k: new_master.get(k) for k in
                             ('instrument_key', 'strike_price', 'lot_size', 'expiry', 'tick_size')}:
        raise FoundationError('Adjusted master differs from exchange terms')
    return digest(event)


def validate_review(contract, review, quotes, *, now):
    if not isinstance(review, dict) or review.get('status') != 'VERIFIED':
        raise FoundationError('Corporate-action reconciliation pending')
    now = stamp(now)
    if (review.get('contract_version') != contract.version or review.get('rule_version') != contract.rule_version
            or not stamp(review['checked_at']) <= now < stamp(review['valid_until'])):
        raise FoundationError('Corporate-action review stale or version mismatch')
    boundary = stamp(review['quotes_after'])
    if boundary > now:
        raise FoundationError('Adjustment is not yet effective')
    for quote in quotes.values():
        if stamp(quote['source_at']) < boundary or stamp(quote['received_at']) < boundary:
            raise FoundationError('Pre-adjustment quotes/Greeks must be refreshed')
    return review['event_version']
