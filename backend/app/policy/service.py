"""
The policy register: browse the library, preview a change, activate it,
inspect what changed.

The library holds several documents. Each is amended on its own, but the
platform runs on all of them composed together — so previewing a change to one
means composing the library WITH that draft substituted in and re-running the
models. That is what makes the preview trustworthy: it is the real rule-set the
platform would operate under, not the one document in isolation.

The four verbs:

  preview(key, draft)   Runs the real models under the library as it stands and
                        under the library with this draft substituted. Nothing
                        is written and nothing is activated.

  activate(key, draft)  Writes an immutable version of THAT document (text,
                        author, reason, diff, measured effect) and recomposes
                        the rules in force.

  rollback(key, id)     Re-activates an earlier text as a NEW version. History
                        is never rewritten.

  library()             What documents exist, and where each one stands.

The crowd simulation is injected (`run_crowd`) rather than imported, so this
module does not depend on the HTTP layer.
"""
from __future__ import annotations

import logging

from app.config import Settings

from . import context as ctx
from . import diff as D
from . import documents as docs
from . import location as loc
from .schema import Policy, PolicyError, compose, parse_document
from .store import PolicyStore, PolicyVersion, make_id, now_iso

log = logging.getLogger("railsetu.policy.service")

GENESIS_TITLE = "Initial text"


class PolicyConflict(PolicyError):
    """A revert could not be applied cleanly; the caller is told exactly why."""

    def __init__(self, message: str, conflicts: list, seq: int):
        super().__init__(message)
        self.conflicts = conflicts
        self.seq = seq


