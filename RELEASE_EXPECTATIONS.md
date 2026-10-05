# Release expectations: owner configuration and diagnosis

These three names are case-sensitive **root-level TOML strings** in the live
release-branch app's Streamlit Settings / Secrets. They are not Actions variables
and not members of `[auth]`, `[positions]`, `[release]` or another section.

## Owner steps

1. Keep a private backup of the existing Secrets. Never upload it or paste it in
   chat, logs or the repository. Confirm you are editing the live app configured
   to deploy from `release`, not a separate development app.
2. Review/upload this complete file group to main, keeping tests under `tests/`.
   Wait for all exact-commit checks and successful release promotion. Do not
   change the fingerprint to the new value before that release is deployed.
3. In that app's Settings / Secrets, put each name exactly once, above the first
   `[section]` header. Use ordinary double-quoted strings and no surrounding
   whitespace inside their values. An example of placement only follows; do
   NOT save the placeholder text:

   ```toml
   EXPECTED_APP_BUILD = "<reviewed APP_BUILD>"
   RESILIENCE_POLICY_SHA256 = "<reviewed policy SHA-256>"
   EXPECTED_EQUITY_CODE_SHA256 = "<reviewed promoted code SHA-256>"

   [auth]
   # Keep your existing private authentication settings unchanged here.
   ```

   Moving lines above a section is correct. Indentation does not leave a TOML
   section; root keys must precede it. Remove misplaced copies of these three
   keys only, leaving unrelated credentials intact. Both hashes must be exactly
   64 lowercase hexadecimal characters. Obtain build from the reviewed app.py
   APP_BUILD assignment and public hashes from the reviewed release report or
   local `python equity_runtime_health.py`. Never derive expectations from the
   live display merely to make a mismatch disappear. The old v22.0 build does
   not match this release and would cause CONFIG_DRIFT once read successfully.
4. Save, then reboot the app and wait for the new startup. Root Streamlit secrets
   are also exposed as environment variables; a reboot matters if a prior value
   persists there. Do not change OIDC settings or loosen any safety control.
5. Settings / Release configuration (names and sources only), or the Equities
   runtime health expander, must show all three presence booleans true.
   In `release_configuration_sources`, each should show `status: VALID`,
   `source: STREAMLIT_ROOT`, `root_present: true`, `matches_actual: true` and
   `misplaced_sections: []`. `environment_present: true` is normal for root
   secrets. Diagnostics contain names, locations and booleans, never values.
6. If blocked, use the status rather than moving keys into arbitrary sections:
   - MISSING: exact root key and environment key absent. Check case, correct app
     and that Save succeeded. Section names, if any, identify misplaced keys.
   - INVALID_FORMAT: value is not a valid string/build/hash. Check privately.
   - SOURCE_CONFLICT: root and environment disagree. Reboot after saving and
     inspect any independently configured server environment privately.
   - SECRETS_READ_ERROR: the secrets store could not be read/enumerated. Check
     TOML parsing, duplicate definitions and Save/reboot. Exception text is
     intentionally hidden because it could quote credentials.
   - VALID with matches_actual false: configured value is stale/wrong or the
     wrong release is deployed. Verify the reviewed commit; do not self-default.
   If unresolved, share only status/source booleans and misplaced section names,
   not full Secrets, values, tokens or raw parsing errors.
7. Confirm configuration missing/drift blockers disappear. Calibration and other
   evidence blockers may legitimately remain. This repair grants no approvals,
   installs no database tables and starts no collector.

## Diagnosis and boundaries

The old helper already used root-level `st.secrets.get(name)`, but swallowed
read errors and converted arbitrary types to strings. The reported absence of
correct root keys is not explained by a required special section. The exact
hosted cause remains unverified; read failures, wrong/unsaved app configuration
or a misspelling must be distinguished, not assumed.

Settings and equity governance now share one resolver. Root values are preferred
to environment-only values, but invalid roots, read errors and conflicting
sources fail closed. Nested values are diagnosed, never silently accepted.
Non-equity legacy configuration behavior is unchanged. No real Secrets were read
or modified during implementation; all tests use synthetic values.

Official references:
- https://docs.streamlit.io/develop/concepts/connections/secrets-management
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
