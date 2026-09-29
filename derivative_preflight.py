"""One shared derivative eligibility boundary. Never grants trade authorization."""
from dataclasses import dataclass
from datetime import date

from derivative_contracts import FoundationError, resolve_contract, digest, stamp
from derivative_quotes import snapshot
from derivative_restrictions import restriction
from derivative_settlement import entry_check
from derivative_corporate_actions import validate_review


# Deliberately not configurable from environment, manual confirmation or research
# payloads. Replacing this hold requires a reviewed production validator, not a
# switch that grants authority to a shadow comparison's CONSISTENT result.
OPTION_COMPARISON_HOLD = (
    "NOT_COMPARABLE: option entry/roll approval is unavailable until provider "
    "Greek conventions, sourced valuation inputs and a production comparison "
    "policy are verified. Legacy surface and research results are not approval evidence."
)


def option_comparison_hold(contract, action):
    return contract.kind in {"CE", "PE"} and action in {"ENTRY", "ROLL"}


@dataclass(frozen=True)
class PreflightResult:
    eligible: bool
    reasons: tuple[str, ...]
    contract: object = None
    snapshot: dict | None = None
    ban_status: str = "UNKNOWN"
    greek_status: str = "NOT_APPLICABLE"

    def permits(self, *, now=None, governance_approved=False, manual_reviewed=False):
        if not self.eligible or now is None or not self.snapshot:
            return False
        # Also reject an old eligible option-entry result retained by a caller.
        if self.contract is None or option_comparison_hold(self.contract, self.snapshot.get("action", "ENTRY")):
            return False
        try:
            fresh = stamp(self.snapshot["validated_at"]) <= stamp(now) < stamp(self.snapshot["expires_at"])
        except (FoundationError, KeyError):
            return False
        return fresh and governance_approved is True and manual_reviewed is True


def evaluate(master, rules, quotes, *, now, generation, quantity, side, policy,
             ban=None, action="ENTRY", exposure=None, extra_required=(), lifecycle=None):
    try:
        contract = resolve_contract(master, rules, now=now)
        book = snapshot(contract, quotes, now=now, generation=generation,
                        quantity=quantity, side=side, policy=policy, extra_required=extra_required)
        adjustment = validate_review(contract, (lifecycle or {}).get('adjustment_review'), book['quotes'], now=now)
        if action in {'ENTRY','ROLL'}:
            entry_check(contract,lifecycle,now=now)
        status = restriction(contract, ban, trading_date=date.fromisoformat(rules["session_date"]),
                             now=now, action=action, exposure=exposure)
        book = dict(book, action=action, adjustment_event=adjustment,
                    lifecycle_hash=digest(lifecycle), ban_source_hash=ban.sha256 if ban else None,
                    ban_trading_date=ban.trading_date.isoformat() if ban else None)
        book["expires_at"] = min(book["expires_at"], stamp(rules["effective_until"]))
        if action in {'ENTRY','ROLL'}:
            book['expires_at'] = min(book['expires_at'],stamp(lifecycle['valid_until']),
                                     stamp(lifecycle['adjustment_review']['valid_until']))
            if contract.settlement == 'PHYSICAL':
                book['expires_at'] = min(book['expires_at'],stamp(lifecycle['broker_policy']['entry_cutoff']),
                                         stamp(lifecycle['broker_policy']['valid_until']))
        book.pop("snapshot_id")
        book["snapshot_id"] = digest(book)
        if option_comparison_hold(contract, action):
            # Retain the validated book for diagnostics, never actionable approval.
            # Existing quote, lifecycle and restriction failures still run first.
            return PreflightResult(False, (OPTION_COMPARISON_HOLD,), contract, book,
                                   status, "NOT_COMPARABLE")
        return PreflightResult(True, (), contract, book, status)
    except (FoundationError, KeyError, TypeError, ValueError, ArithmeticError, AttributeError, OSError) as exc:
        reason = str(exc) if isinstance(exc, FoundationError) else "Invalid derivative preflight input"
        return PreflightResult(False, (reason,))