class PolicyService:
    def __init__(self, store: PolicyStore, settings: Settings):
        self.store = store
        self.s = settings

    # ---- lifecycle ------------------------------------------------------

    def bootstrap(self) -> Policy:
        """Load every document's active text, seeding any that are new."""
        # Documents added through the UI live in the register, not in code, so
        # they have to be put back on the registry before anything reads it.
        try:
            for row in self.store.get_registry():
                docs.register(docs.PolicyDocument(
                    key=row["key"], title=row["title"], summary=row.get("summary", ""),
                    # `owner` was the earlier field name — read either, so a
                    # register written before the rename still loads.
                    department=row.get("department") or row.get("owner") or "Unassigned",
                    sections=(),
                    default_yaml=row.get("initial_text", ""),
                    format=row.get("format", "text")))
        except Exception as exc:  # noqa: BLE001 — never block startup
            log.error("could not load added policy documents: %s", exc)

        raws: dict[str, str] = {}
        for d in docs.all_documents():
            head = None
            try:
                head = self.store.head(d.key)
            except Exception as exc:  # noqa: BLE001 — never block startup
                log.error("could not read the register for %s: %s", d.key, exc)
            if head:
                raws[d.key] = head.yaml
                continue
            version = PolicyVersion(
                id=make_id(d.default_yaml, 1), seq=1,
                title=GENESIS_TITLE,
                description=("The text this document shipped with. Recorded so every "
                             "later amendment has a baseline to be compared against."),
                author_name="RailSetu", author_email="system@railsetu",
                created_at=now_iso(), yaml=d.default_yaml, parent_id=None,
                diff_stats={"added": len(d.default_yaml.splitlines()), "removed": 0,
                            "changed": len(d.default_yaml.splitlines())},
                changes=[], impact={},
            )
            try:
                self.store.put_version(d.key, version)
            except Exception as exc:  # noqa: BLE001
                log.error("could not seed %s: %s", d.key, exc)
            raws[d.key] = d.default_yaml

        ctx.set_active_library(raws)
        return ctx.get_active()

    # ---- reading --------------------------------------------------------

    def library_payload(self) -> dict:
        """Every document, with where it currently stands. No document text."""
        out = []
        for meta in docs.catalogue():
            head = None
            try:
                head = self.store.head(meta["key"])
            except Exception as exc:  # noqa: BLE001
                log.warning("register unreadable for %s: %s", meta["key"], exc)
            try:
                versions = len(self.store.list_versions(meta["key"]))
            except Exception:  # noqa: BLE001
                versions = 0
            out.append({
                **meta,
                "versions": versions,
                "current": head.summary() if head else None,
            })
        return {"documents": out, "count": len(out), "store": self.store.health()}

    def document_payload(self, key: str) -> dict | None:
        doc = docs.get(key)
        if doc is None:
            return None
        head = self.store.head(key)
        return {
            "document": {**next(m for m in docs.catalogue() if m["key"] == key)},
            "text": head.yaml if head else doc.default_yaml,
            "version": head.summary() if head else None,
            "store": self.store.health(),
        }

    def default_text(self, key: str) -> str | None:
        doc = docs.get(key)
        return doc.default_yaml if doc else None

    def history_payload(self, key: str, limit: int = 50) -> dict | None:
        if docs.get(key) is None:
            return None
        rows = self.store.list_versions(key)[:limit]
        return {"key": key, "versions": rows, "count": len(rows)}

    def version_payload(self, key: str, version_id: str) -> dict | None:
        if docs.get(key) is None:
            return None
        v = self.store.get_version(key, version_id)
        if not v:
            return None
        parent = self.store.get_version(key, v.parent_id) if v.parent_id else None
        old = parent.yaml if parent else ""
        return {
            "key": key,
            "version": v.summary(),
            "text": v.yaml,
            "parent_text": old,
            "hunks": D.unified_hunks(old, v.yaml),
            "changes": v.changes,
        }

    # ---- adding a document ----------------------------------------------

    MAX_TITLE = 80
    MAX_SUMMARY = 160
    MAX_DEPARTMENT = 80

    def create_document(self, *, title: str, summary: str, department: str,
                        fmt: str, text: str, author_name: str, author_email: str,
                        location: dict | None = None,
                        client_ip: str | None = None) -> dict:
        """Add a written standard to the library, with its first version."""
        title = (title or "").strip()
        summary = (summary or "").strip()
        department = (department or "").strip()
        fmt = (fmt or "").strip().lower()

        if not title:
            raise PolicyError("a title is required")
        if len(title) > self.MAX_TITLE:
            raise PolicyError(f"the title must be {self.MAX_TITLE} characters or fewer")
        if len(summary) > self.MAX_SUMMARY:
            raise PolicyError(f"the summary must be {self.MAX_SUMMARY} characters or fewer")
        if len(department) > self.MAX_DEPARTMENT:
            raise PolicyError(
                f"the department must be {self.MAX_DEPARTMENT} characters or fewer")
        if fmt not in docs.ADDABLE_FORMATS:
            raise PolicyError(
                "a new policy can be a Markdown or a plain-text standard. The "
                "structured rule-sets cannot be added here: each one is read by a "
                "specific model, so a new one would have nothing reading it.")
        if not (text or "").strip():
            raise PolicyError("the document is empty")

        key = docs.slugify(title)
        if not key:
            raise PolicyError("the title must contain some letters or numbers")
        if docs.get(key) is not None:
            raise PolicyError(f"a policy named '{title}' already exists")

        doc = docs.PolicyDocument(key=key, title=title, summary=summary,
                                  department=department or "Unassigned", sections=(),
                                  default_yaml=text, format=fmt)
        rows = [r for r in self.store.get_registry() if r.get("key") != key]
        rows.append({"key": key, "title": title, "summary": summary,
                     "department": doc.department, "format": fmt, "initial_text": text,
                     "created_by": author_email, "created_at": now_iso()})
        self.store.put_registry(rows)
        docs.register(doc)

        version = PolicyVersion(
            id=make_id(text, 1), seq=1,
            title="Initial text",
            description=(f"'{title}' added to the policy library by "
                         f"{author_name}."),
            author_name=author_name, author_email=author_email,
            created_at=now_iso(), yaml=text, parent_id=None,
            diff_stats={"added": len(text.splitlines()), "removed": 0,
                        "changed": len(text.splitlines())},
            changes=[], impact={},
            location=loc.normalise(location, client_ip),
        )
        self.store.put_version(key, version)

        # A written standard changes nothing the models compute, so the rules in
        # force are unaffected — but keep the library in the context in step.
        ctx.set_active_library(self._library_raws())
        log.info("policy document added: %s ('%s') by %s from %s",
                 key, title, author_email, loc.describe(version.location))
        return {"created": True, "key": key,
                "document": next(m for m in docs.catalogue() if m["key"] == key),
                "version": version.summary()}

    # ---- validate / preview --------------------------------------------

    def validate_payload(self, key: str, draft: str) -> dict:
        try:
            parse_document(key, draft)
            return {"valid": True, "errors": []}
        except PolicyError as exc:
            return {"valid": False, "errors": str(exc).split("; ")}

    def _library_raws(self) -> dict[str, str]:
        return dict(ctx.active_library())

    def preview(self, key: str, draft: str, run_crowd) -> dict:
        """The library as it stands vs the library with this draft in it."""
        doc = docs.get(key)
        if doc is None:
            return {"valid": False, "errors": [f"unknown policy document '{key}'"]}

        current_text = self._library_raws().get(key, doc.default_yaml)
        base = {
            "hunks": D.unified_hunks(current_text, draft),
            "stats": D.diff_stats(current_text, draft),
            "structured": doc.structured,
        }
        try:
            parse_document(key, draft)
        except PolicyError as exc:
            return {**base, "valid": False, "errors": str(exc).split("; ")}

        if not doc.structured:
            # A written standard governs people, not the models. Reporting a
            # measured "effect" here would be an invention.
            return {**base, "valid": True, "errors": [], "changes": [],
                    "narrative": True}

        import yaml as _y
        changes = D.semantic_changes(_y.safe_load(current_text) or {},
                                     _y.safe_load(draft) or {})
        deep = any(c["path"].split("[")[0].startswith("intervention_priority")
                   for c in changes)

        raws = self._library_raws()
        before = self._probe(run_crowd, deep=deep)
        raws[key] = draft
        with ctx.use_policy(compose(raws)):
            after = self._probe(run_crowd, deep=deep)

        return {
            **base, "valid": True, "errors": [], "narrative": False,
            "changes": [{**c, "text": D.describe_change(c)} for c in changes],
            "before": before, "after": after,
            "deltas": _deltas(before, after),
            "ran_optimizer": deep,
        }

    def _probe(self, run_crowd, *, deep: bool) -> dict:
        """Measure the platform's headline outputs under the rules in force."""
        out: dict = {}
        try:
            crowd = run_crowd(self.s.policy_preview_crowd_scenario, None)
            cs = crowd["summary"]
            out["crowd"] = {
                "scenario": crowd.get("title") or self.s.policy_preview_crowd_scenario,
                "peak_density": cs["peak_density"], "peak_los": cs["peak_los"],
                "crush_count": cs["crush_count"], "danger_count": cs["danger_count"],
                "cleared": round(cs["total_cleared"], 1),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("preview crowd probe failed: %s", exc)
            out["crowd"] = {"error": str(exc)}

        try:
            from app.m2_delay import service as corridor
            res = corridor.simulate_payload(self.s.policy_preview_corridor_scenario, True)
            if res:
                out["corridor"] = {
                    "scenario": res["title"],
                    "delay_before_min": res["baseline"]["total_delay_min"],
                    "delay_after_min": res["optimized"]["total_delay_min"],
                    "saved_min": res["impact"]["saved_min"],
                    "saved_pct": res["impact"]["saved_pct"],
                    "affected": res["optimized"]["affected"],
                    "moves": res["impact"]["actions_count"],
                }
        except Exception as exc:  # noqa: BLE001
            log.warning("preview corridor probe failed: %s", exc)
            out["corridor"] = {"error": str(exc)}

        try:
            from app.m6_kavach import service as protection
            cov = protection.coverage_payload()["summary"]
            corr = protection.correlation_payload()["headline"]
            out["protection"] = {
                "weighted_coverage_pct": cov["traffic_weighted_coverage_pct"],
                "equipped": cov["status_counts"]["equipped"],
                "partial": cov["status_counts"]["partial"],
                "none": cov["status_counts"]["none"],
                "risk_share_pct": corr["risk_share_pct"],
                "corridors_at_risk": corr["n_corridors"],
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("preview protection probe failed: %s", exc)
            out["protection"] = {"error": str(exc)}

        if deep:
            try:
                from app.m1_crowd.optimizer import search
                from app.main import Mitigations
                r = search(run_crowd, self.s.policy_preview_crowd_scenario, Mitigations)
                out["recommendation"] = {
                    "measures": r["recommended"]["labels"] or ["No intervention"],
                    "peak_after": r["recommended"]["peak_density"],
                    "crush_after": r["recommended"]["crush_count"],
                    "objective": r["objective"],
                }
            except Exception as exc:  # noqa: BLE001
                log.warning("preview optimizer probe failed: %s", exc)
        return out

    # ---- activate / rollback -------------------------------------------

    def activate(self, key: str, draft: str, *, title: str, description: str,
                 author_name: str, author_email: str, run_crowd,
                 rollback_of: str | None = None, reverts: str | None = None,
                 location: dict | None = None, client_ip: str | None = None) -> dict:
        doc = docs.get(key)
        if doc is None:
            raise PolicyError(f"unknown policy document '{key}'")
        title = (title or "").strip()
        if not title:
            raise PolicyError("a change title is required")
        if not (author_name or "").strip() or not (author_email or "").strip():
            raise PolicyError("a signed-in author is required")

        parse_document(key, draft)                 # raises on invalid
        head = self.store.head(key)
        old = head.yaml if head else ""
        if head and old == draft:
            raise PolicyError("no changes to activate — this document is identical "
                              "to the version already in force")

        changes: list = []
        impact: dict = {}
        if doc.structured:
            import yaml as _y
            changes = D.semantic_changes(_y.safe_load(old) if old else {},
                                         _y.safe_load(draft) or {})
            raws = self._library_raws()
            before = self._probe(run_crowd, deep=True)
            raws[key] = draft
            with ctx.use_policy(compose(raws)):
                after = self._probe(run_crowd, deep=True)
            impact = {"before": before, "after": after,
                      "deltas": _deltas(before, after)}

        seq = self.store.next_seq(key)
        version = PolicyVersion(
            id=make_id(draft, seq), seq=seq,
            title=title, description=(description or "").strip(),
            author_name=author_name.strip(), author_email=author_email.strip(),
            created_at=now_iso(), yaml=draft,
            parent_id=head.id if head else None,
            diff_stats=D.diff_stats(old, draft),
            changes=[{**c, "text": D.describe_change(c)} for c in changes],
            impact=impact, rollback_of=rollback_of, reverts=reverts,
            location=loc.normalise(location, client_ip),
        )
        self.store.put_version(key, version)

        raws = self._library_raws()
        raws[key] = draft
        ctx.set_active_library(raws)
        log.info("%s activated: %s '%s' by %s from %s (%d rule change(s))",
                 key, version.id, title, author_email,
                 loc.describe(version.location), len(changes))
        return {"activated": True, "key": key, "version": version.summary(),
                "impact": impact, "changes": version.changes}

    def revert_change(self, key: str, version_id: str, *, author_name: str,
                      author_email: str, run_crowd,
                      location: dict | None = None,
                      client_ip: str | None = None) -> dict:
        """Back out ONE earlier change, keeping everything done since.

        This is `git revert`, not `git reset`: the diff that version introduced
        is applied in reverse to the text currently in force. Where a later
        version has already edited the same lines the reverse patch cannot be
        applied safely, and the conflict is reported rather than guessed at.
        """
        target = self.store.get_version(key, version_id)
        if not target:
            raise PolicyError(f"unknown version '{version_id}' for '{key}'")
        if not target.parent_id:
            raise PolicyError("this is the document's initial text — there is no "
                              "earlier change to back out. Use restore instead.")
        parent = self.store.get_version(key, target.parent_id)
        if not parent:
            raise PolicyError("the version this change was made against is missing "
                              "from the register, so it cannot be backed out")

        current = self._library_raws().get(key) or (self.store.head(key).yaml)
        new_text, conflicts = D.reverse_patch(parent.yaml, target.yaml, current)
        if new_text is None:
            # Distinguish "someone else has since edited these lines" from
            # "this change is simply not in force any more" — the second is not
            # a conflict, it is a no-op, and saying "conflict" would send the
            # reader hunting for a clash that does not exist.
            if D.reverse_patch(target.yaml, parent.yaml, current)[0] is not None:
                raise PolicyError(
                    f"v{target.seq} has already been backed out — the document "
                    f"in force no longer contains that change")
            raise PolicyConflict(
                f"cannot back out v{target.seq} automatically", conflicts, target.seq)
        if new_text == current:
            raise PolicyError(f"v{target.seq} has already been backed out — the "
                              f"document in force does not contain that change")

        return self.activate(
            key, new_text,
            title=f"Revert v{target.seq} — {target.title}",
            description=(f"Backs out the change introduced by v{target.seq} "
                         f"({target.id}), keeping every later amendment in place."),
            author_name=author_name, author_email=author_email,
            run_crowd=run_crowd, reverts=version_id,
            location=location, client_ip=client_ip,
        )

    def rollback(self, key: str, version_id: str, *, author_name: str,
                 author_email: str, run_crowd,
                 location: dict | None = None, client_ip: str | None = None) -> dict:
        target = self.store.get_version(key, version_id)
        if not target:
            raise PolicyError(f"unknown version '{version_id}' for '{key}'")
        head = self.store.head(key)
        if head and head.id == version_id:
            raise PolicyError("that version is already in force")
        return self.activate(
            key, target.yaml,
            title=f"Roll back to v{target.seq} — {target.title}",
            description=(f"Reverts this document to the text activated as v{target.seq} "
                         f"({target.id}) on {target.created_at}."),
            author_name=author_name, author_email=author_email,
            run_crowd=run_crowd, rollback_of=version_id,
            location=location, client_ip=client_ip,
        )


# --------------------------------------------------------------------------

def _num_delta(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        d = round(b - a, 2)
        return {"before": a, "after": b, "delta": d, "changed": abs(d) > 1e-9}
    return {"before": a, "after": b, "delta": None, "changed": a != b}


def _deltas(before: dict, after: dict) -> dict:
    out: dict = {}
    for group in ("crowd", "corridor", "protection"):
        b, a = before.get(group) or {}, after.get(group) or {}
        if "error" in b or "error" in a:
            continue
        out[group] = {k: _num_delta(b.get(k), a.get(k)) for k in a if k != "scenario"}
    if "recommendation" in before or "recommendation" in after:
        b = (before.get("recommendation") or {}).get("measures")
        a = (after.get("recommendation") or {}).get("measures")
        out["recommendation"] = {"before": b, "after": a, "changed": b != a}
    return out
