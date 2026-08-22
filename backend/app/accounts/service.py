"""
Sign-in, and resolving the person behind a request.

Signing in registers an address as the current user and records it, so that
every later change carries a real identity rather than a name typed into a
form each time. The address is the identity: it is what appears against a
policy version, and what the change history is read by.

Identity here is asserted by the caller, not proven — the platform records who
someone says they are so their edits are attributable. Anything that must
resist impersonation needs a credential check in front of this.
"""
from __future__ import annotations

import logging

from .store import (
    Account, AccountStore, display_name_for, is_valid_email, normalise, now_iso,
)

log = logging.getLogger("railsetu.accounts")


class AccountError(ValueError):
    """The address could not be accepted."""


class AccountService:
    def __init__(self, store: AccountStore):
        self.store = store

    def sign_in(self, email: str) -> Account:
        """Register an address as the current user, creating it if new."""
        e = normalise(email)
        if not is_valid_email(e):
            raise AccountError("enter a valid email address")

        existing = self.store.get(e)
        if existing:
            existing.last_seen_at = now_iso()
            existing.sign_in_count += 1
            self.store.put(existing)
            log.info("sign-in: %s (visit %d)", e, existing.sign_in_count)
            return existing

        account = Account(email=e, display_name=display_name_for(e),
                          created_at=now_iso(), last_seen_at=now_iso())
        self.store.put(account)
        log.info("sign-in: %s (new account)", e)
        return account

    def resolve(self, email: str | None) -> Account | None:
        """The account for an address, or None. Used to authorise a request."""
        e = normalise(email or "")
        if not e or not is_valid_email(e):
            return None
        return self.store.get(e)

    def touch_sign_out(self, email: str) -> None:
        acc = self.resolve(email)
        if acc:
            acc.last_seen_at = now_iso()
            self.store.put(acc)
            log.info("sign-out: %s", acc.email)

    def list_payload(self) -> dict:
        rows = self.store.list_accounts()
        return {"accounts": rows, "count": len(rows), "store": self.store.health()}
