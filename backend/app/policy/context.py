"""
Which policy is in force, right here, right now.

This is the seam that makes "preview before activation" possible at all.

The simulators do not take a policy argument threaded down through every call
— that would mean touching a dozen signatures across three modules to answer
one question. Instead they ask `current()` for the rules in force, and a
preview simply runs the SAME code under a different answer:

    with use_policy(draft):
        preview = run_everything()      # draft rules, nothing persisted

That gives an exact preview: it is not a parallel "what-if" implementation
that might drift from the real one, it is the real simulation with one value
swapped. A contextvar (not a global) is used so an override is scoped to the
block that set it and cannot leak into a concurrent request.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar

from .schema import Policy, compose, default_policy

log = logging.getLogger("railsetu.policy")

# The activated rules — every document in the library, composed. This is what
# the platform runs on when nothing is overriding.
_active: Policy | None = None

# The text of each document as activated, keyed by document. Kept so a preview
# can recompose the library with one document swapped without re-reading the
# store, and so the editor can show what is actually in force.
_library: dict[str, str] = {}

# A scoped override, set only for the duration of a preview.
_override: ContextVar[Policy | None] = ContextVar("policy_override", default=None)


def current() -> Policy:
    """The policy in force for this call. Never returns None."""
    o = _override.get()
    if o is not None:
        return o
    global _active
    if _active is None:
        _active = default_policy()
    return _active


def set_active(policy: Policy) -> None:
    """Install a composed rule-set as the platform-wide active one."""
    global _active
    _active = policy
    log.info("rules in force: crush_above=%s, headway=%s, objective=%s",
             policy.crush_threshold, policy.headway_min,
             ",".join(policy.intervention_priority))


def set_active_library(raws: dict) -> Policy:
    """Recompose the rules in force from every document's active text."""
    global _library
    _library = dict(raws)
    policy = compose(_library)
    set_active(policy)
    return policy


def active_library() -> dict:
    """Each document's active text, keyed by document."""
    return dict(_library)


def get_active() -> Policy:
    """The activated policy, ignoring any preview override."""
    global _active
    if _active is None:
        _active = default_policy()
    return _active


@contextmanager
def use_policy(policy: Policy):
    """Run a block under `policy` without activating it."""
    token = _override.set(policy)
    try:
        yield policy
    finally:
        _override.reset(token)
