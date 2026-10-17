# Research dataset boundary — offline foundation only

`research_dataset_boundary.py` imports only the standard library. It has no IO,
CLI, production adapters, fitting, replay engine or activation path. Supply typed
frozen plan/version/decision/label objects to `evaluate`; no dataset is read.

The API uses aware UTC-normalized observation times, selects the latest version
actually observed by each decision cutoff and checks a frozen hash of the full
caller-declared input prefix. Later revisions remain separate; they cannot replace
a decision's input. Event/version identities and strictly increasing receipt times
must be unambiguous. Hashes cover supplied payload fingerprints, not verified bytes.

This follows the time/version and canonical JSON conventions in
`research_replay_comparison.py`, `forward_revision_evidence.py` and
`research_integrity.py`, without importing them. It is not an adapter or substitute
for their full observation/spec/source verification. Prefix completeness itself
cannot be authenticated from this API's declared events.

Development is restricted to 2022–2024 metadata. Sealed 2025/2026 historical data
cannot be admitted through that partition. Explicit `PROSPECTIVE_VERSIONED_2026`
is separate and requires prospective, licence, provenance and preregistration
attestations plus source/study/document hashes. Caller claims do not distinguish
genuine prospective collection from retrospectively forged metadata: authentication
and existing prospective-cohort verification remain separate mandatory work.

Only matured, observed, hash-pinned reference-direction labels are calculated:
the sign of target reference price minus frozen entry reference price. Required
reference prices/quote counts must exist. These are not bid/ask executable quotes,
fills, costs, returns, target-before-stop labels or executable PnL. They must not
be silently mapped into the existing model-training target schema.

The frozen plan declares the complete expected decision scope. Missing decisions,
labels, immature horizons or absent attestations withhold the entire output dataset;
policy failures are classified separately. Ambiguous/malformed structures raise
fixed `ValueError` codes. Limits are 4,096 versions, 512 decisions/labels, 64 input
events per decision and an 8 MiB canonical manifest. Prices are finite, positive,
non-boolean and at most 1e12. These bounds are not statistical sample adequacy.

The report contains immutable canonical manifest bytes and SHA-256, including the
plan, all supplied versions, decisions, labels and classified missing/rejected
evidence. This is tamper-evident content binding, not authenticated custody or an
independent registration timestamp. Preserve returned bytes separately if required;
the module never stores them. `evaluated_at` is supplied, not a trusted live clock.

Every report keeps training eligibility, promotion, approval authority,
authenticated admission and executable PnL false, including structurally complete
outputs. Input kind is explicitly SYNTHETIC or CALLER_UNAUTHENTICATED; no synthetic
fixture is promoted to REAL. There is no authentication override switch.

Tests use generated 2022 toy reference prices, not market data. Partition tests
substitute calendar metadata only; they do not read sealed historical or capture
records. No existing gate, dataset, model, capture or operational resource changes.
