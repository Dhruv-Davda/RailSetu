"""API-facing payload builders for M2 — keeps main.py thin."""
from __future__ import annotations

from . import network as net
from . import scenarios as scn
from .engine import SimResult, simulate


def network_payload() -> dict:
    """Corridor geometry + the planned train sheet for the M2 board."""
    trains = net.trains_with_priority()
    sheet = []
    # Each train's PLANNED (unobstructed) timeline, for the board.
    stations = net.STATIONS
    secs = net.sections()
    for t in trains:
        clock = t["dep_min"]
        tl = [{"code": stations[0]["code"], "arr_hhmm": net.hhmm(clock),
               "dep_hhmm": net.hhmm(clock), "stop": True}]
        for i, sec in enumerate(secs):
            clock += net.running_time_min(sec["km"], t["speed"])
            code = stations[i + 1]["code"]
            stop = net.stops_at(t, code)
            arr = clock
            if i + 1 < len(stations) - 1 and stop:
                clock += net.STOP_DWELL_MIN
            tl.append({"code": code, "arr_hhmm": net.hhmm(arr),
                       "dep_hhmm": net.hhmm(clock), "stop": stop})
        sheet.append({
            "no": t["no"], "name": t["name"], "type": t["type"],
            "priority": t["priority"], "speed": t["speed"],
            "dep": t["dep"], "timeline": tl,
        })
    return {
        "corridor": net.corridor_meta(),
        "stations": net.STATIONS,
        "sections": secs,
        "trains": sheet,
    }


def scenarios_payload() -> dict:
    return {"scenarios": scn.list_scenarios()}


def _serialize(res: SimResult) -> dict:
    return {
        "policy": res.policy,
        "total_delay_min": res.total_delay_min,
        "weighted_delay_min": res.weighted_delay_min,
        "affected": res.affected,
        "actions": res.actions,
        "trains": [
            {
                "no": tr.no, "name": tr.name, "type": tr.type,
                "priority": tr.priority, "delay_min": tr.delay_min,
                "arrival_min": tr.arrival_min,
                "arrival_hhmm": net.hhmm(tr.arrival_min),
                "timeline": tr.timeline,
            }
            for tr in res.trains.values()
        ],
    }


def simulate_payload(scenario_key: str, optimize: bool = True) -> dict | None:
    sc = scn.get_scenario(scenario_key)
    if sc is None:
        return None
    dis = sc["disruption"]
    baseline = simulate("fcfs", dis)
    optimized = simulate("priority", dis) if optimize else None

    out = {
        "scenario": scenario_key,
        "title": sc["title"],
        "description": sc["description"],
        "disruption": _describe_disruption(dis),
        "baseline": _serialize(baseline),
    }
    if optimized is not None:
        b, o = baseline.total_delay_min, optimized.total_delay_min
        out["optimized"] = _serialize(optimized)
        out["impact"] = {
            "delay_before_min": b,
            "delay_after_min": o,
            "saved_min": round(b - o, 1),
            "saved_pct": round((b - o) / b * 100, 1) if b else 0.0,
            "weighted_before": baseline.weighted_delay_min,
            "weighted_after": optimized.weighted_delay_min,
            "affected_before": baseline.affected,
            "affected_after": optimized.affected,
            "actions_count": len(optimized.actions),
        }
    return out


def _describe_disruption(dis) -> dict | None:
    if not dis:
        return None
    out = {"train": dis.get("train")}
    if "dep_override" in dis:
        out["type"] = "repath"
        out["detail"] = f"running late — pathed ahead, entering at {net.hhmm(dis['dep_override'])}"
    if "station_index" in dis and "delay_min" in dis:
        st = net.STATIONS[dis["station_index"]]["name"]
        out["type"] = out.get("type", "delay")
        d = f"+{dis['delay_min']} min at {st}"
        out["detail"] = f"{out.get('detail', '')}; {d}" if out.get("detail") else d
    return out
