"""Inactive, local-engine-only contained bridge. Preview has zero operational IO."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, NoReturn
import uuid

from archive_preservation_inventory import measure, private_path, publish
from archive_preservation_witness import verify_observation
from archive_catalog_verify import PRESERVED_BUNDLE_SHA256
from outcomes_private_worker import SAFE_ERROR_CODES, CONTAINMENT_PROFILE, PROBE_FIELDS, WRITE_RESULTS, readonly_detail_passes
from programme_next_upload_check import safe_read
from normal_user_test_run import _normal_windows, Blocked

MIB = 1024**2
MEMORY = 768 * MIB
MAX_OUTPUT = 65536
BUILD_FILES = ('outcomes_private_worker.py', 'archive_catalog_reconcile.py', 'archive_catalog_verify.py',
    'archive_recovery_review.py', 'outcomes_footer_diagnostic.py', 'outcomes_large_profile.py')
ENGINE = 'npipe:////./pipe/dockerDesktopLinuxEngine' if os.name == 'nt' else 'unix:///var/run/docker.sock'
CHECKS = frozenset({'nonroot', 'non_pid1', 'no_new_privileges', 'zero_capabilities', 'host_socket_absent',
    'no_routes', 'finite_memory_cgroup', 'finite_pid_cgroup', 'synthetic_inputs_exact',
    'root_readonly', 'input_readonly', 'network_denied', 'codec', 'core_dumps_disabled'})


class SyntheticFailure(ValueError):
    def __init__(self, failed: tuple[str, ...], probes: dict[str, Any]) -> None:
        super().__init__('SYNTHETIC_CONTAINER_CHECK_FAILED')
        if any(name not in CHECKS for name in failed):
            raise ValueError('SYNTHETIC_PROBE_SCHEMA_INVALID')
        self.failed = failed
        self.probes = validate_probes(probes)


def validate_probes(value: Any) -> dict[str, Any]:
    """Closed public diagnostic vocabulary, never arbitrary worker text/paths."""
    if type(value) is not dict or set(value) != {'root', 'catalog', 'bundle'}:
        raise ValueError('SYNTHETIC_PROBE_SCHEMA_INVALID')
    result: dict[str, Any] = {}
    for name in ('root', 'catalog', 'bundle'):
        detail = value[name]
        if (type(detail) is not dict or set(detail) != PROBE_FIELDS
                or any(type(detail[k]) is not bool for k in PROBE_FIELDS - {'write_open_result'})
                or type(detail['write_open_result']) is not str or detail['write_open_result'] not in WRITE_RESULTS):
            raise ValueError('SYNTHETIC_PROBE_SCHEMA_INVALID')
        result[name] = dict(detail)
    return result


def docker_prefix(config: Path) -> list[str]:
    executable = shutil.which('docker')
    if executable is None:
        raise ValueError('LOCAL_DOCKER_UNAVAILABLE')
    config.mkdir(exist_ok=False)
    return [executable, '--config', str(config), '--host', ENGINE]


def execute(command: list[str], seconds: int = 20, maximum: int = MAX_OUTPUT, *, allow_nonzero: bool = False) -> bytes:
    """Bounded stdout, discarded stderr; never emit raw Docker/Arrow diagnostics."""
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME', 'USERPROFILE'}}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL, env=environment)
    output = bytearray()
    overflow = threading.Event()
    failed, eof = threading.Event(), threading.Event()
    def drain() -> None:
        try:
            assert process.stdout is not None
            while True:
                block = process.stdout.read(1024)
                if not block:
                    eof.set()
                    break
                if len(output) + len(block) > maximum:
                    overflow.set()
                    process.kill()
                    break
                output.extend(block)
        except Exception:
            failed.set()
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        process.wait(timeout=seconds)
        reader.join(timeout=3)
        if reader.is_alive() or overflow.is_set() or failed.is_set() or not eof.is_set() or (process.returncode != 0 and not allow_nonzero):
            raise ValueError('LOCAL_CONTAINER_COMMAND_FAILED')
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(timeout=3)
        if process.stdout is not None:
            process.stdout.close()


def create_arguments(image: str, name: str, catalog: Path, bundle: Path, worker_args: list[str]) -> list[str]:
    if re.fullmatch(r'sha256:[0-9a-f]{64}', image) is None or re.fullmatch(r'researchops-bridge-[0-9a-f]{32}', name) is None:
        raise ValueError('EXTERNAL_IMAGE_ID_AND_FRESH_NAME_REQUIRED')
    for path in (catalog, bundle):
        private_path(path)
        if '..' in path.parts or any(c in str(path) for c in ',\n\r'):
            raise ValueError('MOUNT_PATH_UNSUPPORTED')
    return ['create', '--name', name, '--pull=never', '--platform=linux/amd64', '--init',
        '--network=none', '--read-only', '--user=65534:65534', '--cap-drop=ALL',
        '--security-opt=no-new-privileges:true', '--pids-limit=16', '--memory=' + str(MEMORY),
        '--memory-swap=' + str(MEMORY), '--cpus=1', '--ipc=none', '--cgroupns=private',
        '--runtime=runc', '--log-driver=none', '--restart=no', '--ulimit=cpu=60:60',
        '--ulimit=nofile=64:64', '--ulimit=core=0:0', '--mount', f'type=bind,source={catalog},target=/inputs/catalog.json,readonly',
        '--mount', f'type=bind,source={bundle},target=/inputs/bundle.zip,readonly', image, *worker_args]


def source_matches(actual: str, path: Path) -> bool:
    native = str(path).replace('\\', '/')
    allowed = {native}
    if re.match(r'^[A-Za-z]:/', native):
        suffix = native[0].lower() + native[2:]
        allowed |= {'/run/desktop/mnt/host/' + suffix, '/host_mnt/' + suffix}
    return actual.replace('\\', '/') in allowed


def validate_inspection(value: dict[str, Any], image: str, catalog: Path, bundle: Path) -> None:
    host, config, mounts = value['HostConfig'], value['Config'], value['Mounts']
    if (value['Image'] != image or config['User'] != '65534:65534' or config['Image'] != image
            or host['NetworkMode'] != 'none' or host['ReadonlyRootfs'] is not True
            or host['Privileged'] is not False or host.get('Init') is not True or host['CapDrop'] != ['ALL']
            or host['CapAdd'] or host['Devices'] or host.get('DeviceRequests')
            or host['Memory'] != MEMORY or host['MemorySwap'] != MEMORY or host['NanoCpus'] != 1000000000
            or host['PidsLimit'] != 16 or host['IpcMode'] != 'none' or host['PidMode']
            or host['CgroupnsMode'] != 'private' or host['Runtime'] != 'runc'
            or host['LogConfig']['Type'] != 'none' or host['RestartPolicy']['Name'] != 'no'
            or set(host['SecurityOpt']) != {'no-new-privileges:true'}
            or host.get('PortBindings') or config.get('Volumes') or host.get('VolumesFrom')):
        raise ValueError('CONTAINER_POLICY_READBACK_MISMATCH')
    actual = {(m['Destination'], m['Source'], m['RW'], m['Type']) for m in mounts}
    # Docker Desktop translates Windows sources; verify its HostConfig original
    # source separately rather than treating the translated /run/desktop path as trust.
    expected_mounts = [('/inputs/catalog.json', str(catalog)), ('/inputs/bundle.zip', str(bundle))]
    requested = host['Mounts']
    by_target = dict(expected_mounts)
    if (len(requested) != 2 or {m['Target'] for m in requested} != set(by_target)
            or any(m['ReadOnly'] is not True or m['Type'] != 'bind'
                   or not source_matches(m['Source'], Path(by_target[m['Target']])) for m in requested)):
        raise ValueError('EXACT_READONLY_INPUTS_REQUIRED')
    if len(mounts) != 2 or len(actual) != 2 or {(m['Destination'], m['RW'], m['Type']) for m in mounts} != {
            ('/inputs/catalog.json', False, 'bind'), ('/inputs/bundle.zip', False, 'bind')}:
        raise ValueError('EXACT_READONLY_INPUTS_REQUIRED')
    for mount in mounts:
        expected = catalog if mount['Destination'] == '/inputs/catalog.json' else bundle
        if not source_matches(mount['Source'], expected):
            raise ValueError('EFFECTIVE_MOUNT_SOURCE_MISMATCH')
    limits = {u['Name']: (u['Soft'], u['Hard']) for u in host['Ulimits']}
    if limits != {'cpu': (60, 60), 'nofile': (64, 64), 'core': (0, 0)}:
        raise ValueError('CONTAINER_LIMIT_READBACK_MISMATCH')


def run_container(image: str, catalog: Path, bundle: Path, args: list[str], journal: Path, *, watchdog: bool = False) -> dict[str, Any]:
    name = 'researchops-bridge-' + uuid.uuid4().hex
    publish(journal, json.dumps(dict(name=name, image=image, phase='INTENT_NOT_EXECUTION')).encode())
    prefix = docker_prefix(journal.parent / (name + '-empty-config'))
    created = False
    try:
        identity = execute(prefix + create_arguments(image, name, catalog, bundle, args)).decode().strip()
        created = True
        if re.fullmatch('[0-9a-f]{64}', identity) is None:
            raise ValueError('CREATED_CONTAINER_ID_INVALID')
        inspected = json.loads(execute(prefix + ['inspect', name]))
        if len(inspected) != 1 or inspected[0]['State']['Running']:
            raise ValueError('CONTAINER_NOT_STOPPED_BEFORE_ADMISSION')
        validate_inspection(inspected[0], image, catalog, bundle)
        if inspected[0]['Config'].get('Entrypoint') != ['python', '-B', '/app/outcomes_private_worker.py'] or inspected[0]['Config'].get('Cmd') != args:
            raise ValueError('EXACT_WORKER_COMMAND_REQUIRED')
        if watchdog:
            # start client exits BEFORE the autonomous alarm; no attached client
            # remains to deliver cancellation. init makes worker a non-PID-1 task.
            execute(prefix + ['start', name], seconds=10)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                terminal = json.loads(execute(prefix + ['inspect', name], seconds=2))[0]
                if terminal['State']['Running'] is False:
                    validate_inspection(terminal, image, catalog, bundle)
                    if terminal['State']['Pid'] == 0 and terminal['State']['ExitCode'] == 142 and terminal['State']['OOMKilled'] is False:
                        return dict(status='AUTONOMOUS_WATCHDOG_VERIFIED')
                    break
                time.sleep(0.1)
            raise ValueError('AUTONOMOUS_WATCHDOG_NOT_VERIFIED')
        raw = execute(prefix + ['start', '--attach', name], seconds=150, maximum=4096, allow_nonzero=True)
        after = json.loads(execute(prefix + ['inspect', name]))[0]
        validate_inspection(after, image, catalog, bundle)
        if after['Config'].get('Entrypoint') != ['python', '-B', '/app/outcomes_private_worker.py'] or after['Config'].get('Cmd') != args:
            raise ValueError('EXACT_WORKER_COMMAND_REQUIRED')
        if after['State']['Running'] or after['State']['Pid'] != 0 or after['State']['OOMKilled']:
            raise ValueError('CONTAINER_TERMINAL_STATE_NOT_VERIFIED')
        from programme_next_upload_check import unique
        result = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(result, dict):
            raise ValueError('WORKER_REPORT_INVALID')
        if after['State']['ExitCode'] != 0:
            if (set(result) != {'status', 'code', 'row_values_printed', 'deletion_authorised', 'training_eligible'}
                    or result['status'] != 'BLOCKED' or result['code'] not in SAFE_ERROR_CODES
                    or any(result[k] is not False for k in ('row_values_printed', 'deletion_authorised', 'training_eligible'))):
                raise ValueError('WORKER_REPORT_INVALID')
        return result
    except Exception:
        terminal = False
        if created:
            try:
                execute(prefix + ['kill', name], seconds=5)
            except Exception:
                pass
            try:
                stopped = json.loads(execute(prefix + ['inspect', name]))[0]['State']
                terminal = stopped['Running'] is False and stopped['Pid'] == 0
            except Exception:
                pass
        publish(journal.with_name(journal.stem + '-failure.json'), json.dumps(dict(
            terminal_state_verified=terminal, retry_authorised=False, raw_values_printed=False)).encode())
        raise ValueError('CONTAINER_STOPPED_REVIEW_REQUIRED_NO_RETRY' if terminal else 'CONTAINER_CLEANUP_NOT_ESTABLISHED_NO_RETRY') from None


def stage_context(source: Path, destination: Path) -> None:
    private_path(destination)
    destination.mkdir(exist_ok=False)
    for name in BUILD_FILES:
        publish(destination / name, safe_read(source / name))
    publish(destination / 'Dockerfile', safe_read(source / 'docker/outcomes-private.Dockerfile'))
    publish(destination / 'requirements.txt', safe_read(source / 'docker/outcomes-private.requirements.txt'))
    # Defense against accidentally adding unrelated/private files before building.
    ignore = '**\n!Dockerfile\n!requirements.txt\n' + ''.join('!' + name + '\n' for name in BUILD_FILES)
    publish(destination / '.dockerignore', ignore.encode('ascii'))


def synthetic(image: str, root: Path) -> dict[str, Any]:
    root.mkdir(exist_ok=False)
    catalog, bundle = root / 'synthetic-catalog.json', root / 'synthetic-bundle.zip'
    # New PUBLIC synthetic fixtures, initial mode only; never chmod owner data.
    for path, raw in ((catalog, b'{"SYNTHETIC_ONLY":true}'), (bundle, b'SYNTHETIC_ONLY_NOT_A_RECOVERY_ZIP')):
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), 'wb') as stream:
            stream.write(raw)
    result = run_container(image, catalog, bundle, ['--selftest'], root / 'container-intent.json')
    if result.get('status') == 'BLOCKED' and result.get('code') in SAFE_ERROR_CODES:
        publish(root / 'worker-blocked.json', json.dumps(result, sort_keys=True).encode())
        raise ValueError(result['code'])
    if result.get('containment_profile') != CONTAINMENT_PROFILE:
        raise ValueError('CONTAINMENT_PROFILE_MISMATCH')
    if (set(result) != {'status', 'checks', 'private_decode_authorised', 'readonly_probes', 'containment_profile'}
            or result['status'] not in {'SYNTHETIC_CONTAINER_CHECK_PASSED', 'SYNTHETIC_CONTAINER_CHECK_FAILED'}
            or result['private_decode_authorised'] is not False or set(result['checks']) != CHECKS
            or any(type(v) is not bool for v in result['checks'].values())):
        raise ValueError('SYNTHETIC_CONTAINER_PROOF_MISSING')
    probes = validate_probes(result['readonly_probes'])
    if (result['checks']['root_readonly'] is not readonly_detail_passes(probes['root'])
            or result['checks']['input_readonly'] is not all(readonly_detail_passes(probes[n]) for n in ('catalog', 'bundle'))):
        raise ValueError('SYNTHETIC_PROBE_SCHEMA_INVALID')
    failed = tuple(sorted(key for key in CHECKS if result['checks'][key] is not True))
    if failed or result['status'] != 'SYNTHETIC_CONTAINER_CHECK_PASSED':
        publish(root / 'result.json', json.dumps(result, sort_keys=True).encode())
        raise SyntheticFailure(failed, probes)
    run_container(image, catalog, bundle, ['--watchdog-probe'], root / 'watchdog-intent.json', watchdog=True)
    result['autonomous_watchdog_verified'] = True
    publish(root / 'result.json', json.dumps(result, sort_keys=True).encode())
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError('ARGUMENTS_REVIEW_REQUIRED')


def owner_host(mode: str, platform: str | None = None) -> None:
    platform = os.name if platform is None else platform
    if platform == 'nt':
        try:
            _normal_windows()
        except Blocked as error:
            raise ValueError(str(error)) from None
    elif mode == 'private':
        raise ValueError('WINDOWS_OWNER_PRIVATE_HOST_REQUIRED')


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument('--mode', choices=('preview', 'stage', 'selftest', 'private'), default='preview')
    parser.add_argument('--confirm-run', action='store_true')
    parser.add_argument('--confirm-private-decode', action='store_true')
    for name in ('image-id', 'run-root', 'catalog', 'bundle', 'catalog-sha256', 'witness',
                 'trusted-public-key', 'public-sha256', 'latest-digest'):
        parser.add_argument('--' + name)
    parser.add_argument('--latest-generation', type=int)
    try:
        args = parser.parse_args()
    except ValueError:
        print(json.dumps(dict(status='BLOCKED', code='ARGUMENTS_REVIEW_REQUIRED', raw_error_printed=False)))
        return 2
    if args.mode == 'preview' or not args.confirm_run:
        print(json.dumps(dict(status='PREVIEW', input_reads=0, process_launches=0, writes=0,
                             private_decode_authorised=False)))
        return 0
    stage = 'HOST_PREFLIGHT'
    try:
        owner_host(args.mode)
        stage = 'ADMISSION'
        root = Path(args.run_root)
        private_path(root)
        if args.mode == 'stage':
            stage_context(Path(__file__).resolve().parent, root)
            result: dict[str, Any] = dict(status='PUBLIC_BUILD_CONTEXT_STAGED_NOT_BUILT')
        elif args.mode == 'selftest':
            stage = 'SYNTHETIC_CONTAINER'
            result = synthetic(args.image_id, root)
        else:
            if not args.confirm_private_decode:
                raise ValueError('EXPLICIT_PRIVATE_COMMISSIONING_REQUIRED')
            # Signature/current-head/preserved artifact binding BEFORE any private decoder.
            stage = 'PRESERVATION_WITNESS'
            from archive_preservation_witness import _read
            if re.fullmatch('[0-9a-f]{64}', args.public_sha256 or '') is None:
                raise ValueError('EXTERNAL_PUBLIC_KEY_FINGERPRINT_REQUIRED')
            checked = verify_observation(_read(Path(args.witness), 65536), _read(Path(args.trusted_public_key), 32),
                latest_generation=args.latest_generation, latest_digest=args.latest_digest,
                trusted_public_key_sha256=args.public_sha256)
            observed = json.loads(checked.observation_json)
            anchors = {r['role']: r['measured']['sha256'] for r in observed['originals']}
            if (observed.get('version') != 'preservation-inventory-v1' or len(observed['originals']) != 7 or len(anchors) != 7
                    or anchors['catalog'] != args.catalog_sha256 or anchors['bundle'] != PRESERVED_BUNDLE_SHA256):
                raise ValueError('PRESERVATION_GENERATION_MISMATCH')
            catalog, bundle = Path(args.catalog), Path(args.bundle)
            for file, expected, maximum in ((catalog, args.catalog_sha256, 5 * MIB), (bundle, PRESERVED_BUNDLE_SHA256, 2 * 1024**3)):
                private_path(file)
                if measure(file, maximum)['sha256'] != expected:
                    raise ValueError('ORIGINAL_GENERATION_PINS_REQUIRED')
            root.mkdir(exist_ok=False)
            publish(root / 'attempt.json', b'{"private_attempt_consumed":true}')
            binding = json.dumps(dict(format='outcomes-private-input-binding-v1',
                catalog_sha256=args.catalog_sha256, bundle_sha256=PRESERVED_BUNDLE_SHA256,
                image_id=args.image_id, preservation_generation=args.latest_generation,
                preservation_digest=args.latest_digest, public_key_sha256=args.public_sha256,
                ordinals=[135, 266, 318, 386, 395, 626, 698, 757]), sort_keys=True).encode()
            publish(root / 'input-binding.json', binding)
            stage = 'LOCAL_SYNTHETIC_ADMISSION'
            synthetic(args.image_id, root / 'synthetic')
            stage = 'CONTAINED_PRIVATE_STRUCTURAL_CHECK'
            result = run_container(args.image_id, catalog, bundle,
                ['--contained-private', '--catalog-sha256', args.catalog_sha256, '--bundle-sha256', PRESERVED_BUNDLE_SHA256], root / 'container-intent.json')
            if result.get('status') == 'BLOCKED':
                publish(root / 'worker-blocked.json', json.dumps(result, sort_keys=True).encode())
                raise ValueError(result['code'])
            flags = {'full_catalog_byte_footer_coverage', 'row_values_printed', 'receipt_claims_authenticated',
                'independent_custody_verified', 'restore_verified', 'deletion_authorised', 'training_eligible'}
            if (set(result) != flags | {'status', 'batches', 'rows', 'historical_original_catalog_matched', 'original_catalog_total', 'containment_profile'}
                    or result['status'] != 'EIGHT_OUTCOMES_STRUCTURAL_CHECK_NOT_CATALOG_ACCEPTANCE'
                    or result['containment_profile'] != CONTAINMENT_PROFILE
                    or type(result['batches']) is not int or result['batches'] != 8
                    or type(result['rows']) is not int or not 0 < result['rows'] <= 800
                    or result['historical_original_catalog_matched'] != 868 or result['original_catalog_total'] != 876
                    or any(result[k] is not False for k in flags)):
                raise ValueError('PRIVATE_REPORT_NOT_ACCEPTED')
            result['host_input_binding_sha256'] = hashlib.sha256(binding).hexdigest()
            publish(root / 'result.json', json.dumps(result, sort_keys=True).encode())
        summary: dict[str, Any] = dict(status=result['status'], stage=stage, raw_values_printed=False,
            private_result_is_not_catalog_acceptance=True, deletion_authorised=False, training_eligible=False)
        if args.mode == 'selftest':
            summary.update(synthetic_checks=result['checks'], autonomous_watchdog_verified=True,
                readonly_probes=result['readonly_probes'], containment_profile=CONTAINMENT_PROFILE)
        elif args.mode == 'private':
            summary.update(local_native_admission_verified=True, batches=result['batches'], rows=result['rows'])
        print(json.dumps(summary))
        return 0
    except Exception as error:
        safe = SAFE_ERROR_CODES | {'LOCAL_DOCKER_UNAVAILABLE', 'EXTERNAL_IMAGE_ID_AND_FRESH_NAME_REQUIRED',
            'WINDOWS_OWNER_PRIVATE_HOST_REQUIRED', 'NONADMIN_TOKEN_REQUIRED', 'PYTHON_3_13_9_REQUIRED', 'WINDOWS_REQUIRED',
            'EXPLICIT_PRIVATE_COMMISSIONING_REQUIRED', 'EXTERNAL_PUBLIC_KEY_FINGERPRINT_REQUIRED',
            'PRESERVATION_GENERATION_MISMATCH', 'ORIGINAL_GENERATION_PINS_REQUIRED', 'SYNTHETIC_CONTAINER_PROOF_MISSING',
            'CONTAINER_STOPPED_REVIEW_REQUIRED_NO_RETRY', 'CONTAINER_CLEANUP_NOT_ESTABLISHED_NO_RETRY'}
        safe |= {'SYNTHETIC_CONTAINER_CHECK_FAILED', 'SYNTHETIC_PROBE_SCHEMA_INVALID', 'CONTAINMENT_PROFILE_MISMATCH'}
        reason = ('SYNTHETIC_CONTAINER_CHECK_FAILED' if isinstance(error, SyntheticFailure) else
            str(error) if type(error) is ValueError and str(error) in safe else 'PRIVATE_ADMISSION_OR_IO_UNVERIFIED')
        print(json.dumps(dict(status='BLOCKED', code='PRIVATE_BRIDGE_REVIEW_REQUIRED_NO_RETRY', stage=stage,
            reason=reason,
            failed_checks=list(error.failed) if isinstance(error, SyntheticFailure) else [],
            readonly_probes=error.probes if isinstance(error, SyntheticFailure) else {},
            raw_error_printed=False, retry_authorised=False, deletion_authorised=False, training_eligible=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
