"""
M2.2 + M2.3 — Delay propagation and rescheduling, as one section-by-section
dispatch simulation.

The corridor is a single track per direction with overtaking only possible at
stations (which have loop lines). We move trains through each section in turn,
dispatching them in an order set by the *policy*:

  * "fcfs"     — first-come-first-served (what happens with no active control):
                 a slow train scheduled ahead blocks every faster train behind it,
                 because they cannot overtake mid-section. Delays cascade.
  * "priority" — the optimizer: when a higher-priority train is ready close behind,
                 dispatch it first and HOLD the slower train at the station (a loop
                 move = an overtake). This is the rescheduling decision.

A disruption adds delay to one train at one station; the simulation propagates the
knock-on. Comparing fcfs-vs-priority on the SAME disruption gives the headline:
delay-minutes saved by rescheduling. Delays are measured against each train's
free-run (unobstructed) schedule, so that reference cancels in the comparison.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import network as net

OVERTAKE_WINDOW = 12.0   # max minutes we'll hold a slow train for a not-yet-ready faster one


@dataclass
class TrainResult:
    no: str
    name: str
    type: str
    priority: int
    timeline: list = field(default_factory=list)   # [{station, code, arr, dep, stop, held}]
    arrival_min: float = 0.0
    delay_min: float = 0.0


@dataclass
class SimResult:
    policy: str
    trains: dict                # no -> TrainResult
    actions: list               # rescheduling actions taken (priority policy only)
    total_delay_min: float
    weighted_delay_min: float
    affected: int               # trains delayed > 1 min


def _free_run(trains, stations, secs):
    """Each train's unobstructed arrival at the final station (the planned time)."""
    out = {}
    for t in trains:
        clock = t["dep_min"]
        for i, sec in enumerate(secs):
            clock += net.running_time_min(sec["km"], t["speed"])
            code = stations[i + 1]["code"]
            if i + 1 < len(stations) - 1 and net.stops_at(t, code):
                clock += net.STOP_DWELL_MIN
        out[t["no"]] = clock
    return out


