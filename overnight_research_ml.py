"""Deterministic chronological/purged folds and inactive ML trial foundation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
import math
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from overnight_research_dataset import DataScope, ResearchError, fingerprint, instant, scoped_time, sha, validate_version, unique_pairs


@dataclass(frozen=True)
class LabelInterval:
    row_id: str
    version: str
    decision_at: str
    feature_start: str
    available_at: str
    label_end: str
    label_available_at: str
    group_id: str
    data_scope: DataScope = 'DEVELOPMENT_ONLY'

    def validate(self) -> None:
        sha(self.row_id)
        validate_version(self.version)
        start, decision, available, end, known = (scoped_time(v, self.data_scope) for v in (
            self.feature_start, self.decision_at, self.available_at, self.label_end, self.label_available_at))
        if (not self.group_id
                or not start <= decision <= available < end <= known):
            raise ResearchError('LABEL_INTERVAL_INVALID')


@dataclass(frozen=True)
class Fold:
    train: tuple[str, ...]
    test: tuple[str, ...]
    purged: tuple[str, ...]
    status: str
    fit_at: str


def chronological_folds(samples: Sequence[LabelInterval], *, minimum_train_groups: int,
                        test_groups: int, gap_seconds: int = 0,
                        session_groups: bool = False) -> tuple[Fold, ...]:
    """Expanding walk-forward, preserving same-decision/version groups.

    Purge closed information intervals intersecting test feature history and labels
    unavailable at fit time. Apply a time gap before each test. No future training
    exists here, so a post-test embargo would be vacuous; this is not CPCV.
    Explicit session_groups keeps every IST-day row in one test/train block;
    minimum counts then mean sessions, never individual five-minute decisions.
    """
    if (type(minimum_train_groups) is not int or minimum_train_groups < 1
            or type(test_groups) is not int or test_groups < 1
            or type(gap_seconds) is not int or gap_seconds < 0
            or type(session_groups) is not bool):
        raise ResearchError('FOLD_CONFIGURATION_INVALID')
    groups: dict[str, list[LabelInterval]] = {}
    seen: set[str] = set()
    time_groups: dict[object, str] = {}
    for sample in samples:
        sample.validate()
        if sample.row_id in seen:
            raise ResearchError('DUPLICATE_SAMPLE')
        seen.add(sample.row_id)
        moment = scoped_time(sample.decision_at, sample.data_scope)
        if moment in time_groups and time_groups[moment] != sample.group_id:
            raise ResearchError('SAME_DECISION_MUST_SHARE_GROUP')
        time_groups[moment] = sample.group_id
        group_identity = (moment.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()
                 if session_groups else sample.group_id)
        groups.setdefault(group_identity, []).append(sample)
    if len({sample.data_scope for sample in samples}) > 1:
        raise ResearchError('MIXED_DATA_SCOPES_FORBIDDEN')
    ordered = sorted(groups.values(), key=lambda group: min(instant(s.decision_at) for s in group))
    for group in ordered:
        if not session_groups and len({instant(s.decision_at) for s in group}) != 1:
            raise ResearchError('GROUP_SPANS_DECISIONS')
    folds: list[Fold] = []
    for index in range(minimum_train_groups, len(ordered), test_groups):
        test = [s for group in ordered[index:index + test_groups] for s in group]
        fit_at = min(instant(s.available_at) for s in test)
        boundary = min(instant(s.decision_at) for s in test) - timedelta(seconds=gap_seconds)
        train: list[str] = []
        purged: list[str] = []
        for group in ordered[:index]:
            unsafe = any(instant(s.label_available_at) >= fit_at
                or instant(s.available_at) >= boundary
                or any(instant(s.feature_start) <= instant(t.label_end)
                    and instant(t.feature_start) <= instant(s.label_end) for t in test)
                for s in group)
            (purged if unsafe else train).extend(s.row_id for s in group)
        folds.append(Fold(tuple(sorted(train)), tuple(sorted(s.row_id for s in test)),
            tuple(sorted(purged)), 'READY_FOR_OFFLINE_VALIDATION' if train else 'INSUFFICIENT_DATA', fit_at.isoformat()))
    return tuple(folds)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    feature_names: tuple[str, ...]
    algorithm: str
    parameters_json: str
    feature_code_sha256: str
    registered_at: str
    seed: int

    def identity(self) -> str:
        import json
        instant(self.registered_at)
        sha(self.feature_code_sha256)
        forbidden = {'label', 'target', 'net_pnl', 'direction', 'label_end', 'training_eligible'}
        if (not self.name or self.algorithm not in ('MEAN_BASELINE', 'LINEAR_RIDGE_RESEARCH')
                or not self.feature_names or len(set(self.feature_names)) != len(self.feature_names)
                or set(self.feature_names) & forbidden or type(self.seed) is not int):
            raise ResearchError('MODEL_SPEC_INVALID')
        try:
            parameters = json.loads(self.parameters_json, object_pairs_hook=unique_pairs)
            if not isinstance(parameters, dict):
                raise ValueError()
            fingerprint(parameters)
            if self.algorithm == 'LINEAR_RIDGE_RESEARCH':
                if (set(parameters) != {'alpha', 'minimum_train_rows'}
                        or type(parameters['alpha']) not in (int, float)
                        or not math.isfinite(parameters['alpha']) or parameters['alpha'] <= 0
                        or type(parameters['minimum_train_rows']) is not int or parameters['minimum_train_rows'] < 2):
                    raise ValueError()
        except (ValueError, TypeError):
            raise ResearchError('MODEL_PARAMETERS_INVALID') from None
        return fingerprint({**asdict(self), 'parameters_json': parameters})


class TrialRegistry:
    """In-memory append-only hash chain; no persistent or production registry."""

    def __init__(self) -> None:
        self._events: list[bytes] = []
        self._ids: set[str] = set()

    def record(self, *, trial_id: str, spec: ModelSpec, dataset_sha256: str,
               folds: Sequence[Fold], started_at: str, completed_at: str,
               status: str, metrics: Mapping[str, float], failure_code: str | None = None) -> str:
        from overnight_research_dataset import canonical
        start, end = map(instant, (started_at, completed_at))
        sha(dataset_sha256)
        model_id = spec.identity()
        if (not trial_id or trial_id in self._ids or not instant(spec.registered_at) <= start <= end
                or status not in ('COMPLETED', 'FAILED', 'INSUFFICIENT_DATA')
                or (status == 'COMPLETED' and (not folds or any(not f.train or not f.test for f in folds)))
                or (status != 'COMPLETED' and metrics)
                or (status == 'FAILED' and not failure_code)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in metrics.values())):
            raise ResearchError('TRIAL_INVALID')
        event = {'trial_id': trial_id, 'model_sha256': model_id, 'dataset_sha256': dataset_sha256,
            'folds_sha256': fingerprint([asdict(f) for f in folds]), 'started_at': start.isoformat(),
            'completed_at': end.isoformat(), 'status': status, 'metrics': dict(metrics),
            'failure_code': failure_code, 'previous_sha256': self.head,
            'training_eligible': False, 'approval_authority': False}
        identity = fingerprint(event)
        self._events.append(canonical({**event, 'event_sha256': identity}))
        self._ids.add(trial_id)
        return identity

    @property
    def head(self) -> str | None:
        import json
        return json.loads(self._events[-1])['event_sha256'] if self._events else None

    def events(self) -> tuple[dict[str, Any], ...]:
        import json
        return tuple(json.loads(event) for event in self._events)


def mean_baseline(train: Sequence[float], test: Sequence[float]) -> dict[str, float]:
    """Train-only deterministic regression baseline, for synthetic/offline validation."""
    if not train or not test or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*train, *test)):
        raise ResearchError('BASELINE_DATA_INVALID')
    prediction = math.fsum(train) / len(train)
    return {'prediction': prediction, 'mae': math.fsum(abs(v - prediction) for v in test) / len(test),
            'mse': math.fsum((v - prediction) ** 2 for v in test) / len(test)}


@dataclass(frozen=True)
class Standardizer:
    means: tuple[float, ...]
    scales: tuple[float, ...]

    @classmethod
    def fit(cls, training: Sequence[Sequence[float]]) -> Standardizer:
        """Fit only the explicitly supplied training matrix; no global statistics."""
        if not training or not training[0]:
            raise ResearchError('TRAINING_MATRIX_REQUIRED')
        width = len(training[0])
        if any(len(row) != width or any(type(v) not in (int, float) or not math.isfinite(v)
                                      for v in row) for row in training):
            raise ResearchError('TRAINING_MATRIX_INVALID')
        means = tuple(math.fsum(row[i] for row in training) / len(training) for i in range(width))
        scales = tuple(math.sqrt(math.fsum((row[i] - means[i])**2 for row in training) / len(training))
                       or 1.0 for i in range(width))
        return cls(means, scales)

    def transform(self, rows: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
        if any(len(row) != len(self.means) or any(type(v) not in (int, float) or not math.isfinite(v)
                                                for v in row) for row in rows):
            raise ResearchError('TRANSFORM_MATRIX_INVALID')
        return tuple(tuple((v - mean) / scale for v, mean, scale in zip(row, self.means, self.scales))
                     for row in rows)


def solve_system(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> tuple[float, ...]:
    """Deterministic partial-pivot Gaussian elimination for small ridge systems."""
    n = len(vector)
    if not n or len(matrix) != n or any(len(row) != n for row in matrix):
        raise ResearchError('LINEAR_SYSTEM_INVALID')
    augmented = [list(row) + [vector[i]] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda i: abs(augmented[i][column]))
        if not math.isfinite(augmented[pivot][column]) or abs(augmented[pivot][column]) < 1e-14:
            raise ResearchError('RIDGE_SYSTEM_NUMERICALLY_SINGULAR')
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [v / divisor for v in augmented[column]]
        for i in range(n):
            if i != column:
                multiplier = augmented[i][column]
                augmented[i] = [v - multiplier * p for v, p in zip(augmented[i], augmented[column])]
    result = tuple(row[-1] for row in augmented)
    if not all(math.isfinite(v) for v in result):
        raise ResearchError('RIDGE_NONFINITE_RESULT')
    return result


@dataclass(frozen=True)
class RidgeModel:
    scaler: Standardizer
    coefficients: tuple[float, ...]
    intercept: float
    alpha: float

    @classmethod
    def fit(cls, training: Sequence[Sequence[float]], targets: Sequence[float], *, alpha: float) -> RidgeModel:
        if (type(alpha) not in (int, float) or not math.isfinite(alpha) or alpha <= 0
                or len(training) != len(targets) or len(targets) < 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in targets)):
            raise ResearchError('RIDGE_TRAINING_INVALID')
        scaler = Standardizer.fit(training)
        transformed = scaler.transform(training)
        intercept = math.fsum(targets) / len(targets)
        width = len(scaler.means)
        matrix = [[math.fsum(row[i] * row[j] for row in transformed) + (alpha if i == j else 0)
                   for j in range(width)] for i in range(width)]
        vector = [math.fsum(row[i] * (target - intercept) for row, target in zip(transformed, targets))
                  for i in range(width)]
        return cls(scaler, solve_system(matrix, vector), intercept, alpha)

    def predict(self, rows: Sequence[Sequence[float]]) -> tuple[float, ...]:
        return tuple(self.intercept + math.fsum(v * c for v, c in zip(row, self.coefficients))
                     for row in self.scaler.transform(rows))


def walk_forward_ridge(*, samples: Sequence[LabelInterval], features: Mapping[str, Sequence[float]],
                       targets: Mapping[str, float], spec: ModelSpec, evaluated_at: str,
                       minimum_train_groups: int, test_groups: int, gap_seconds: int = 0,
                       synthetic_fixture: bool = False, session_groups: bool = False) -> dict[str, Any]:
    """Train-only ridge and zero/mean/chance/simple-rule baselines on purged folds.

    Real-data admission is pending the main agent's licensing/PIT adapter. Only an
    explicit synthetic fixture runs now; all results remain non-training evidence.
    Targets must not be derived from index prices and called executable net P&L.
    """
    import json
    import random
    spec.identity()
    if spec.algorithm != 'LINEAR_RIDGE_RESEARCH':
        raise ResearchError('RIDGE_SPEC_REQUIRED')
    evaluated = instant(evaluated_at)
    folds = chronological_folds(samples, minimum_train_groups=minimum_train_groups,
                                test_groups=test_groups, gap_seconds=gap_seconds,
                                session_groups=session_groups)
    result: dict[str, Any] = {'status': 'INSUFFICIENT_DATA', 'reasons': [], 'folds': [],
        'predictions': [], 'metrics': {}, 'synthetic_fixture': synthetic_fixture,
        'training_eligible': False, 'approval_authority': False, 'fill_evidence': False}
    if synthetic_fixture is not True:
        return {**result, 'reasons': ['INDEPENDENT_DATA_AND_LICENSING_ADMISSION_PENDING']}
    if not folds:
        return {**result, 'reasons': ['NO_CHRONOLOGICAL_FOLDS']}
    lookup = {sample.row_id: sample for sample in samples}
    if instant(spec.registered_at) > min(instant(sample.available_at) for sample in samples):
        raise ResearchError('MODEL_NOT_FROZEN_BEFORE_OBSERVATIONS')
    if set(features) - lookup.keys() or set(targets) - lookup.keys():
        raise ResearchError('ML_ROW_IDENTITY_MISMATCH')
    parameters = json.loads(spec.parameters_json, object_pairs_hook=unique_pairs)
    metric_errors: dict[str, list[float]] = {name: [] for name in ('ridge', 'zero', 'mean', 'chance', 'rule')}
    for fold_number, fold in enumerate(folds):
        ids = (*fold.train, *fold.test)
        if (len(fold.train) < parameters['minimum_train_rows']
                or any(key not in features or key not in targets for key in ids)
                or any(instant(lookup[key].label_available_at) > evaluated for key in fold.test)):
            result['folds'].append({**asdict(fold), 'status': 'INSUFFICIENT_DATA'})
            result['reasons'].append('FOLD_DATA_OR_LABELS_INCOMPLETE')
            continue
        x_train, x_test = [features[key] for key in fold.train], [features[key] for key in fold.test]
        if any(len(row) != len(spec.feature_names) for row in (*x_train, *x_test)):
            raise ResearchError('FEATURE_SCHEMA_MISMATCH')
        y_train = [targets[key] for key in fold.train]
        if any(type(targets[key]) not in (int, float) or not math.isfinite(targets[key]) for key in ids):
            raise ResearchError('NONFINITE_ML_TARGET')
        model = RidgeModel.fit(x_train, y_train, alpha=parameters['alpha'])
        predictions = model.predict(x_test)
        magnitude = math.fsum(abs(value) for value in y_train) / len(y_train)
        rng = random.Random(spec.seed + fold_number)
        for key, prediction, x in zip(fold.test, predictions, x_test):
            candidates = {'ridge': prediction, 'zero': 0.0, 'mean': model.intercept,
                'chance': magnitude * rng.choice((-1, 1)),
                'rule': magnitude * (1 if x[0] > 0 else -1 if x[0] < 0 else 0)}
            result['predictions'].append({'row_id': key, 'fold': fold_number,
                'predictions': candidates, 'actual': targets[key]})
            for name, value in candidates.items():
                metric_errors[name].append(targets[key] - value)
        result['folds'].append({**asdict(fold), 'model': asdict(model), 'status': 'EVALUATED_SYNTHETIC'})
    if result['predictions']:
        result['metrics'] = {name: {'mae': math.fsum(abs(v) for v in errors) / len(errors),
            'mse': math.fsum(v*v for v in errors) / len(errors)} for name, errors in metric_errors.items()}
        result['status'] = 'PARTIAL_SYNTHETIC_EVALUATION' if result['reasons'] else 'COMPLETED_SYNTHETIC_EVALUATION'
    return result
