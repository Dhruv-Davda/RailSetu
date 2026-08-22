"""
Shared bootstrap for the API suites.

Every suite gets its OWN policy and account store, under a directory named after
the suite. Without that, two suites — or a suite and a running dev server —
share `backend/fixtures/policy` and quietly corrupt each other's fixtures: one
activates a threshold the next asserts against, and the failure looks like a
product bug rather than test bleed. Isolating the store is what makes the suites
independently runnable and re-runnable.

The stores are local, so no suite needs network or AWS credentials.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def bootstrap(suite: str) -> pathlib.Path:
    """Point this process at the repo and at a private, empty store."""
    sys.path.insert(0, str(ROOT / "backend"))
    os.chdir(ROOT / "backend")

    work = ROOT / "tests" / ".work" / suite
    shutil.rmtree(work, ignore_errors=True)
    (work / "policy").mkdir(parents=True, exist_ok=True)
    (work / "accounts").mkdir(parents=True, exist_ok=True)

    os.environ["RAILSETU_POLICY_STORE"] = "local"
    os.environ["RAILSETU_ACCOUNTS_STORE"] = "local"
    os.environ["RAILSETU_POLICY_LOCAL_ROOT"] = str(work / "policy")
    os.environ["RAILSETU_ACCOUNTS_LOCAL_ROOT"] = str(work / "accounts")
    os.environ.setdefault("RAILSETU_M3_ARTIFACTS_DIR",
                          str(ROOT / "railsetu-m3" / "artifacts"))
    return work


class Report:
    """Collects results and exits non-zero if anything failed."""

    def __init__(self, title: str):
        self.title = title
        self.passed: list[str] = []
        self.failed: list[str] = []

    def check(self, name: str, cond: object, detail: object = "") -> bool:
        ok = bool(cond)
        (self.passed if ok else self.failed).append(name)
        tail = f"  — {str(detail)[:110]}" if detail else ""
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{tail}")
        return ok

    def section(self, name: str) -> None:
        print(f"\n=== {name} ===")

    def finish(self) -> None:
        n = len(self.passed) + len(self.failed)
        print(f"\n{'=' * 62}\n{self.title}: {len(self.passed)}/{n} passed, "
              f"{len(self.failed)} failed")
        for f in self.failed:
            print("   -", f)
        sys.exit(1 if self.failed else 0)
