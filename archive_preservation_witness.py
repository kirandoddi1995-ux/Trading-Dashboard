"""Dedicated preservation-v1 signatures over owner observations, not custody facts.

Only the inventory's local-path gate is reused; no transport, implicit keys or trust-on-first-use. Canonical JSON
here is this bounded Python JSON profile, not a claim of RFC 8785 conformance.
Key helpers accept explicit bytes; only the confirmed CLI performs local file IO.
Private output permissions on Windows remain an owner responsibility. Partial
exclusive writes are retained after failure; never automatically retry or erase.
Revocation and key rotation are NOT implemented: the caller must supply a currently
approved external key/head. Verification does not discover revocation status.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import getpass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import NoReturn, Sequence, TypeAlias, cast
import warnings

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from archive_preservation_inventory import check_path as check_local_path
from archive_preservation_inventory import open_read as open_local_read
from archive_preservation_inventory import MAX_FILE_ID

JsonValue: TypeAlias = None | bool | int | float | str | list['JsonValue'] | dict[str, 'JsonValue']
JsonObject: TypeAlias = dict[str, JsonValue]
SCOPE = 'preservation-v1'
DOMAIN = b'archive-preservation-witness\x00preservation-v1\x00'
MAX_BYTES = 65536
MAX_KEY_BYTES = 16384
MAX_GENERATION = 2**63 - 1
# Additive v1 numeric-profile extension; existing canonical bytes stay unchanged.
# This is not RFC8785/I-JSON and must not pass through IEEE754-only JSON tooling.
# Native identity width and anti-rollback generation bounds are separate contracts.
MAX_JSON_INTEGER = MAX_FILE_ID
MIN_PASSPHRASE_BYTES = 16
MAX_PASSPHRASE_BYTES = 1024
PROJECT_ROOT = Path(__file__).parent
PUBLIC_ERROR_CODES = (
    'JSON_STRUCTURE_BOUND', 'JSON_STRING_BOUND', 'JSON_INTEGER_BOUND',
    'NONFINITE_JSON_FORBIDDEN', 'STRING_JSON_KEYS_REQUIRED', 'JSON_TYPE_REQUIRED',
    'JSON_SIZE_BOUND', 'INVALID_JSON', 'DUPLICATE_JSON_KEY', 'JSON_OBJECT_REQUIRED',
    'CANONICAL_JSON_REQUIRED', 'GENERATION_REQUIRED', 'EXTERNAL_DIGEST_REQUIRED',
    'FIRST_GENERATION_HAS_NO_PREDECESSOR', 'EXACT_PREDECESSOR_GENERATION_REQUIRED',
    'PASSPHRASE_BYTES_BOUND', 'ENCRYPTED_PKCS8_REQUIRED', 'ENCRYPTED_KEY_UNAVAILABLE',
    'DEDICATED_ED25519_KEY_REQUIRED', 'LITERAL_ENROLLMENT_REQUIRED',
    'EXPLICIT_FIRST_GENERATION_ENROLLMENT_REQUIRED', 'ENROLLMENT_ONLY_FOR_FIRST_GENERATION',
    'EXACT_WITNESS_SCHEMA_REQUIRED', 'EXACT_PREDECESSOR_REQUIRED',
    'EXTERNAL_ED25519_PUBLIC_KEY_REQUIRED', 'EXTERNAL_LATEST_ANCHOR_MISMATCH',
    'SIGNATURE_NOT_VERIFIED', 'TRUSTED_PUBLIC_KEY_FINGERPRINT_MISMATCH',
    'PRIVATE_PATH_OUTSIDE_SOURCE_REQUIRED', 'LOCAL_NATIVE_PRIVATE_PATH_REQUIRED',
    'PRIVATE_PARENT_OR_INPUT_MISSING', 'PRIVATE_LINK_REJECTED', 'OUTPUT_ALREADY_EXISTS',
    'PRIVATE_REGULAR_FILE_REQUIRED', 'PRIVATE_DIRECTORY_REQUIRED',
    'PRIVATE_INPUT_SIZE_BOUND', 'PRIVATE_INPUT_CHANGED', 'HIDDEN_PASSPHRASE_TTY_REQUIRED',
    'PASSPHRASES_DIFFER', 'INVALID_ARGUMENTS', 'EXPLICIT_PATH_REQUIRED',
    'DISTINCT_KEY_OUTPUTS_REQUIRED', 'RECOVERED_KEY_NOT_EXTERNALLY_TRUSTED',
    'SIGNING_KEY_NOT_EXTERNALLY_TRUSTED',
)


class WitnessError(ValueError):
    """Fixed codes only; never include keys, passwords, paths or observations."""


@dataclass(frozen=True)
class VerifiedObservation:
    generation: int
    digest: str
    predecessor_generation: int | None
    predecessor_digest: str | None
    observation_json: bytes
    scope: str = field(default=SCOPE, init=False)
    signature_verified: bool = field(default=True, init=False)
    custody_verified: bool = field(default=False, init=False)
    logical_restore_verified: bool = field(default=False, init=False)
    delete_authorised: bool = field(default=False, init=False)
    training_eligible: bool = field(default=False, init=False)
    approval_authority: bool = field(default=False, init=False)
    revocation_checked: bool = field(default=False, init=False)


def _validate(value: object, depth: int, budget: list[int]) -> None:
    budget[0] += 1
    if depth > 16 or budget[0] > 10000:
        raise WitnessError('JSON_STRUCTURE_BOUND')
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is str:
        if len(cast(str, value)) > MAX_BYTES:
            raise WitnessError('JSON_STRING_BOUND')
    elif kind is int:
        if abs(cast(int, value)) > MAX_JSON_INTEGER:
            raise WitnessError('JSON_INTEGER_BOUND')
    elif kind is float:
        if not math.isfinite(cast(float, value)):
            raise WitnessError('NONFINITE_JSON_FORBIDDEN')
    elif kind is list:
        for item in cast(list[object], value):
            _validate(item, depth + 1, budget)
    elif kind is dict:
        for key, item in cast(dict[object, object], value).items():
            if type(key) is not str:
                raise WitnessError('STRING_JSON_KEYS_REQUIRED')
            _validate(key, depth + 1, budget)
            _validate(item, depth + 1, budget)
    else:
        raise WitnessError('JSON_TYPE_REQUIRED')


def canonical_json(value: JsonValue) -> bytes:
    _validate(value, 0, [0])
    # Each scalar is bounded above; iterencode avoids allocating the potentially
    # enormous aggregate encoding of repeated bounded strings before checking it.
    raw = bytearray()
    try:
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False)
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode('utf-8')
            if len(raw) + len(encoded) > MAX_BYTES:
                raise WitnessError('JSON_SIZE_BOUND')
            raw.extend(encoded)
    except WitnessError:
        raise
    except (ValueError, UnicodeError):
        raise WitnessError('INVALID_JSON') from None
    return bytes(raw)


def _unique(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise WitnessError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _nonfinite(_: str) -> NoReturn:
    raise WitnessError('NONFINITE_JSON_FORBIDDEN')


def _parse(raw: bytes, *, require_canonical: bool) -> JsonObject:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise WitnessError('JSON_SIZE_BOUND')
    try:
        value: object = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                                   parse_constant=_nonfinite)
    except WitnessError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise WitnessError('INVALID_JSON') from None
    if type(value) is not dict:
        raise WitnessError('JSON_OBJECT_REQUIRED')
    result = cast(JsonObject, value)
    encoded = canonical_json(result)
    if require_canonical and encoded != raw:
        raise WitnessError('CANONICAL_JSON_REQUIRED')
    return result


def _generation(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_GENERATION:
        raise WitnessError('GENERATION_REQUIRED')
    return value


def _digest(value: object) -> str:
    if type(value) is not str or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise WitnessError('EXTERNAL_DIGEST_REQUIRED')
    return value


def _predecessor(generation: int, previous: object, digest: object) -> JsonValue:
    if generation == 1:
        if previous is not None or digest is not None:
            raise WitnessError('FIRST_GENERATION_HAS_NO_PREDECESSOR')
        return None
    if _generation(previous) != generation - 1:
        raise WitnessError('EXACT_PREDECESSOR_GENERATION_REQUIRED')
    return {'generation': generation - 1, 'digest': _digest(digest)}


def _password(password: bytes) -> None:
    if type(password) is not bytes or not MIN_PASSPHRASE_BYTES <= len(password) <= MAX_PASSPHRASE_BYTES:
        raise WitnessError('PASSPHRASE_BYTES_BOUND')


def _load_key(encrypted_pkcs8: bytes, password: bytes) -> Ed25519PrivateKey:
    _password(password)
    if type(encrypted_pkcs8) is not bytes or not 0 < len(encrypted_pkcs8) <= MAX_KEY_BYTES:
        raise WitnessError('ENCRYPTED_PKCS8_REQUIRED')
    try:
        key = serialization.load_der_private_key(encrypted_pkcs8, password=password)
    except (ValueError, TypeError):
        raise WitnessError('ENCRYPTED_KEY_UNAVAILABLE') from None
    if not isinstance(key, Ed25519PrivateKey):
        raise WitnessError('DEDICATED_ED25519_KEY_REQUIRED')
    return key


def generate_encrypted_pkcs8(password: bytes) -> bytes:
    """Explicit key generation only. Never called during preview/import/verify."""
    _password(password)
    return Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password))


def public_key_from_encrypted_pkcs8(encrypted_pkcs8: bytes, password: bytes) -> bytes:
    return _load_key(encrypted_pkcs8, password).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def signing_payload(observation: JsonObject, generation: int,
                    predecessor_generation: int | None, predecessor_digest: str | None,
                    enroll_first_generation: bool) -> JsonObject:
    """Pure full-envelope preflight; no key read, prompt, signature or publication."""
    current = _generation(generation)
    if type(enroll_first_generation) is not bool:
        raise WitnessError('LITERAL_ENROLLMENT_REQUIRED')
    if current == 1 and not enroll_first_generation:
        raise WitnessError('EXPLICIT_FIRST_GENERATION_ENROLLMENT_REQUIRED')
    if current != 1 and enroll_first_generation:
        raise WitnessError('ENROLLMENT_ONLY_FOR_FIRST_GENERATION')
    if type(observation) is not dict:
        raise WitnessError('JSON_OBJECT_REQUIRED')
    payload: JsonObject = dict(scope=SCOPE, generation=current,
        predecessor=_predecessor(current, predecessor_generation, predecessor_digest),
        observation=observation)
    # A fixed-width Ed25519 hex signature makes this an exact envelope size check.
    canonical_json({'payload': payload, 'signature': '0' * 128})
    return payload


def sign_observation(encrypted_pkcs8: bytes, password: bytes, observation: JsonObject, *,
                     generation: int, predecessor_generation: int | None,
                     predecessor_digest: str | None,
                     enroll_first_generation: bool = False) -> bytes:
    """Sign caller claims only; predecessor identity is explicitly supplied.

    This byte API does not authenticate the supplied predecessor or observation.
    The CLI additionally verifies the prior witness against external anchors.
    """
    payload = signing_payload(observation, generation, predecessor_generation,
                              predecessor_digest, enroll_first_generation)
    message = canonical_json(payload)
    signature = _load_key(encrypted_pkcs8, password).sign(DOMAIN + message)
    return canonical_json({'payload': payload, 'signature': signature.hex()})


def _decode(witness: bytes) -> tuple[JsonObject, bytes]:
    envelope = _parse(witness, require_canonical=True)
    if set(envelope) != {'payload', 'signature'}:
        raise WitnessError('EXACT_WITNESS_SCHEMA_REQUIRED')
    raw_payload, signature = envelope['payload'], envelope['signature']
    if type(raw_payload) is not dict or type(signature) is not str:
        raise WitnessError('EXACT_WITNESS_SCHEMA_REQUIRED')
    payload = raw_payload
    if (set(payload) != {'scope', 'generation', 'predecessor', 'observation'}
            or payload['scope'] != SCOPE or type(payload['observation']) is not dict
            or re.fullmatch('[a-f0-9]{128}', signature) is None):
        raise WitnessError('EXACT_WITNESS_SCHEMA_REQUIRED')
    generation = _generation(payload['generation'])
    prior = payload['predecessor']
    if generation == 1:
        _predecessor(generation, None, prior)
    else:
        if type(prior) is not dict or set(prior) != {'generation', 'digest'}:
            raise WitnessError('EXACT_PREDECESSOR_REQUIRED')
        _predecessor(generation, prior['generation'], prior['digest'])
    return payload, bytes.fromhex(signature)


def witness_digest(witness: bytes) -> str:
    """Content identity only, NOT signature verification or an external anchor."""
    _decode(witness)
    return hashlib.sha256(witness).hexdigest()


def verify_observation(witness: bytes, trusted_public_key: bytes, *,
                       latest_generation: int, latest_digest: str,
                       trusted_public_key_sha256: str | None = None) -> VerifiedObservation:
    """Require independently retained key AND latest generation/digest anchors.

    Validating one head does not validate all prior observations or custody.
    Never obtain these anchors from the envelope being verified.
    """
    expected_generation, expected_digest = _generation(latest_generation), _digest(latest_digest)
    if type(trusted_public_key) is not bytes or len(trusted_public_key) != 32:
        raise WitnessError('EXTERNAL_ED25519_PUBLIC_KEY_REQUIRED')
    _public_fingerprint(trusted_public_key, trusted_public_key_sha256)
    payload, signature = _decode(witness)
    actual = hashlib.sha256(witness).hexdigest()
    if payload['generation'] != expected_generation or not hmac.compare_digest(actual, expected_digest):
        raise WitnessError('EXTERNAL_LATEST_ANCHOR_MISMATCH')
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            signature, DOMAIN + canonical_json(payload))
    except (InvalidSignature, ValueError):
        raise WitnessError('SIGNATURE_NOT_VERIFIED') from None
    prior = payload['predecessor']
    previous = cast(JsonObject, prior) if prior is not None else None
    return VerifiedObservation(expected_generation, actual,
        cast(int, previous['generation']) if previous is not None else None,
        cast(str, previous['digest']) if previous is not None else None,
        canonical_json(payload['observation']))


def _public_fingerprint(public: bytes, expected: str | None) -> None:
    """Optional SECOND external gate, never a replacement for the trusted key."""
    if expected is not None and not hmac.compare_digest(hashlib.sha256(public).hexdigest(), _digest(expected)):
        raise WitnessError('TRUSTED_PUBLIC_KEY_FINGERPRINT_MISMATCH')


def _private_path(path: Path, *, output: bool = False) -> None:
    if (not path.is_absolute() or str(path).startswith(('\\\\', '//'))
            or '..' in path.parts or path == PROJECT_ROOT or path.is_relative_to(PROJECT_ROOT)):
        raise WitnessError('PRIVATE_PATH_OUTSIDE_SOURCE_REQUIRED')
    try:
        # Shared gate checks GetDriveTypeW BEFORE metadata on Windows. This rejects
        # mapped network drives as well as UNC/device/relative and linked paths.
        check_local_path(path)
    except (ValueError, OSError):
        raise WitnessError('LOCAL_NATIVE_PRIVATE_PATH_REQUIRED') from None
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if output and part == path:
                continue
            raise WitnessError('PRIVATE_PARENT_OR_INPUT_MISSING') from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise WitnessError('PRIVATE_LINK_REJECTED')
        if part == path:
            if output:
                raise WitnessError('OUTPUT_ALREADY_EXISTS')
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise WitnessError('PRIVATE_REGULAR_FILE_REQUIRED')
        elif not stat.S_ISDIR(info.st_mode):
            raise WitnessError('PRIVATE_DIRECTORY_REQUIRED')


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read(path: Path, maximum: int) -> bytes:
    _private_path(path)
    before = path.lstat()
    if not 0 < before.st_size <= maximum:
        raise WitnessError('PRIVATE_INPUT_SIZE_BOUND')
    with os.fdopen(open_local_read(path), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _file_identity(opened) != _file_identity(before):
            raise WitnessError('PRIVATE_INPUT_CHANGED')
        raw = stream.read(maximum + 1)
        _private_path(path)
        after, named = os.fstat(stream.fileno()), path.lstat()
        if (len(raw) != opened.st_size or _file_identity(after) != _file_identity(opened)
                or _file_identity(named) != _file_identity(opened)
                or opened.st_ctime_ns != after.st_ctime_ns or before.st_ctime_ns != named.st_ctime_ns):
            raise WitnessError('PRIVATE_INPUT_CHANGED')
        return raw


def _publish(path: Path, raw: bytes) -> None:
    _private_path(path, output=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _hidden_password(*, confirmation: bool) -> bytes:
    if not sys.stdin.isatty():
        raise WitnessError('HIDDEN_PASSPHRASE_TTY_REQUIRED')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            first = getpass.getpass('Dedicated key passphrase (16-1024 UTF-8 bytes; hidden; no pasted command lines): ')
            if confirmation and first != getpass.getpass('Repeat dedicated passphrase (hidden): '):
                raise WitnessError('PASSPHRASES_DIFFER')
        except getpass.GetPassWarning:
            raise WitnessError('HIDDEN_PASSPHRASE_TTY_REQUIRED') from None
    try:
        password = first.encode('utf-8')
    except UnicodeError:
        raise WitnessError('PASSPHRASE_BYTES_BOUND') from None
    _password(password)
    return password


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise WitnessError('INVALID_ARGUMENTS')


def _required(value: str | None) -> Path:
    if not value:
        raise WitnessError('EXPLICIT_PATH_REQUIRED')
    return Path(value)


def _emit_public_preview() -> None:
    """Literal public contract; no arguments, globals, input reads or secret flow.

    The policy values are deliberately projected here rather than flowing from
    credential-named validation constants into a logging sink. Regression tests
    bind this literal contract to enforcement so duplication cannot silently drift.
    This is not a sanitizer or a CodeQL suppression.
    """
    print('{"status":"PREVIEW","input_reads":0,"writes":0,"credential_reads":0,'
          '"unlock_input_policy":{"minimum_utf8_bytes":16,"maximum_utf8_bytes":1024,'
          '"encoding":"UTF-8","single_command_only":true},'
          '"custody_verified":false,"delete_authorised":false,"training_eligible":false}')


def _public_error_code(error: WitnessError) -> str:
    """Return a member of the public literal vocabulary, never received error text."""
    if len(error.args) == 1 and type(error.args[0]) is str:
        for label in PUBLIC_ERROR_CODES:
            if error.args[0] == label:
                return label
    return 'LOCAL_WITNESS_OPERATION_NOT_ESTABLISHED'


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument('--mode', choices=('preview', 'keygen', 'check-key', 'check-observation', 'sign', 'verify'), default='preview')
        parser.add_argument('--confirm-run', action='store_true')
        for name in ('key-output', 'public-output', 'key', 'observation', 'output',
                     'witness', 'trusted-public-key', 'previous-witness', 'latest-digest',
                     'trusted-public-key-sha256'):
            parser.add_argument('--' + name)
        parser.add_argument('--generation', type=int)
        parser.add_argument('--latest-generation', type=int)
        parser.add_argument('--confirm-first-generation-enrollment', action='store_true')
        args = parser.parse_args(argv)
        if not args.confirm_run or args.mode == 'preview':
            _emit_public_preview()
            return 0
        if args.mode == 'check-observation':
            observation = _parse(_read(_required(args.observation), MAX_BYTES), require_canonical=False)
            signing_payload(observation, _generation(args.generation), args.latest_generation,
                            args.latest_digest, args.confirm_first_generation_enrollment)
            result: dict[str, object] = dict(status='OBSERVATION_SIGNING_PREFLIGHT_PASSED_NOT_SIGNATURE',
                input_reads=1, credential_reads=0, writes=0, signature_verified=False)
        elif args.mode == 'keygen':
            key_out, public_out = _required(args.key_output), _required(args.public_output)
            _private_path(key_out, output=True)
            _private_path(public_out, output=True)
            if key_out == public_out:
                raise WitnessError('DISTINCT_KEY_OUTPUTS_REQUIRED')
            password = _hidden_password(confirmation=True)
            key = generate_encrypted_pkcs8(password)
            public = public_key_from_encrypted_pkcs8(key, password)
            _publish(key_out, key)
            _publish(public_out, public)
            result = dict(status='DEDICATED_KEY_CREATED_NOT_TRUST_ENROLLED', writes=2)
        elif args.mode == 'check-key':
            fingerprint = _digest(args.trusted_public_key_sha256)
            public = _read(_required(args.trusted_public_key), 32)
            _public_fingerprint(public, fingerprint)
            key = _read(_required(args.key), MAX_KEY_BYTES)
            password = _hidden_password(confirmation=False)
            if not hmac.compare_digest(public_key_from_encrypted_pkcs8(key, password), public):
                raise WitnessError('RECOVERED_KEY_NOT_EXTERNALLY_TRUSTED')
            result = dict(status='KEY_RECOVERY_VERIFIED_NOT_ARCHIVE',
                          key_recovery_verified=True, archive_recovery_verified=False, writes=0)
        elif args.mode == 'sign':
            generation = _generation(args.generation)
            fingerprint = _digest(args.trusted_public_key_sha256)
            first = args.confirm_first_generation_enrollment
            if first != (generation == 1):
                raise WitnessError('EXPLICIT_FIRST_GENERATION_ENROLLMENT_REQUIRED')
            if generation == 1:
                if any(x is not None for x in (args.latest_generation, args.latest_digest, args.previous_witness)):
                    raise WitnessError('FIRST_GENERATION_HAS_NO_PREDECESSOR')
                previous_generation, previous_digest = None, None
            else:
                previous_generation, previous_digest = _generation(args.latest_generation), _digest(args.latest_digest)
                _predecessor(generation, previous_generation, previous_digest)
            output = _required(args.output)
            _private_path(output, output=True)
            public = _read(_required(args.trusted_public_key), 32)
            _public_fingerprint(public, fingerprint)
            if generation > 1:
                verify_observation(_read(_required(args.previous_witness), MAX_BYTES), public,
                    latest_generation=cast(int, previous_generation), latest_digest=cast(str, previous_digest),
                    trusted_public_key_sha256=fingerprint)
            observation = _parse(_read(_required(args.observation), MAX_BYTES), require_canonical=False)
            signing_payload(observation, generation, previous_generation, previous_digest, first)
            key = _read(_required(args.key), MAX_KEY_BYTES)
            password = _hidden_password(confirmation=False)
            if not hmac.compare_digest(public_key_from_encrypted_pkcs8(key, password), public):
                raise WitnessError('SIGNING_KEY_NOT_EXTERNALLY_TRUSTED')
            witness = sign_observation(key, password, observation, generation=generation,
                predecessor_generation=previous_generation, predecessor_digest=previous_digest,
                enroll_first_generation=first)
            _publish(output, witness)
            result = dict(status='OWNER_OBSERVATION_SIGNED_NOT_CUSTODY', generation=generation,
                          digest=witness_digest(witness), writes=1)
        else:
            generation, digest = _generation(args.latest_generation), _digest(args.latest_digest)
            fingerprint = _digest(args.trusted_public_key_sha256)
            checked = verify_observation(_read(_required(args.witness), MAX_BYTES),
                _read(_required(args.trusted_public_key), 32), latest_generation=generation, latest_digest=digest,
                trusted_public_key_sha256=fingerprint)
            result = dict(status='PRESERVATION_SIGNATURE_VERIFIED_NOT_CUSTODY',
                          generation=checked.generation, digest=checked.digest, writes=0)
        result.update(custody_verified=False, logical_restore_verified=False,
                      delete_authorised=False, training_eligible=False, approval_authority=False,
                      network_requests=0, revocation_checked=False)
        print(json.dumps(result, sort_keys=True))
        return 0
    except WitnessError as error:
        code = _public_error_code(error)
    except Exception:
        code = 'LOCAL_WITNESS_OPERATION_NOT_ESTABLISHED'
    print(json.dumps(dict(status='BLOCKED', code=code, raw_error_printed=False,
                         custody_verified=False, delete_authorised=False, training_eligible=False)))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
