"""Synthetic TOML/Streamlit/environment tests; never read real secrets."""
import json
import tomllib
import ast
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from release_expectations import NAMES, resolve


def settings():
    return dict(zip(NAMES, ('fixture-build', 'a' * 64, 'b' * 64)))


def test_root_toml_and_streamlit_export_match():
    root = tomllib.loads('EXPECTED_APP_BUILD="fixture-build"\n'
        'RESILIENCE_POLICY_SHA256="' + 'a' * 64 + '"\n'
        'EXPECTED_EQUITY_CODE_SHA256="' + 'b' * 64 + '"\n[auth]\nclient_id="private-token"')
    values, diagnostics = resolve(root, settings(), actual=settings())
    assert values == settings()
    assert all(row['source'] == 'STREAMLIT_ROOT' and row['matches_actual'] for row in diagnostics.values())
    assert 'private-token' not in json.dumps(diagnostics)
    assert 'fixture-build' not in json.dumps(diagnostics)


def test_toml_section_never_supplies_values():
    root = tomllib.loads('[auth]\nEXPECTED_APP_BUILD="private-value"')
    values, diagnostics = resolve(root, {})
    assert not values
    assert diagnostics[NAMES[0]]['misplaced_sections'] == ['auth']
    assert diagnostics[NAMES[0]]['status'] == 'MISSING'
    assert 'private-value' not in json.dumps(diagnostics)


def test_environment_only_and_missing_fields():
    values, diagnostics = resolve({}, settings())
    assert values == settings() and all(row['source'] == 'ENVIRONMENT' for row in diagnostics.values())
    values, diagnostics = resolve({}, {})
    assert not values and all(row['status'] == 'MISSING' for row in diagnostics.values())


@pytest.mark.parametrize('bad', ['', ' ', 'a' * 63, 'A' * 64, ' a' * 32, 123, None, ['private']])
def test_invalid_root_does_not_fall_back(bad):
    root = settings()
    root[NAMES[2]] = bad
    values, diagnostics = resolve(root, {})
    assert NAMES[2] not in values
    assert diagnostics[NAMES[2]]['status'] == 'INVALID_FORMAT'


def test_conflicting_sources_fail_closed_without_values():
    environment = settings()
    environment[NAMES[0]] = 'private-old-build'
    values, diagnostics = resolve(settings(), environment)
    assert NAMES[0] not in values and diagnostics[NAMES[0]]['status'] == 'SOURCE_CONFLICT'
    assert 'private-old-build' not in json.dumps(diagnostics)


def test_read_error_is_explicit_and_never_leaks_exception_or_accepts_old_env():
    class Broken(Mapping):
        def __getitem__(self, key): raise ValueError('private-token raw TOML line')
        def __iter__(self): return iter(NAMES)
        def __len__(self): return len(NAMES)
    values, diagnostics = resolve(Broken(), settings())
    assert not values
    assert all(row['status'] == 'SECRETS_READ_ERROR' for row in diagnostics.values())
    assert 'private-token' not in json.dumps(diagnostics)


def test_present_old_build_reports_mismatch_not_missing():
    expected = settings()
    expected[NAMES[0]] = 'old-build'
    values, diagnostics = resolve(expected, {}, actual=settings())
    assert values[NAMES[0]] == 'old-build'
    assert diagnostics[NAMES[0]]['matches_actual'] is False
    assert diagnostics[NAMES[0]]['status'] == 'VALID'


def test_misspelling_does_not_match_expected_key():
    values, diagnostics = resolve({'expected_app_build': 'fixture-build'}, {})
    assert not values and diagnostics[NAMES[0]]['status'] == 'MISSING'


def test_invalid_root_cannot_accept_valid_environment_fallback():
    root = settings()
    root[NAMES[2]] = 123
    values, diagnostics = resolve(root, settings())
    assert NAMES[2] not in values
    assert diagnostics[NAMES[2]]['status'] == 'SOURCE_CONFLICT'


@pytest.mark.parametrize('bad', [42, None, '', ' build', 'build ', 'build\nother', 'build\x00'])
def test_invalid_build_is_not_coerced_or_trimmed(bad):
    values, diagnostics = resolve({NAMES[0]: bad}, {})
    assert not values and diagnostics[NAMES[0]]['status'] == 'INVALID_FORMAT'


def test_root_wins_over_unaccepted_section_and_section_names_only_are_reported():
    root = settings()
    root['auth'] = {NAMES[0]: 'private-nested-build', 'client_secret': 'private-token'}
    values, diagnostics = resolve(root, {})
    assert values == settings()
    assert diagnostics[NAMES[0]]['misplaced_sections'] == ['auth']
    assert 'private-' not in json.dumps(diagnostics)


def app_function(name):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def test_app_configuration_uses_same_resolver_and_no_runtime_probe():
    scope = dict(st=SimpleNamespace(secrets=settings()), os=SimpleNamespace(environ=settings()),
                 APP_BUILD=settings()[NAMES[0]], EQUITY_RELEASE_FINGERPRINT=settings()[NAMES[2]],
                 RESILIENCE_CONTROL_PLANE=SimpleNamespace(policy=SimpleNamespace(digest=settings()[NAMES[1]])),
                 resolve_release_expectations=resolve)
    exec(compile(ast.Module(body=[app_function('_release_configuration')], type_ignores=[]), '<adapter>', 'exec'), scope)
    values, diagnostics = scope['_release_configuration']()
    assert values == settings()
    assert all(item['matches_actual'] is True for item in diagnostics.values())


@pytest.mark.parametrize('asset', ['equity', 'options', 'futures', 'mcx', 'equity_smc'])
def test_equity_adapter_removes_rejected_environment_but_other_routes_unchanged(asset):
    function = app_function('evaluate_live_governance_contract')
    branch = next(node for node in function.body if isinstance(node, ast.If) and
                  any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and
                      call.func.id == '_release_configuration' for call in ast.walk(node)))
    scope = dict(evidence_bundle=SimpleNamespace(context=SimpleNamespace(asset_class=asset)),
                 readiness_environment={**settings(), 'OTHER_CONFIG': 'preserved'},
                 RELEASE_EXPECTATION_NAMES=NAMES,
                 _release_configuration=lambda: ({}, {}))
    exec(compile(ast.Module(body=[branch], type_ignores=[]), '<equity-adapter>', 'exec'), scope)
    expected = {'OTHER_CONFIG': 'preserved'} if asset == 'equity' else {**settings(), 'OTHER_CONFIG': 'preserved'}
    assert scope['readiness_environment'] == expected
