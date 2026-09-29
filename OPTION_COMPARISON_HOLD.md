# Option valuation authority: interim fail-closed repair

## Severity and operational change

This is a material decision-quality defect, not evidence that a specific past
trade was incorrect. Convenient defaults can cause false acceptance; mismatched
conventions can cause false rejection. A legacy pass was not the whole trade
approval (other gates still applied), but those other gates do not establish
correct Greek valuation. Historical impact requires replay of genuine recorded
inputs; do not infer the number or profitability of affected trades.

The legacy surface's `production_valid` field is no longer consumed by the app's
option selector. The legacy function remains unchanged for existing research
consumers; its UI is explicitly labelled as legacy research diagnostics.

ALL new CE/PE entries and rolls, both index and stock options, are now ineligible
at the shared derivative preflight boundary. When other foundation checks pass,
the reason/status is NOT_COMPARABLE, not a claim of measured Greek mismatch.
This intentionally means no actionable option-entry approvals in this release.
Quick ideas and normal recommendations both use that boundary. Rechecking
`permits()` also rejects previously retained eligible option-entry results.

Futures remain on their original path. EXIT review is not subject to the new
hold and retains its official exposure, quote and lifecycle safeguards. No
positions are liquidated. Settlement monitoring, alerts and research displays
are unchanged. Invalid quotes or existing restriction failures still report
their original reasons before the comparison hold is considered.

There is no environment variable, manual override or payload status that lifts
this hold. It cannot be lifted by `production_valid=true` or a research/shadow
`CONSISTENT` result. No permissions, SQL, hosted configuration or broker orders
are changed by this code.

## Why the shadow comparator is not the replacement yet

Four useful diagnostic names are not sufficient to grant production authority.
The present comparator takes caller-declared conventions/tolerances and model
inputs; it does not authenticate those declarations or establish an empirically
reviewed operating envelope. Bid/ask IV is conditional on its model inputs.
Finite sampling of Greek ranges is not a rigorous extremum guarantee. It is
appropriate for tests and shadow observations, not a drop-in approval gate.

Before replacing the hold:

1. Verify endpoint-specific provider Greek conventions (spot/forward delta,
   IV units, theta/day count, vega bump, per-unit/lot) and calculation freshness.
   A fresh packet does not prove freshly recomputed Greeks. Unknown ->
   NOT_COMPARABLE, never a guess based on the value's magnitude.
2. Supply versioned point-in-time rates, dividend/carry treatment, contract and
   adjustment lineage, actual expiry and aligned executable books from trusted
   adapters. Unknown inputs cannot become 6%, zero or date-plus-15:30 defaults.
3. Review an explicit comparison policy: numerical conditioning, near-expiry
   exclusions, uncertainty bounds, absolute/relative/monetary-impact tolerances.
   Validate the operating region against recorded inputs without fitting limits
   simply to make disagreements disappear. Provisional limits must be labelled.
4. Bind a typed production comparison to the exact contract, quote generation,
   timestamps, expiry, input hashes and policy version. Recompute/invalidate on
   input change. Never accept an arbitrary dictionary claiming CONSISTENT.
5. Prove the common gate is required by every actionable options path. Test
   NOT_COMPARABLE, UNSTABLE and MISMATCH block, and CONSISTENT only satisfies this
   one prerequisite. All other gates, manual review and official regulatory
   evidence requirements must remain independent and mandatory.

The broader volatility engine stays research-only during and after this work
unless separately promoted through an evidence-backed reviewed change.

## Local review scope

- app.py: remove legacy validity wiring/rejection; label diagnostics honestly.
- derivative_preflight.py: central CE/PE entry/roll hold and cached-result guard.
- tests/test_derivative_foundations.py: update intentional eligibility semantics;
  retain book assertions and test futures, exits, overrides and cached results.
- tests/test_volatility_research.py: assert isolation against the new boundary.
- tests/test_audit_fixes.py: keep isolated sizing/governance tests working with
  the new preflight result field; these explicit test doubles are not approvals.
- VOLATILITY_RESEARCH.md: correct the previous description of live authority.
- this document.

No new module or dependency. The existing release manifest already covers both
changed runtime files; the source fingerprint nevertheless changes. Update only
EXPECTED_EQUITY_CODE_SHA256 to the supplied value after uploading reviewed files.
