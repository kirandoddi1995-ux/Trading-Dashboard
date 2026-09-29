"""One shared derivative eligibility boundary. Never grants trade authorization."""
from dataclasses import dataclass
from datetime import date

from derivative_contracts import FoundationError, resolve_contract, digest, stamp
from derivative_quotes import snapshot
from derivative_restrictions import restriction
from derivative_settlement import entry_check
from derivative_corporate_actions import validate_review


@dataclass(frozen=True)
class PreflightResult:
    eligible: bool
    reasons: tuple[str, ...]
    contract: object = None
    snapshot: dict | None = None
    ban_status: str = "UNKNOWN"

    def permits(self, *, now=None, governance_approved=False, manual_reviewed=False):
        if not self.eligible or now is None or not self.snapshot:
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
        return PreflightResult(True, (), contract, book, status)
    except (FoundationError, KeyError, TypeError, ValueError, ArithmeticError, AttributeError, OSError) as exc:
        reason = str(exc) if isinstance(exc, FoundationError) else "Invalid derivative preflight input"
        return PreflightResult(False, (reason,))
