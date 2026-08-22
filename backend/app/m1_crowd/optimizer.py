"""
M1.4 — Mitigation optimizer: which crowd-control measures to apply, and why.

The control space is small and fully enumerable: four independent crowd-
engineering levers = 16 combinations. So we do NOT guess — we run the real
pedestrian-flow simulation on every combination and rank the outcomes. With a
~100 ms run that is ~1.7 s for an exact answer, which is strictly better than
any heuristic (or any language model) picking from the same 16 options.

The ranking is lexicographic, in the order a station controller actually cares:

  1. crush points        — the lethal regime (LOS F). Non-negotiable, so first.
  2. peak density        — lower is safer even below the crush threshold;
                           LOS D (3.3) is meaningfully safer than LOS E (4.2).
  3. throughput          — people cleared in the horizon; more is better.
  4. intervention count  — each measure costs staff, gates and announcements.
                           Telling a controller to do four things when one
                           suffices is bad operational advice.

Points 3 and 4 only ever break ties between plans that are already safe, so the
optimizer never trades safety for convenience.

An LLM is used ONLY to write the operator-facing brief explaining the result
(see app/clients/gemini.py). It does not choose. The decision path stays
algorithmic, which is the claim the rest of the platform makes.
"""
from __future__ import annotations

import logging
from itertools import product

log = logging.getLogger("railsetu.optimizer")

# The four levers, in the order the UI lists them.
LEVERS = ["metered_holding", "open_fob", "stagger_release", "extra_exits"]

# Human phrasing for the policy-set objective, echoed back to the UI.
LEVER_OBJECTIVE_LABEL = {
    "crush_points": "crush points",
    "peak_density": "peak density",
    "throughput": "throughput",
    "measure_count": "measures used",
}

LEVER_LABEL = {
    "metered_holding": "Metered holding",
    "open_fob": "One-way / extra FOB lanes",
    "stagger_release": "Staggered release",
    "extra_exits": "Open extra exit gates",
}


# Each objective, expressed so that LOWER is always better. The ORDER they are
# applied in is not a constant — it is policy (intervention_priority), because
# "what do we optimise for" is a decision, not an implementation detail.
_OBJECTIVE_FN = {
    "crush_points": lambda s, n: s["crush_count"],
    "peak_density": lambda s, n: round(s["peak_density"], 2),
    "throughput": lambda s, n: -round(s["total_cleared"], 1),   # more is better
    "measure_count": lambda s, n: n,
}


def _score(summary: dict, n_active: int, order: list[str] | None = None) -> tuple:
    """Lexicographic objective — lower is better on every component.

    `order` comes from the active policy, so changing the policy genuinely
    changes which plan wins, not merely how the result is described.
    """
    if order is None:
        from app.policy.context import current
        order = current().intervention_priority
    return tuple(_OBJECTIVE_FN[o](summary, n_active) for o in order)


def search(run_fn, scenario_key: str, mitigation_cls) -> dict:
    """Evaluate all 16 mitigation combinations and rank them.

    `run_fn(scenario_key, mitigations)` is injected (app.main._run) so this
    module stays independent of the HTTP layer and is unit-testable.
    """
    from app.policy.context import current
    order = current().intervention_priority

    baseline = run_fn(scenario_key, None)
    bs = baseline["summary"]

    plans = []
    for combo in product([False, True], repeat=len(LEVERS)):
        active = [name for name, on in zip(LEVERS, combo) if on]
        mit = mitigation_cls(**dict(zip(LEVERS, combo)))
        res = run_fn(scenario_key, mit) if active else baseline
        s = res["summary"]

        top = (res.get("node_hotspots") or [None])[0]
        plans.append({
            "mitigations": dict(zip(LEVERS, combo)),
            "active": active,
            "labels": [LEVER_LABEL[a] for a in active],
            "n_active": len(active),
            "peak_density": s["peak_density"],
            "peak_los": s["peak_los"],
            "crush_count": s["crush_count"],
            "danger_count": s["danger_count"],
            "cleared": round(s["total_cleared"], 1),
            "worst_node": top["node"] if top else None,
            "score": _score(s, len(active), order),
        })

    plans.sort(key=lambda p: p["score"])
    best = plans[0]

    # What each single lever achieves on its own — this is what exposes the
    # non-obvious result that extra capacity can RELOCATE a crush rather than
    # remove it, which is the most instructive output of the whole module.
    singles = [p for p in plans if p["n_active"] == 1]
    singles.sort(key=lambda p: p["score"])

    peak_drop = bs["peak_density"] - best["peak_density"]
    return {
        "scenario": scenario_key,
        "baseline": {
            "peak_density": bs["peak_density"],
            "peak_los": bs["peak_los"],
            "crush_count": bs["crush_count"],
            "danger_count": bs["danger_count"],
            "cleared": round(bs["total_cleared"], 1),
            "worst_node": (baseline.get("node_hotspots") or [{}])[0].get("node"),
        },
        "recommended": best,
        "impact": {
            "peak_before": bs["peak_density"],
            "peak_after": best["peak_density"],
            "peak_reduction_pct": round(peak_drop / bs["peak_density"] * 100, 1)
            if bs["peak_density"] else 0.0,
            "crush_before": bs["crush_count"],
            "crush_after": best["crush_count"],
            "cleared_before": round(bs["total_cleared"], 1),
            "cleared_after": best["cleared"],
        },
        "ranking": plans[:8],
        "single_levers": singles,
        "evaluated": len(plans),
        "method": "exhaustive simulation over all 16 mitigation combinations",
        "objective": order,
        "objective_labels": [LEVER_OBJECTIVE_LABEL.get(o, o) for o in order],
    }
