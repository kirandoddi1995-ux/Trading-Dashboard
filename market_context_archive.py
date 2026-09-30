"""Bounded, verified private context archives; no database or deletion path."""
import base64
import gzip
import hashlib
import io
import json

from market_context import ContextError, VERSION, MAX_BYTES, MAX_RECORDS, canonical, record


def validate(packet):
    if (not isinstance(packet, dict) or packet.get('format') != VERSION
            or packet.get('mode') != 'CONTEXT_ONLY' or packet.get('approval_eligible') is not False
            or not isinstance(packet.get('records'), list) or len(packet['records']) > MAX_RECORDS):
        raise ContextError('INVALID_CONTEXT_ARCHIVE')
    # Preserve original first-known timestamps. This is integrity validation,
    # not evidence that a manually supplied value or timestamp is authoritative.
    for row in packet['records']:
        rebuilt = record(row, received_at=row['available_at'], origin=row['origin'])
        if rebuilt != row:
            raise ContextError('CONTEXT_RECORD_INTEGRITY_FAILURE')
    for source in packet.get('source_files', []):
        raw = base64.b64decode(source['bytes_base64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != source['sha256']:
            raise ContextError('CONTEXT_SOURCE_CHECKSUM_FAILURE')
    return canonical(packet)


def unpack(data):
    if len(data) > MAX_BYTES:
        raise ContextError('CONTEXT_ARCHIVE_TOO_LARGE')
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ContextError('CONTEXT_ARCHIVE_TOO_LARGE')
    packet = json.loads(raw)
    validate(packet)
    return packet


def archive_context(drive, packet):
    raw = validate(packet)
    compressed = gzip.compress(raw, mtime=0)
    identity = hashlib.sha256(raw).hexdigest()
    digest = hashlib.sha256(compressed).hexdigest()
    drive.check_folder()
    file_id = drive.put('context-'+identity+'.json.gz', compressed, identity, 'data', 'application/gzip')
    downloaded = drive.download(file_id)
    if hashlib.sha256(downloaded).hexdigest() != digest or canonical(unpack(downloaded)) != raw:
        raise ContextError('CONTEXT_ARCHIVE_VERIFICATION_FAILED')
    manifest = dict(format=VERSION, mode='CONTEXT_ONLY', approval_eligible=False,
                    batch_id=identity, file_id=file_id, sha256=digest,
                    row_count=len(packet['records']), uncompressed_bytes=len(raw))
    encoded = canonical(manifest)
    manifest_id = drive.put('context-'+identity+'.manifest.json', encoded, identity, 'manifest', 'application/json')
    if drive.download(manifest_id) != encoded:
        raise ContextError('CONTEXT_MANIFEST_VERIFICATION_FAILED')
    return dict(status='VERIFIED_CONTEXT_ARCHIVE', records=len(packet['records']),
                compressed_bytes=len(compressed), batch_id=identity)
