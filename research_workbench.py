"""Bounded generated research reports. No loaders, activation, orders or schedules.

UI entry points: catalog, run_generated, validate_report, compare_reports.
All numeric losses concern artificial regression units, never market returns.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import TypeAlias, cast

from overnight_research_dataset import ResearchError, fingerprint
from overnight_research_execution import InstrumentContract, Quote, round_trip_scenario
from overnight_research_ml import LabelInterval, ModelSpec, chronological_folds, walk_forward_ridge
from overnight_research_runner import offline_boundary
from research_lab_statistics import histogram_drift

Json: TypeAlias = None | bool | int | float | str | list['Json'] | dict[str, 'Json']
Report: TypeAlias = dict[str, Json]
IST = timezone(timedelta(hours=5, minutes=30))
MAX_REPORT_BYTES = 131_072
MAX_ROWS = 24
STUDIES = ('frozen_baseline', 'backtesting', 'ml_models', 'automation_reports')
SOURCE_FILES = ('research_workbench.py', 'overnight_research_dataset.py',
                'overnight_research_ml.py', 'overnight_research_runner.py',
                'overnight_research_execution.py', 'overnight_research_evidence.py',
                'overnight_research_trials.py', 'research_lab_statistics.py', 'intraday_fo_costs.py')
ASSUMPTIONS: Report = {
    'source': 'GENERATED_2022_ONLY', 'label': 'ARTIFICIAL_REGRESSION_UNITS_NOT_PNL',
    'validation': 'EXPANDING_WALK_FORWARD_CLOSED_INTERVAL_PURGE',
    'grouping': 'WHOLE_IST_SESSION', 'post_test_embargo': 'VACUOUS_NO_FUTURE_TRAINING',
    'gap_seconds': 60, 'costs': 'UNVERIFIED_NO_EXECUTION_PERFORMANCE',
    'feature_schema': ['signal', 'lag'], 'generator': 'workbench-fixture-v1',
    'evidence_use': 'SYNTHETIC_PLUMBING_ONLY',
}


@dataclass(frozen=True)
class WorkbenchSpec:
    """Frozen small-model work request; the public UI uses these defaults."""

    study: str = 'frozen_baseline'
    sessions: int = 12
    seed: int = 17
    alpha: float = 1.0
    minimum_train_sessions: int = 4
    gap_seconds: int = 60

    def validate(self) -> None:
        if (self.study not in STUDIES or type(self.sessions) is not int
                or not 6 <= self.sessions <= MAX_ROWS or type(self.seed) is not int
                or not 0 <= self.seed <= 65535 or type(self.alpha) not in (int, float)
                or not math.isfinite(self.alpha) or not 0.01 <= self.alpha <= 100
                or type(self.minimum_train_sessions) is not int
                or not 3 <= self.minimum_train_sessions <= self.sessions - 2
                or type(self.gap_seconds) is not int or not 0 <= self.gap_seconds <= 86400):
            raise ResearchError('WORK_REQUEST_BOUNDS_INVALID')


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii')
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ResearchError('REPORT_CANONICAL_INVALID') from None


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _json(value: object, *, depth: int = 0, budget: list[int] | None = None) -> Json:
    """Copy a bounded JSON tree, rejecting custom containers and nonfinite values."""
    if budget is None:
        budget = [12000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        raise ResearchError('REPORT_TREE_BOUNDS_INVALID')
    if value is None or type(value) in (bool, int, float, str):
        if isinstance(value, str) and len(value) > 512:
            raise ResearchError('REPORT_STRING_BOUNDS_INVALID')
        if type(value) in (int, float) and (abs(cast(float, value)) > 1e12
                                         or not math.isfinite(cast(float, value))):
            raise ResearchError('REPORT_NONFINITE_OR_EXCESSIVE_NUMBER')
        return cast(Json, value)
    if type(value) in (list, tuple):
        sequence = cast(list[object], value)
        if len(sequence) > 256:
            raise ResearchError('REPORT_ARRAY_BOUNDS_INVALID')
        return [_json(v, depth=depth + 1, budget=budget) for v in sequence]
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if len(mapping) > 40 or any(type(k) is not str or len(k) > 80 for k in mapping):
            raise ResearchError('REPORT_OBJECT_BOUNDS_INVALID')
        return {cast(str, k): _json(v, depth=depth + 1, budget=budget) for k, v in mapping.items()}
    raise ResearchError('REPORT_JSON_TYPES_REQUIRED')


def _object(value: object, keys: set[str] | None = None) -> Report:
    if type(value) is not dict:
        raise ResearchError('REPORT_OBJECT_REQUIRED')
    result = cast(Report, value)
    if keys is not None and set(result) != keys:
        raise ResearchError('REPORT_SCHEMA_KEYS_INVALID')
    return result


def _list(value: Json) -> list[Json]:
    if type(value) is not list:
        raise ResearchError('REPORT_ARRAY_REQUIRED')
    return value


def _text(value: Json) -> str:
    if type(value) is not str:
        raise ResearchError('REPORT_TEXT_REQUIRED')
    return value


def _digest(value: Json) -> str:
    text = _text(value)
    if len(text) != 64 or any(c not in '0123456789abcdef' for c in text):
        raise ResearchError('REPORT_SHA256_REQUIRED')
    return text


def _number(value: Json) -> float:
    if type(value) not in (float, int):
        raise ResearchError('REPORT_NUMBER_REQUIRED')
    return float(cast(float, value))


def _integer(value: Json) -> int:
    if type(value) is not int:
        raise ResearchError('REPORT_INTEGER_REQUIRED')
    return value


def catalog() -> Report:
    """Cheap static data for the UI; importing/calling this performs no fitting."""
    return {'schema': 'research-workbench-catalog-v1', 'studies': list(STUDIES),
            'default_spec': _json(asdict(WorkbenchSpec())), 'max_sessions': MAX_ROWS,
            'run_trigger': 'EXPLICIT_PAGE_BUTTON_ONLY', 'synthetic_only': True,
            'real_training_status': 'REAL_TRAINING_BLOCKED',
            'market_guard': '09:15:00 THROUGH 15:40:59 IST EVERY DAY',
            'report_max_bytes': MAX_REPORT_BYTES, 'orders_enabled': False,
            'scheduling_enabled': False}


def real_training_admission() -> Report:
    """No caller flags, historical loaders or credentials can grant admission."""
    return {'status': 'REAL_TRAINING_BLOCKED', 'evidence_status': 'INSUFFICIENT_REAL_DATA',
            'training_eligible': False, 'approval_authority': False,
            'blockers': ['INDEPENDENT_SOURCE_CUSTODY_AND_RESTORE', 'ML_USE_LICENSE',
                         'POINT_IN_TIME_FEATURES_AND_EXECUTABLE_LABELS',
                         'DATED_CONTRACT_COST_MARGIN_AND_FILL_MECHANICS',
                         'FROZEN_STUDY_COMPLETE_TRIAL_LEDGER_AND_FORWARD_REVIEW']}


def _readiness() -> Report:
    return {'status': 'INSUFFICIENT_REAL_DATA', 'actual_derivative_backtest_available': False,
        'verified_real_sessions': None, 'verified_real_executable_labels': None,
        'missing_matrix': {name: {'status': 'MISSING_OR_NOT_INDEPENDENTLY_VERIFIED',
                                 'real_evidence': None, 'synthetic_is_admission': False}
            for name in ('instrument_contract', 'dated_costs', 'fills', 'liquidity_depth',
                         'margin_stress', 'source_license', 'point_in_time_labels')},
        'regression_units': 'ARTIFICIAL_REGRESSION_UNITS_NOT_PNL',
        'quote_rehearsal_units': 'GENERATED_CONTRACT_CURRENCY_ARITHMETIC_NOT_MARKET_PERFORMANCE'}


def guard_compute(spec: WorkbenchSpec, now: datetime | None = None) -> None:
    """Reject oversized work before generation and block during the IST window."""
    spec.validate()
    moment = datetime.now(timezone.utc) if now is None else now
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ResearchError('AWARE_TIME_REQUIRED')
    local = moment.astimezone(IST)
    if 555 <= local.hour * 60 + local.minute <= 940:
        raise ResearchError('HEAVY_COMPUTE_MARKET_WINDOW_BLOCKED')


def _sources() -> Report:
    """Only explicit sibling code bytes, never data, config or directory discovery."""
    root = Path(__file__).resolve().parent
    sources: Report = {}
    for name in SOURCE_FILES:
        path = root / name
        if path.is_symlink() or path.stat().st_size > 262144:
            raise ResearchError('SOURCE_CODE_BOUNDARY_INVALID')
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sources


def _fixture(spec: WorkbenchSpec) -> tuple[list[LabelInterval], dict[str, tuple[float, ...]], dict[str, float]]:
    samples: list[LabelInterval] = []
    features: dict[str, tuple[float, ...]] = {}
    targets: dict[str, float] = {}
    # One artificial row per day. Lag uses only previous generated signal; the
    # future target is separate from the feature matrix and known after label end.
    previous = 0.0
    for index in range(spec.sessions):
        decision = datetime(2022, 1, 3, 10, tzinfo=IST) + timedelta(days=index)
        signal = float(((index * 7 + spec.seed) % 19) - 9) / 9
        row_id = fingerprint({'fixture': 'workbench-fixture-v1', 'seed': spec.seed, 'row': index})
        feature_start = (decision - timedelta(days=1) if index else
                         decision - timedelta(minutes=5))
        samples.append(LabelInterval(row_id, 'workbench-v1', decision.isoformat(),
            feature_start.isoformat(),
            (decision + timedelta(seconds=1)).isoformat(),
            (decision + timedelta(minutes=5)).isoformat(),
            (decision + timedelta(minutes=6)).isoformat(), decision.date().isoformat()))
        features[row_id] = (signal, previous)
        targets[row_id] = 0.5 * signal - 0.2 * previous + float((index % 3) - 1) * 0.03
        previous = signal
    return samples, features, targets


def _assumptions(spec: WorkbenchSpec) -> Report:
    assumptions = _object(_json(ASSUMPTIONS))
    assumptions['gap_seconds'] = spec.gap_seconds
    assumptions['minimum_train_sessions'] = spec.minimum_train_sessions
    return assumptions


def _execution() -> Report:
    """Actual existing quote/cost engine on a wholly artificial declared contract."""
    contract = InstrumentContract('GENERATED_NOT_MARKET_CONTRACT', 'FUTURE', 50, '.05',
        '2022-01-01T00:00:00+05:30', '2022-01-27T15:30:00+05:30',
        '2022-01-02T00:00:00+05:30', '2022-01-03T09:15:00+05:30',
        '2022-01-03T15:00:00+05:30', 'https://example.invalid/GENERATED_NOT_OFFICIAL', 'd'*64)
    entry = Quote(contract.contract_key, '2022-01-03T10:00:01+05:30',
        '2022-01-03T10:00:01+05:30', '100', '101', 100, 100, 'e'*64)
    exit_quote = Quote(contract.contract_key, '2022-01-03T10:04:59+05:30',
        '2022-01-03T10:04:59+05:30', '104', '105', 100, 100, 'f'*64)
    names = ('brokerage_cap', 'brokerage_rate', 'stt_sell', 'stamp_buy', 'exchange', 'ipft', 'sebi', 'gst')
    rates = dict(zip(names, ('1', '.0001', '.0001', '.0001', '.0001', '.0001', '.0001', '.1')))
    policy = {'exchange': 'NSE', 'reviewed': True, 'effective_from': '2022-01-01',
        'effective_to': '2022-01-31', 'reviewed_at': '2021-12-31T00:00:00+05:30',
        'rounding': 'PER_SIDE_PAISE_HALF_UP', 'gst_components': ['brokerage', 'exchange', 'ipft', 'sebi'],
        'sources': dict.fromkeys(names, 'https://example.invalid/GENERATED_NOT_OFFICIAL'),
        'rates': {'FUTURE': rates, 'OPTION': dict(rates)}}
    decision, entered, exited = ('2022-01-03T10:00:00+05:30',
        '2022-01-03T10:00:02+05:30', '2022-01-03T10:05:00+05:30')
    inputs = {'contract': asdict(contract), 'entry': asdict(entry), 'exit': asdict(exit_quote),
        'cost_policy': policy, 'decision_at': decision, 'entered_at': entered, 'exited_at': exited,
        'quantity': 50, 'side': 'BUY', 'adverse_ticks': 1, 'max_quote_age_seconds': 5}
    result = round_trip_scenario(contract=contract, decision_at=decision, entered_at=entered,
        exited_at=exited, entry=entry, exit=exit_quote, quantity=50, side='BUY', cost_policy=policy,
        adverse_ticks=1, max_quote_age_seconds=5)
    if result['status'] != 'RESEARCH_QUOTE_SCENARIO':
        raise ResearchError('GENERATED_EXECUTION_FIXTURE_FAILED')
    return {'status': 'SYNTHETIC_QUOTE_COST_ARITHMETIC_ONLY', 'synthetic': True,
            'inputs': _json(inputs), 'result': _json(result),
            'performance_evidence': False, 'real_tariffs_verified': False}


def run_generated(study: str, now: datetime | None = None) -> Report:
    """Page-button API. Optional aware clock supports deterministic offline tests."""
    return run_synthetic(WorkbenchSpec(study=study), now=now)


def run_synthetic(spec: WorkbenchSpec, *, now: datetime | None = None) -> Report:
    """Run at most 24 rows, two features, one ridge spec; never retune."""
    guard_compute(spec, now)
    with offline_boundary():
        sources = _sources()
        samples, features, targets = _fixture(spec)
        execution = _execution()
        input_hash = _hash({'samples': [asdict(s) for s in samples],
                            'features': features, 'targets': targets, 'execution': execution['inputs']})
        model = ModelSpec('workbench-generated-ridge', ('signal', 'lag'),
            'LINEAR_RIDGE_RESEARCH', _canonical({'alpha': spec.alpha, 'minimum_train_rows': 2}).decode(),
            _hash(sources), '2022-01-02T00:00:00+05:30', spec.seed)
        result = walk_forward_ridge(samples=samples, features=features, targets=targets,
            spec=model, evaluated_at='2022-02-01T16:00:00+05:30',
            minimum_train_groups=spec.minimum_train_sessions, test_groups=1,
            gap_seconds=spec.gap_seconds, synthetic_fixture=True, session_groups=True)
        folds = chronological_folds(samples, minimum_train_groups=spec.minimum_train_sessions,
            test_groups=1, gap_seconds=spec.gap_seconds, session_groups=True)
        last = folds[-1]
        # Fixed bins, never selected from test outcomes. Training reference only.
        def histogram(ids: tuple[str, ...]) -> list[float]:
            counts = [0.0, 0.0, 0.0]
            for key in ids:
                x = features[key][0]
                counts[0 if x < -1/3 else 2 if x > 1/3 else 1] += 1
            return counts
        drift = histogram_drift(histogram(last.train), histogram(last.test))
        payload: Report = {'spec': _json(asdict(spec)), 'assumptions': _assumptions(spec),
            'identities': {'spec_sha256': _hash(asdict(spec)), 'input_sha256': input_hash,
                           'code_sha256': _hash(sources), 'sources': sources,
                           'model_sha256': model.identity()},
            'validation': _json({'status': result['status'], 'reasons': result['reasons'],
                                'folds': result['folds'], 'predictions': result['predictions'],
                                'metrics': result['metrics']}),
            'model_registry': {'status': 'IN_MEMORY_SYNTHETIC_ONLY',
                'algorithm': 'LINEAR_RIDGE_RESEARCH', 'model_sha256': model.identity(),
                'feature_importance': {'status': 'NOT_ESTABLISHED', 'values': None},
                'deployment_allowed': False, 'trial_count': 1},
            'drift': _json(drift),
            'generated_execution': execution,
            'readiness': _readiness(),
            'backtest': {'status': 'INSUFFICIENT_REAL_DATA', 'returns': None,
                'sharpe': None, 'net_pnl': None, 'fill_evidence': False,
                'reason': 'ARTIFICIAL_REGRESSION_LABELS_ARE_NOT_EXECUTION_OUTCOMES'},
            'automation_report': {'status': 'SYNTHETIC_MANUAL_RUN_ONLY',
                'scheduled': False, 'attempts': 1, 'failures': 0,
                'checks': ['CAUSAL_FEATURES', 'PURGED_SESSION_FOLDS', 'TRAIN_ONLY_SCALER',
                           'REAL_TRAINING_BLOCKED', 'BOUNDED_WORK']},
            'admission': real_training_admission()}
    envelope: Report = {'schema': 'research-workbench-report-v1',
        'status': 'SYNTHETIC_PLUMBING_ONLY', 'synthetic': True,
        'training_eligible': False, 'approval_authority': False,
        'payload': payload, 'report_sha256': _hash(payload)}
    return validate_report(envelope)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchError('REPORT_DUPLICATE_FIELD')
        result[key] = value
    return result


def _same_shape(value: Json, template: Json) -> None:
    """Exact nested keys and primitive types; arrays use one item as schema."""
    if isinstance(template, dict):
        obj = _object(value, set(template))
        for key in template:
            _same_shape(obj[key], template[key])
    elif isinstance(template, list):
        items = _list(value)
        if not template and items:
            raise ResearchError('REPORT_SCHEMA_ARRAY_INVALID')
        for item in items:
            if template:
                _same_shape(item, template[0])
    elif type(template) in (float, int) and type(template) is not bool:
        if type(template) is int:
            _integer(value)
        else:
            _number(value)
    elif type(value) is not type(template):
        raise ResearchError('REPORT_SCHEMA_TYPE_INVALID')


def validate_report(value: bytes | Mapping[str, object]) -> Report:
    """Validate/copy a bounded envelope. Hashes detect edits, not authenticity.

    Imported evidence never gains trading or training authority. Historical code
    hashes are retained rather than rewritten to the current installed code.
    """
    if isinstance(value, bytes):
        if not value or len(value) > MAX_REPORT_BYTES:
            raise ResearchError('REPORT_BYTES_BOUNDS_INVALID')
        try:
            decoded: object = json.loads(value, object_pairs_hook=_pairs)
        except (ValueError, UnicodeError, RecursionError):
            raise ResearchError('REPORT_JSON_INVALID') from None
    elif isinstance(value, Mapping):
        if len(value) > 40:
            raise ResearchError('REPORT_OBJECT_BOUNDS_INVALID')
        decoded = dict(value)
    else:
        raise ResearchError('REPORT_BYTES_OR_MAPPING_REQUIRED')
    report = _object(_json(decoded), {'schema', 'status', 'synthetic', 'training_eligible',
                                    'approval_authority', 'payload', 'report_sha256'})
    if len(_canonical(report)) > MAX_REPORT_BYTES:
        raise ResearchError('REPORT_BYTES_BOUNDS_INVALID')
    if (report['schema'] != 'research-workbench-report-v1'
            or report['status'] != 'SYNTHETIC_PLUMBING_ONLY'
            or report['synthetic'] is not True or report['training_eligible'] is not False
            or report['approval_authority'] is not False):
        raise ResearchError('REPORT_AUTHORITY_OR_SCHEMA_INVALID')
    payload = _object(report['payload'], {'spec', 'assumptions', 'identities', 'validation',
        'model_registry', 'drift', 'backtest', 'automation_report', 'admission',
        'generated_execution', 'readiness'})
    if _digest(report['report_sha256']) != _hash(payload):
        raise ResearchError('REPORT_TAMPERED')
    raw = _object(payload['spec'], set(asdict(WorkbenchSpec())))
    _number(raw['alpha'])
    spec = WorkbenchSpec(_text(raw['study']), _integer(raw['sessions']), _integer(raw['seed']),
        cast(float, raw['alpha']), _integer(raw['minimum_train_sessions']), _integer(raw['gap_seconds']))
    spec.validate()
    _same_shape(payload['assumptions'], _assumptions(spec))
    _same_shape(payload['admission'], real_training_admission())
    _same_shape(payload['readiness'], _readiness())
    if payload['readiness'] != _readiness():
        raise ResearchError('REPORT_READINESS_INVALID')
    if payload['assumptions'] != _assumptions(spec) or payload['admission'] != real_training_admission():
        raise ResearchError('REPORT_ASSUMPTIONS_OR_ADMISSION_INVALID')
    identities = _object(payload['identities'], {'spec_sha256', 'input_sha256', 'code_sha256',
                                                'sources', 'model_sha256'})
    sources = _object(identities['sources'], set(SOURCE_FILES))
    for digest in sources.values():
        _digest(digest)
    for key in ('spec_sha256', 'input_sha256', 'code_sha256', 'model_sha256'):
        _digest(identities[key])
    if identities['code_sha256'] != _hash(sources) or identities['spec_sha256'] != _hash(raw):
        raise ResearchError('REPORT_IDENTITIES_INVALID')
    samples, features, targets = _fixture(spec)
    execution = _execution()
    _same_shape(payload['generated_execution'], execution)
    if payload['generated_execution'] != execution:
        raise ResearchError('REPORT_GENERATED_EXECUTION_INVALID')
    if identities['input_sha256'] != _hash({'samples': [asdict(s) for s in samples],
            'features': features, 'targets': targets, 'execution': execution['inputs']}):
        raise ResearchError('REPORT_SOURCE_BOUNDARY_INVALID')
    model = ModelSpec('workbench-generated-ridge', ('signal', 'lag'), 'LINEAR_RIDGE_RESEARCH',
        _canonical({'alpha': spec.alpha, 'minimum_train_rows': 2}).decode(),
        _text(identities['code_sha256']), '2022-01-02T00:00:00+05:30', spec.seed)
    if identities['model_sha256'] != model.identity():
        raise ResearchError('REPORT_MODEL_IDENTITY_INVALID')
    _validate_results(payload, spec, samples, features, targets, identities)
    return report


def _validate_results(payload: Report, spec: WorkbenchSpec, samples: list[LabelInterval],
                      features: dict[str, tuple[float, ...]], targets: dict[str, float],
                      identities: Report) -> None:
    registry: Report = {'status': 'IN_MEMORY_SYNTHETIC_ONLY', 'algorithm': 'LINEAR_RIDGE_RESEARCH',
        'model_sha256': identities['model_sha256'], 'feature_importance': {'status': 'NOT_ESTABLISHED',
        'values': None}, 'deployment_allowed': False, 'trial_count': 1}
    backtest: Report = {'status': 'INSUFFICIENT_REAL_DATA', 'returns': None, 'sharpe': None,
        'net_pnl': None, 'fill_evidence': False,
        'reason': 'ARTIFICIAL_REGRESSION_LABELS_ARE_NOT_EXECUTION_OUTCOMES'}
    automation: Report = {'status': 'SYNTHETIC_MANUAL_RUN_ONLY', 'scheduled': False,
        'attempts': 1, 'failures': 0, 'checks': ['CAUSAL_FEATURES', 'PURGED_SESSION_FOLDS',
            'TRAIN_ONLY_SCALER', 'REAL_TRAINING_BLOCKED', 'BOUNDED_WORK']}
    for name, template in (('model_registry', registry), ('backtest', backtest),
                           ('automation_report', automation)):
        _same_shape(payload[name], template)
    if (payload['model_registry'] != registry or payload['backtest'] != backtest
            or payload['automation_report'] != automation):
        raise ResearchError('REPORT_UNSUPPORTED_CLAIM')
    validation = _object(payload['validation'], {'status', 'reasons', 'folds', 'predictions', 'metrics'})
    if validation['status'] != 'COMPLETED_SYNTHETIC_EVALUATION' or validation['reasons'] != []:
        raise ResearchError('REPORT_VALIDATION_STATUS_INVALID')
    folds = chronological_folds(samples, minimum_train_groups=spec.minimum_train_sessions,
        test_groups=1, gap_seconds=spec.gap_seconds, session_groups=True)
    stored_folds = _list(validation['folds'])
    predictions = _list(validation['predictions'])
    if len(stored_folds) != len(folds) or len(predictions) != len(folds):
        raise ResearchError('REPORT_FOLD_COUNTS_INVALID')
    errors: dict[str, list[float]] = {name: [] for name in ('ridge', 'zero', 'mean', 'chance', 'rule')}
    for index, (fold, stored, prediction) in enumerate(zip(folds, stored_folds, predictions)):
        record = _object(stored, {'train', 'test', 'purged', 'status', 'fit_at', 'model'})
        expected = cast(Report, _json(asdict(fold)))
        for key in ('train', 'test', 'purged', 'fit_at'):
            if record[key] != expected[key]:
                raise ResearchError('REPORT_CAUSAL_FOLDS_INVALID')
        if record['status'] != 'EVALUATED_SYNTHETIC':
            raise ResearchError('REPORT_FOLD_STATUS_INVALID')
        fitted = _object(record['model'], {'scaler', 'coefficients', 'intercept', 'alpha'})
        scaler = _object(fitted['scaler'], {'means', 'scales'})
        coefficients = [_number(v) for v in _list(fitted['coefficients'])]
        means = [_number(v) for v in _list(scaler['means'])]
        scales = [_number(v) for v in _list(scaler['scales'])]
        if (len(coefficients) != 2 or len(means) != 2 or len(scales) != 2
                or any(v <= 0 for v in scales) or _number(fitted['alpha']) != spec.alpha):
            raise ResearchError('REPORT_MODEL_SHAPE_INVALID')
        # Verify train-only scaling and normal equations without refitting a model.
        y_mean = math.fsum(targets[k] for k in fold.train) / len(fold.train)
        if _number(fitted['intercept']) != y_mean:
            raise ResearchError('REPORT_TRAIN_ONLY_INTERCEPT_INVALID')
        for column in range(2):
            mean = math.fsum(features[k][column] for k in fold.train) / len(fold.train)
            scale = math.sqrt(math.fsum((features[k][column] - mean)**2
                                       for k in fold.train) / len(fold.train)) or 1.0
            if means[column] != mean or scales[column] != scale:
                raise ResearchError('REPORT_TRAIN_ONLY_SCALER_INVALID')
        x = [[(features[k][j] - means[j]) / scales[j] for j in range(2)] for k in fold.train]
        for j in range(2):
            lhs = math.fsum(math.fsum(row[j] * row[k] for row in x) * coefficients[k]
                            for k in range(2)) + spec.alpha * coefficients[j]
            rhs = math.fsum(row[j] * (targets[key] - y_mean) for row, key in zip(x, fold.train))
            if not math.isclose(lhs, rhs, rel_tol=1e-9, abs_tol=1e-9):
                raise ResearchError('REPORT_COEFFICIENTS_INVALID')
        pred = _object(prediction, {'row_id', 'fold', 'predictions', 'actual'})
        _number(pred['actual'])
        key = fold.test[0]
        if pred['row_id'] != key or _integer(pred['fold']) != index or pred['actual'] != targets[key]:
            raise ResearchError('REPORT_PREDICTION_BINDING_INVALID')
        candidates = _object(pred['predictions'], set(errors))
        import random
        magnitude = math.fsum(abs(targets[k]) for k in fold.train) / len(fold.train)
        expected_candidates = {'ridge': y_mean + math.fsum(
            (features[key][j] - means[j]) / scales[j] * coefficients[j] for j in range(2)),
            'zero': 0.0, 'mean': y_mean, 'chance': magnitude * random.Random(spec.seed + index).choice((-1, 1)),
            'rule': magnitude * (1 if features[key][0] > 0 else -1 if features[key][0] < 0 else 0)}
        for name in errors:
            number = _number(candidates[name])
            if not math.isclose(number, expected_candidates[name], rel_tol=1e-12, abs_tol=1e-12):
                raise ResearchError('REPORT_PREDICTIONS_INVALID')
            errors[name].append(targets[key] - number)
    expected_metrics = {name: {'mae': math.fsum(abs(e) for e in es) / len(es),
                              'mse': math.fsum(e*e for e in es) / len(es)} for name, es in errors.items()}
    _same_shape(validation['metrics'], cast(Json, expected_metrics))
    if validation['metrics'] != expected_metrics:
        raise ResearchError('REPORT_METRICS_INVALID')
    def counts(ids: tuple[str, ...]) -> list[float]:
        return [float(sum(1 for k in ids if (0 if features[k][0] < -1/3 else
            2 if features[k][0] > 1/3 else 1) == bin_id)) for bin_id in range(3)]
    expected_drift = _json(histogram_drift(counts(folds[-1].train), counts(folds[-1].test)))
    _same_shape(payload['drift'], expected_drift)
    if payload['drift'] != expected_drift:
        raise ResearchError('REPORT_DRIFT_INVALID')


def report_json(report: bytes | Mapping[str, object]) -> bytes:
    """Canonical export for local retention or a grounded LLM evidence envelope."""
    return _canonical(validate_report(report))


def inspect_report(report: bytes | Mapping[str, object]) -> Report:
    """Verified defensive copy suitable for all three UI views."""
    return validate_report(report)


def compare_reports(a: bytes | Mapping[str, object], b: bytes | Mapping[str, object]) -> Report:
    """Compare like assumptions/input/code only; never infer statistical edge."""
    left, right = validate_report(a), validate_report(b)
    lp, rp = _object(left['payload']), _object(right['payload'])
    li, ri = _object(lp['identities']), _object(rp['identities'])
    reasons = [name for name in ('input_sha256', 'code_sha256') if li[name] != ri[name]]
    if lp['assumptions'] != rp['assumptions']:
        reasons.append('assumptions')
    delta: Report = {}
    if not reasons:
        lm = _object(_object(lp['validation'])['metrics'])
        rm = _object(_object(rp['validation'])['metrics'])
        delta = {name: {metric: _number(_object(rm[name])[metric]) - _number(_object(lm[name])[metric])
                        for metric in ('mae', 'mse')} for name in lm}
    return {'status': 'INCOMPATIBLE_ASSUMPTIONS' if reasons else 'DESCRIPTIVE_SYNTHETIC_COMPARISON',
            'incompatibilities': list(reasons), 'metric_deltas_b_minus_a': delta,
            'left_sha256': left['report_sha256'], 'right_sha256': right['report_sha256'],
            'edge_status': 'NOT_ESTABLISHED', 'training_eligible': False,
            'approval_authority': False, 'performance_units': 'ARTIFICIAL_REGRESSION_UNITS_NOT_PNL'}