def simulate(policy: str, disruption: dict | None = None) -> SimResult:
    stations = net.STATIONS
    secs = net.sections()
    trains = net.trains_with_priority()
    n = len(stations)
    by_no = {t["no"]: t for t in trains}

    # Per-train, per-station arrays.
    arrive = {t["no"]: [None] * n for t in trains}     # arrival at station s
    ready = {t["no"]: [None] * n for t in trains}       # earliest it can leave station s
    enter = {t["no"]: [None] * n for t in trains}       # actual section-entry time at station s
    held = {t["no"]: [0.0] * n for t in trains}         # minutes held at station s for an overtake
    actions = []

    def disruption_extra(no, s):
        if (disruption and disruption.get("train") == no
                and disruption.get("station_index") == s and "delay_min" in disruption):
            return float(disruption["delay_min"])
        return 0.0

    # Station 0 (origin): arrival = scheduled departure (+ disruption if injected here).
    # A `dep_override` models a train that is already running late from an upstream
    # section and so enters the corridor out of its planned slot (e.g. a slow
    # passenger train now pathed ahead of the express fleet).
    dep_override = (disruption or {}).get("dep_override")
    for t in trains:
        d0 = t["dep_min"]
        if dep_override and disruption["train"] == t["no"]:
            d0 = float(dep_override)
        d0 += disruption_extra(t["no"], 0)
        arrive[t["no"]][0] = d0
        ready[t["no"]][0] = d0

    # March section by section down the corridor.
    for s, sec in enumerate(secs):
        # Compute readiness to depart station s for every train.
        for t in trains:
            no = t["no"]
            if s > 0:
                code = stations[s]["code"]
                dwell = net.STOP_DWELL_MIN if net.stops_at(t, code) else 0.0
                ready[no][s] = arrive[no][s] + dwell + disruption_extra(no, s)

        queue = sorted((t for t in trains), key=lambda t: ready[t["no"]][s])
        remaining = list(queue)
        prev_enter = prev_exit = float("-inf")

        while remaining:
            gate = max(ready[remaining[0]["no"]][s], prev_enter + net.HEADWAY_MIN)
            if policy == "priority":
                # Dispatch fastest-first (priority breaks ties). On a no-overtake
                # section this is the SPT rule: letting the faster train go first
                # minimises total downstream delay (it would otherwise be throttled
                # behind a slower train it cannot pass). We only hold ready trains
                # to wait for a not-yet-ready train if that train is meaningfully
                # FASTER — otherwise the hold costs more than the overtake saves,
                # so the optimizer never inflates total delay.
                def val(t):
                    return (t["speed"], t["priority"])
                cands = [t for t in remaining if ready[t["no"]][s] <= gate + 1e-6]
                soon = [t for t in remaining
                        if gate < ready[t["no"]][s] <= gate + OVERTAKE_WINDOW]
                best_cand = max(cands, key=val) if cands else None
                best_soon = max(soon, key=val) if soon else None
                if best_soon and (not best_cand or best_soon["speed"] > best_cand["speed"] + 5):
                    chosen = best_soon
                    entry = ready[chosen["no"]][s]
                else:
                    chosen = best_cand
                    entry = gate
            else:  # fcfs
                chosen = remaining[0]
                entry = gate

            no = chosen["no"]
            entry = max(entry, ready[no][s], prev_enter + net.HEADWAY_MIN)
            runtime = net.running_time_min(sec["km"], chosen["speed"])
            exit_t = max(entry + runtime, prev_exit + net.HEADWAY_MIN)  # no overtaking mid-section

            # Record an overtake: trains still waiting that were ready earlier than `chosen`.
            jumped = [t for t in remaining
                      if t is not chosen and ready[t["no"]][s] < ready[no][s] - 1e-6]
            if policy == "priority" and jumped:
                for j in jumped:
                    held[j["no"]][s] += 0.0  # marked precisely below once its entry is known
                actions.append({
                    "section_index": s,
                    "station": stations[s]["code"],
                    "station_name": stations[s]["name"],
                    "overtaker": no,
                    "overtaker_name": chosen["name"],
                    "held": [j["no"] for j in jumped],
                    "held_names": [j["name"] for j in jumped],
                })

            enter[no][s] = entry
            arrive[no][s + 1] = exit_t
            held[no][s] = max(0.0, entry - ready[no][s])
            prev_enter, prev_exit = entry, exit_t
            remaining.remove(chosen)

    # Assemble per-train results.
    free = _free_run(trains, stations, secs)
    results = {}
    total = 0.0
    weighted = 0.0
    affected = 0
    for t in trains:
        no = t["no"]
        tl = []
        for s in range(n):
            code = stations[s]["code"]
            arr = arrive[no][s]
            dep = enter[no][s] if s < n - 1 else None
            tl.append({
                "station": stations[s]["name"], "code": code,
                "arr": round(arr, 1) if arr is not None else None,
                "arr_hhmm": net.hhmm(arr) if arr is not None else None,
                "dep": round(dep, 1) if dep is not None else None,
                "dep_hhmm": net.hhmm(dep) if dep is not None else None,
                "stop": net.stops_at(t, code),
                "held_min": round(held[no][s], 1),
            })
        arrival = arrive[no][n - 1]
        delay = max(0.0, arrival - free[no])
        total += delay
        weighted += delay * t["priority"]
        if delay > 1.0:
            affected += 1
        results[no] = TrainResult(
            no=no, name=t["name"], type=t["type"], priority=t["priority"],
            timeline=tl, arrival_min=round(arrival, 1), delay_min=round(delay, 1),
        )

    return SimResult(
        policy=policy, trains=results, actions=actions,
        total_delay_min=round(total, 1), weighted_delay_min=round(weighted, 1),
        affected=affected,
    )
