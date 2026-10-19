"""Inactive candidate metadata profile; NOT private decode or verification admission."""
from __future__ import annotations

from typing import Any

from outcomes_footer_diagnostic import COLUMN_CHECKS

PROFILE = 'outcomes-large-candidate-v1'
LARGE_COLUMNS = frozenset({'payload', '_row_json'})
COLUMNS = frozenset({'snapshot_id', 'decision_id', 'payload', 'recorded_at', '_row_json'})
MIB = 1024**2
MAX_ROW_BYTES = MIB


def candidate_matches(source: str, observation: dict[str, Any]) -> bool:
    """Pure, untrusted observation classification; never authorizes a private read."""
    try:
        if (type(observation) is not dict or type(observation.get('columns')) is not dict
                or type(observation.get('file_checks')) is not dict):
            return False
        for name in ('declared_rows', 'row_groups', 'file_bytes', 'footer_bytes', 'declared_expanded_bytes'):
            if type(observation[name]) is not int:
                return False
        if (set(observation['file_checks']) != {'row_group_totals_match', 'row_group_rows_match', 'file_expansion_within_128mib'}
                or any(value is not True for value in observation['file_checks'].values())):
            return False
        if (source != 'equity_research.outcomes' or type(observation['declared_rows']) is not int
                or not 1 <= observation['declared_rows'] <= 100 or observation['row_groups'] != 1
                or not 12 <= observation['file_bytes'] <= 32*MIB
                or not 0 < observation['footer_bytes'] <= 256*1024
                or not 0 < observation['declared_expanded_bytes'] <= 128*MIB
                or observation['file_checks'] != dict(row_group_totals_match=True,
                    row_group_rows_match=True, file_expansion_within_128mib=True)
                or set(observation['columns']) != COLUMNS):
            return False
        size_exception = False
        total = 0
        for name, column in observation['columns'].items():
            if type(column) is not dict or type(column.get('predicate_failures')) is not dict:
                return False
            if any(type(column[field]) is not int for field in ('chunks', 'max_uncompressed_bytes',
                    'max_compressed_bytes', 'sum_uncompressed_bytes', 'sum_compressed_bytes')):
                return False
            maximum = 32*MIB if name in LARGE_COLUMNS else 16*MIB
            uncompressed, compressed = column['max_uncompressed_bytes'], column['max_compressed_bytes']
            if (type(uncompressed) is not int or type(compressed) is not int or column['chunks'] != 1
                    or not 0 < uncompressed <= maximum or not 0 < compressed <= observation['file_bytes']
                    or column['sum_uncompressed_bytes'] != uncompressed or column['sum_compressed_bytes'] != compressed
                    or set(column['predicate_failures']) != set(COLUMN_CHECKS)):
                return False
            for check, count in column['predicate_failures'].items():
                expected = int(check == 'uncompressed_within_16mib' and uncompressed > 16*MIB)
                if type(count) is not int or count != expected:
                    return False
            size_exception |= uncompressed > 16*MIB
            total += uncompressed
        return bool(total == observation['declared_expanded_bytes']
                and observation['original_guard_result'] == ('PARQUET_COLUMN_EXPANSION_BOUND' if size_exception else 'PASS')
                and observation['failed_predicates'] == (['uncompressed_within_16mib'] if size_exception else []))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def assess(source: str, observation: dict[str, Any]) -> dict[str, Any]:
    return dict(profile=PROFILE, candidate_metadata_match=candidate_matches(source, observation),
        commissioned=False, private_decode_authorised=False, full_catalog_byte_footer_coverage=False,
        logical_restore_verified=False, independent_custody_verified=False,
        deletion_authorised=False, training_eligible=False, approval_authority=False)
