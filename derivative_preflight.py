"""One shared derivative eligibility boundary. Never grants trade authorization."""
from dataclasses import dataclass
from datetime import date

from derivative_contracts import FoundationError, resolve_contract, digest, stamp
from derivative_quotes import snapshot
from derivative_restrictions import restriction


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
             ban=None, action="ENTRY", exposure=None, extra_required=()):
    try:
        contract = resolve_contract(master, rules, now=now)
        book = snapshot(contract, quotes, now=now, generation=generation,
                        quantity=quantity, side=side, policy=policy, extra_required=extra_required)
        status = restriction(contract, ban, trading_date=date.fromisoformat(rules["session_date"]),
                             now=now, action=action, exposure=exposure)
        book = dict(book, action=action, ban_source_hash=ban.sha256 if ban else None,
                    ban_trading_date=ban.trading_date.isoformat() if ban else None)
        book["expires_at"] = min(book["expires_at"], stamp(rules["effective_until"]))
        book.pop("snapshot_id")
        book["snapshot_id"] = digest(book)
        return PreflightResult(True, (), contract, book, status)
    except (FoundationError, KeyError, TypeError, ValueError, ArithmeticError, AttributeError, OSError) as exc:
        reason = str(exc) if isinstance(exc, FoundationError) else "Invalid derivative preflight input"
        return PreflightResult(False, (reason,))
