# Release packaging and recovery gate

Run `python package_release.py` with the application's requirements installed.
The existing quality and rollback workflows already invoke this command; the
gate is inside the builder, so manual builds receive the same checks.

The explicit FILES list now specifies release entry points and non-code assets,
not the complete Python dependency inventory. All local imports are recursively
included, including function-local and conditional imports, package initializers,
relative imports and literal import_module/__import__ calls. New ordinary local
dependencies no longer need to be added to a second list. Real secrets, databases,
virtual environments and arbitrary data files are not swept into the archive.

The builder writes a temporary ZIP, verifies every manifest member/hash, extracts
it to an unrelated temporary directory, and imports app in a fresh isolated Python
process. That child does not inherit credentials, PYTHONPATH, user-site packages
or the user's home settings. Before adding the extracted application to the import
path, the probe initializes installed Matplotlib's font manager with a fresh,
temporary font cache. This permits system font discovery (such as fc-list), with
network access still blocked. The subprocess ban is then installed before any
application import; there is no permanent utility allowlist. Missing/broken
Matplotlib still fails verification. Application network and subprocess calls
are forbidden. A
completion marker, zero exit code and timeout are enforced. No application/auth
function is mocked. Only after success does the staged ZIP replace the old ZIP.
The embedded manifest is authoritative; the convenience sidecar is written after
publication. A failed build exits nonzero and preserves the previous artifact;
never upload a leftover ZIP after ignoring a failed builder command.

This is a source distribution, not an offline wheelhouse/Python distribution.
Install requirements.txt (and requirements-archive.txt for archive maintenance)
in the restore environment, provision real secrets separately, and apply reviewed
database migrations separately. The smoke test is credential-free import proof,
not proof of broker access, authenticated UI flows or a live disaster recovery.

Computed/dynamic plugin names and non-Python resources still require explicit
FILES entries and feature-specific tests. Static discovery cannot infer arbitrary
runtime paths. Do not use source-relative access to files outside the release.
Do not add credential-bearing scripts or data as runtime dependencies. Review the
generated manifest before upload. The current hard gate runs with the builder's
installed third-party environment; CI installs the pinned requirements first.
