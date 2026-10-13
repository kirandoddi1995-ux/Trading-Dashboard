"""Executable inactive chain. CLI self-check uses generated 2022 fixtures only."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

from overnight_research_dataset import ResearchError, VersionBinding, dataset_manifest, fingerprint, instant, project_bundle
from overnight_research_evidence import EvidenceArtifact, paper_evidence_gate
from overnight_research_execution import InstrumentContract, Quote, round_trip_scenario, summarize_scenarios
from overnight_research_ml import LabelInterval, ModelSpec, TrialRegistry, chronological_folds, walk_forward_ridge
from overnight_research_trials import DurableTrialRegistry


@dataclass(frozen=True)
class ScenarioRequest:
    contract: InstrumentContract | None
    decision_at: str
    entered_at: str
    exited_at: str
    entry: Quote | None
    exit: Quote | None
    quantity: int
    side: str
    cost_policy: Mapping[str, Any] | None
    adverse_ticks: int
    max_quote_age_seconds: int


@contextmanager
def offline_boundary() -> Iterator[None]:
    """Deny socket use during the chain, including transitive optional adapters."""
    from unittest.mock import patch
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise ResearchError('OFFLINE_NETWORK_FORBIDDEN')
    with patch('socket.socket.connect', denied), patch('socket.socket.connect_ex', denied), \
            patch('socket.create_connection', denied), patch('socket.getaddrinfo', denied):
        yield


@offline_boundary()
def run_offline(*, bundles: Sequence[tuple[Mapping[str, Any], VersionBinding]],
                scenarios: Sequence[ScenarioRequest], intervals: Sequence[LabelInterval],
                spec: ModelSpec, artifacts: Sequence[EvidenceArtifact],
                started_at: str, completed_at: str, minimum_train_groups: int = 2,
                test_groups: int = 1, gap_seconds: int = 0,
                targets: Mapping[str, float] | None = None, synthetic_fixture: bool = False,
                trial_registry: DurableTrialRegistry | None = None,
                session_groups: bool = False) -> dict[str, Any]:
    """Projection -> manifest -> scenarios -> folds -> trial -> evidence gate.

    No data-file arguments, discovery, network, orders, installs, or activation.
    Synthetic-only fitting is executable. Real data awaits independent admission.
    """
    model_id = spec.identity()
    try:
        rows = tuple(row for bundle, binding in bundles for row in project_bundle(bundle, binding))
        manifest = dataset_manifest(rows, source_hashes=[fingerprint(bundle) for bundle, _ in bundles],
                                    feature_code_sha256=spec.feature_code_sha256)
        row_ids = {row.row_id for row in rows}
        if any(interval.row_id not in row_ids for interval in intervals):
            raise ResearchError('LABEL_ROW_BINDING_MISMATCH')
        lookup = {row.row_id: row for row in rows}
        for interval in intervals:
            row = lookup[interval.row_id]
            if (interval.version != row.version or interval.data_scope != row.data_scope
                    or instant(interval.decision_at) != instant(row.decision_at)
                    or instant(interval.available_at) != instant(row.available_at)):
                raise ResearchError('LABEL_ROW_CHRONOLOGY_MISMATCH')
        folds = chronological_folds(intervals, minimum_train_groups=minimum_train_groups,
                                    test_groups=test_groups, gap_seconds=gap_seconds,
                                    session_groups=session_groups)
        results = [round_trip_scenario(**{
            field: getattr(request, field) for field in request.__dataclass_fields__}) for request in scenarios]
    except Exception:
        if trial_registry is not None:
            # This is deliberately a rejected input-shape reference, NOT a dataset
            # manifest or source-authenticity claim. Failed preparation still counts.
            reference = fingerprint({'format': 'rejected-research-input-shape-v1',
                'bundles': len(bundles), 'scenarios': len(scenarios), 'intervals': len(intervals)})
            rejected_id = fingerprint({'model': model_id, 'rejected': reference, 'started_at': started_at})
            trial_registry.start(trial_id=rejected_id, spec=spec, dataset_sha256=reference, folds=[],
                started_at=started_at, reference_kind='REJECTED_INPUT_SHAPE')
            trial_registry.finish(trial_id=rejected_id, completed_at=completed_at,
                status='FAILED', metrics={}, failure_code='OFFLINE_PREPARATION_FAILED')
        raise
    trial_id = fingerprint({'model': spec.identity(), 'dataset': manifest['manifest_sha256'], 'started_at': started_at})
    if trial_registry is not None:
        trial_registry.start(trial_id=trial_id, spec=spec, dataset_sha256=manifest['manifest_sha256'],
                             folds=folds, started_at=started_at)
    try:
        ml_result: dict[str, Any] = {'status': 'INSUFFICIENT_DATA', 'metrics': {},
            'reasons': ['LABELS_AND_LICENSE_NOT_INDEPENDENTLY_VERIFIED'], 'training_eligible': False}
        if spec.algorithm == 'LINEAR_RIDGE_RESEARCH':
            feature_matrix: dict[str, tuple[float, ...]] = {}
            interval_ids = {interval.row_id for interval in intervals}
            for row in rows:
                values = dict(row.features)
                if row.row_id in interval_ids and all(name in values for name in spec.feature_names):
                    feature_matrix[row.row_id] = tuple(values[name] for name in spec.feature_names)
            ml_result = walk_forward_ridge(samples=intervals, features=feature_matrix,
                targets=targets or {}, spec=spec, evaluated_at=completed_at,
                minimum_train_groups=minimum_train_groups, test_groups=test_groups,
                gap_seconds=gap_seconds, synthetic_fixture=synthetic_fixture,
                session_groups=session_groups)
    except Exception:
        if trial_registry is not None:
            trial_registry.finish(trial_id=trial_id, completed_at=completed_at,
                                  status='FAILED', metrics={}, failure_code='OFFLINE_FIT_FAILED')
        raise
    trial_status = 'COMPLETED' if ml_result['status'] == 'COMPLETED_SYNTHETIC_EVALUATION' else 'INSUFFICIENT_DATA'
    metrics = {name + '_' + metric: value for name, values in ml_result['metrics'].items()
               for metric, value in values.items()} if trial_status == 'COMPLETED' else {}
    registry = TrialRegistry()
    registry.record(trial_id=trial_id, spec=spec, dataset_sha256=manifest['manifest_sha256'],
        folds=folds, started_at=started_at, completed_at=completed_at, status=trial_status, metrics=metrics,
        failure_code=None if trial_status == 'COMPLETED' else 'LABELS_DATA_OR_LICENSE_INSUFFICIENT')
    if trial_registry is not None:
        trial_registry.finish(trial_id=trial_id, completed_at=completed_at, status=trial_status, metrics=metrics,
                              failure_code=None if trial_status == 'COMPLETED' else 'LABELS_DATA_OR_LICENSE_INSUFFICIENT')
    gate = paper_evidence_gate(artifacts=artifacts, dataset_sha256=manifest['manifest_sha256'],
                              model_sha256=spec.identity(), evaluated_at=completed_at)
    return {'status': 'INACTIVE_RESEARCH_ONLY', 'dataset_manifest': manifest,
        'scenario_summary': summarize_scenarios(results), 'scenario_results': results,
        'folds': [asdict(fold) for fold in folds], 'ml_result': ml_result,
        'trials': trial_registry.events() if trial_registry is not None else registry.events(), 'paper_gate': gate,
        'training_eligible': False, 'approval_authority': False, 'fill_evidence': False}


@offline_boundary()
def synthetic_self_check(*, trial_registry: DurableTrialRegistry | None = None,
                         session_groups: bool = False) -> dict[str, Any]:
    """Six generated polls + synthetic regression labels exercise the full chain."""
    from datetime import datetime, timedelta
    from forward_nifty_producer import prepare_config
    from forward_versioned_producer import recipe, _decision
    from forward_revision_quarantine import snapshot
    config = prepare_config('2022-01-03', 24900, 'a'*64, '2022-01-03T08:45:00+05:30')
    frozen = recipe(config, '2022-01-03T09:00:00+05:30')
    opening = datetime.fromisoformat(config['session_open'])
    polls, sources = [], []
    for count in (1, 5, 9, 13, 17, 21):
        bars = [[(opening+timedelta(minutes=5*i)).isoformat(), 25000+2*i, 25003+2*i,
                 24998+2*i, 25001+2*i, 0, 0] for i in range(count)]
        received = (opening+timedelta(minutes=5*count, seconds=30)).isoformat()
        computed = (instant(received)+timedelta(seconds=1)).isoformat()
        source = snapshot(config, bars, received, [], fingerprint(frozen))
        sources.append(source)
        polls.append({'source': source, 'computed_at': computed,
                      'decision': _decision(config, frozen, sources, computed)})
    bundle = {'format': 'forward-versioned-research-bundle-v1', 'config': config, 'recipe': frozen,
        'polls': polls, 'recorded_decisions': 6, 'missing_decisions': 69, 'expected_decisions': 75,
        'approval_authority': False, 'fill_evidence': False, 'training_eligible': False}
    binding = VersionBinding(config['version'], fingerprint(frozen), frozen['sources']['forward_versioned_producer.py'],
                             'synthetic offline verifier fixture')
    spec = ModelSpec('fixture-ridge', ('last_range_fraction', 'close_return_1'), 'LINEAR_RIDGE_RESEARCH',
        '{"alpha":1,"minimum_train_rows":2}', 'c'*64, '2022-01-02T00:00:00+05:30', 0)
    rows = project_bundle(bundle, binding)
    intervals = [LabelInterval(row.row_id, row.version, row.decision_at,
        (instant(row.decision_at)-timedelta(minutes=10 if i else 5)).isoformat(), row.available_at,
        (instant(row.available_at)+timedelta(minutes=1)).isoformat(),
        (instant(row.available_at)+timedelta(minutes=1, seconds=1)).isoformat(), row.decision_at)
        for i, row in enumerate(rows)]
    # These values test regression plumbing. They are neither returns nor executable P&L labels.
    targets = {row.row_id: float(2*i+1) for i, row in enumerate(rows)}
    request = ScenarioRequest(None, rows[0].available_at, '2022-01-03T09:21:00+05:30',
        '2022-01-03T09:25:00+05:30', None, None, 1, 'BUY', None, 1, 5)
    return run_offline(bundles=[(bundle, binding)], scenarios=[request], intervals=intervals, spec=spec,
        artifacts=[], started_at='2022-01-03T16:00:00+05:30', completed_at='2022-01-03T16:01:00+05:30',
        targets=targets, synthetic_fixture=True, trial_registry=trial_registry,
        session_groups=session_groups)


def verify_environment() -> dict[str, Any]:
    """Check installed versions against the optional profile without installing."""
    import importlib.metadata
    from pathlib import Path
    import re
    import sys
    root = Path(__file__).resolve().parent
    expected: dict[str, str] = {}
    for name in ('requirements-overnight-research.txt', 'requirements-automation.txt'):
        for line in (root/name).read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'([A-Za-z0-9_-]+)==([A-Za-z0-9_.]+)', line.strip())
            if match:
                expected[match[1]] = match[2]
    mismatches = []
    for package, version in expected.items():
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != version:
            mismatches.append(package)
    if sys.version_info[:2] != (3, 13):
        mismatches.append('python_3_13')
    return {'status': 'PINNED_ENVIRONMENT_VERIFIED' if not mismatches else 'PINNED_ENVIRONMENT_BLOCKED',
            'mismatched_packages': sorted(mismatches), 'installed_or_downloaded': False}


def main() -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Inactive synthetic offline research chain')
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument('--self-check', action='store_true')
    commands.add_argument('--verify-environment', action='store_true')
    args = parser.parse_args()
    if args.verify_environment:
        environment = verify_environment()
        print(json.dumps(environment, sort_keys=True))
        return 0 if environment['status'] == 'PINNED_ENVIRONMENT_VERIFIED' else 2
    result = synthetic_self_check()
    print(json.dumps({'status': result['status'], 'row_count': result['dataset_manifest']['row_count'],
        'scenario_status': result['scenario_summary']['status'], 'trial_status': result['trials'][0]['status'],
        'ml_status': result['ml_result']['status'],
        'paper_status': result['paper_gate']['status'], 'approval_authority': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
