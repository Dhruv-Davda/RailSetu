"""
Unified line diff, shaped for a GitHub-style review view.

Two outputs, for two audiences:

  * `unified_hunks()` — the literal line-by-line diff, grouped into hunks with
    context, old/new line numbers, and a +/-/context marker per row. This is
    what the change-log renders.

  * `semantic_changes()` — what actually CHANGED, in the document's own terms:
    "crowd_safety.density_bands.crush_above: 5.0 → 4.5". A line diff tells you
    a character moved; this tells a duty officer which rule was amended. A
    policy register needs both — the text for the record, the semantics for
    the reader.
"""
from __future__ import annotations

import difflib
from typing import Any

CONTEXT = 3


def unified_hunks(old: str, new: str, context: int = CONTEXT) -> list[dict]:
    """Group a line diff into hunks: [{old_start,new_start,lines:[{type,old,new,text}]}]."""
    a = old.splitlines()
    b = new.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    opcodes = sm.get_opcodes()

    # Rows for the whole file, then cut to hunks around the changed ones.
    rows: list[dict] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"type": "context", "old": i1 + k + 1,
                             "new": j1 + k + 1, "text": a[i1 + k]})
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"type": "del", "old": k + 1, "new": None, "text": a[k]})
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append({"type": "add", "old": None, "new": k + 1, "text": b[k]})
        else:  # replace -> deletions then insertions, the way git renders it
            for k in range(i1, i2):
                rows.append({"type": "del", "old": k + 1, "new": None, "text": a[k]})
            for k in range(j1, j2):
                rows.append({"type": "add", "old": None, "new": k + 1, "text": b[k]})

    changed = [i for i, r in enumerate(rows) if r["type"] != "context"]
    if not changed:
        return []

    # Merge changed rows that are within 2*context of each other into one hunk.
    spans: list[list[int]] = []
    for i in changed:
        lo, hi = max(0, i - context), min(len(rows) - 1, i + context)
        if spans and lo <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])

    hunks = []
    for lo, hi in spans:
        block = rows[lo:hi + 1]
        old_no = next((r["old"] for r in block if r["old"] is not None), 1)
        new_no = next((r["new"] for r in block if r["new"] is not None), 1)
        hunks.append({
            "old_start": old_no,
            "new_start": new_no,
            "old_lines": sum(1 for r in block if r["type"] in ("context", "del")),
            "new_lines": sum(1 for r in block if r["type"] in ("context", "add")),
            "lines": block,
        })
    return hunks


def diff_stats(old: str, new: str) -> dict:
    a, b = old.splitlines(), new.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    added = removed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            removed += i2 - i1
        if tag in ("insert", "replace"):
            added += j2 - j1
    return {"added": added, "removed": removed, "changed": added + removed}


# --------------------------------------------------------------------------
# semantic diff — what rule actually changed
# --------------------------------------------------------------------------

def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """dict/list tree -> {'a.b.c': value}. Lists keep their index in the path."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        # A list of scalars is an ordered rule (e.g. the optimizer objective),
        # so its ORDER is the meaning — index it rather than treating it as a set.
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def semantic_changes(old_data: Any, new_data: Any) -> list[dict]:
    """[{path, kind, before, after}] — the rules that were amended."""
    a, b = _flatten(old_data or {}), _flatten(new_data or {})
    out: list[dict] = []
    for path in sorted(set(a) | set(b)):
        av, bv = a.get(path, None), b.get(path, None)
        if path not in b:
            out.append({"path": path, "kind": "removed", "before": av, "after": None})
        elif path not in a:
            out.append({"path": path, "kind": "added", "before": None, "after": bv})
        elif av != bv:
            out.append({"path": path, "kind": "changed", "before": av, "after": bv})
    return out


def describe_change(c: dict) -> str:
    """One-line human phrasing of a semantic change."""
    p = c["path"]
    if c["kind"] == "changed":
        return f"{p}: {c['before']} → {c['after']}"
    if c["kind"] == "added":
        return f"{p}: added ({c['after']})"
    return f"{p}: removed (was {c['before']})"


# --------------------------------------------------------------------------
# reverting one change, the way `git revert` does
# --------------------------------------------------------------------------
#
# Restoring an old version and reverting a single change are different acts,
# and a register needs both:
#
#   restore    make the document exactly as it was at version N. Everything
#              done since is discarded.
#   revert     back out only what version N introduced, and keep every later
#              change. This is `git revert`, and it is usually what someone
#              means by "that change was wrong".
#
# Revert is implemented as a reverse patch: take the diff that version N
# introduced (parent -> N) and apply it backwards to the text currently in
# force. Each changed block is matched against the current text WITH one line
# of surrounding context, which anchors pure deletions and makes an accidental
# match on a similar-looking line far less likely.
#
# If a block cannot be found — because a later version already edited those
# same lines — that hunk is reported as a conflict rather than guessed at. A
# register that silently mangles a rule is worse than one that says it cannot
# do this automatically.

ANCHOR = 1


def _block(lines, lo, hi):
    return lines[max(0, lo):hi]


def _find_unique(haystack: list[str], needle: list[str]) -> tuple[int, int]:
    """(index, count) of `needle` inside `haystack`, as a contiguous block."""
    if not needle:
        return -1, 0
    first, n, hits = needle[0], len(needle), []
    for i in range(len(haystack) - n + 1):
        if haystack[i] == first and haystack[i:i + n] == needle:
            hits.append(i)
            if len(hits) > 1:
                break
    return (hits[0] if hits else -1), len(hits)


def reverse_patch(parent: str, version: str, current: str):
    """Back the change (parent -> version) out of `current`.

    Returns (new_text | None, conflicts). new_text is None when any hunk could
    not be applied; `conflicts` describes each one in the document's own terms.
    """
    a, b = parent.splitlines(), version.splitlines()
    cur = current.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]

    if not ops:
        return current, [{"reason": "this version changed nothing"}]

    conflicts, applied = [], 0
    # Work back to front so earlier indices stay valid as we splice.
    for tag, i1, i2, j1, j2 in reversed(ops):
        lead = _block(b, j1 - ANCHOR, j1)
        trail = _block(b, j2, j2 + ANCHOR)
        find = lead + b[j1:j2] + trail
        repl = lead + a[i1:i2] + trail

        idx, count = _find_unique(cur, find)
        if count == 1:
            cur[idx:idx + len(find)] = repl
            applied += 1
            continue

        # Retry without context — a later edit may have touched a neighbouring
        # line without touching this block itself.
        idx, count = _find_unique(cur, b[j1:j2])
        if count == 1 and b[j1:j2]:
            cur[idx:idx + (j2 - j1)] = a[i1:i2]
            applied += 1
            continue

        conflicts.append({
            "expected": b[j1:j2] or a[i1:i2],
            "would_become": a[i1:i2],
            "reason": ("already changed by a later version"
                       if count == 0 else "matches in more than one place"),
        })

    if conflicts:
        return None, conflicts
    text = "\n".join(cur)
    if version.endswith("\n") or parent.endswith("\n"):
        text += "\n"
    return text, []
