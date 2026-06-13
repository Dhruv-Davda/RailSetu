"""
RailSetu backend — Indian Railway Intelligence Platform.
M1 flagship: Station Crowd-Flow & Stampede Prevention (NDLS).

The HTTP layer is thin: it loads the station graph, asks a `DemandProvider` for a
scenario (committed fixtures OR a live train feed), runs the pedestrian-flow
simulation, optionally folds in calibration from measured crowd density, and
shapes the result for the control-room UI.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import configure_logging, get_settings
from app.data.station import load_station, refresh_station
from app.demand.factory import get_demand_provider
from app.ingest.calibration import CalibrationState, compute_capacity_scale
from app.ingest.crowd_sensing import get_crowd_sensor
from app.m1_crowd.simulation import los_for, simulate

settings = get_settings()
configure_logging(settings)
log = logging.getLogger("railsetu")

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Process-wide singletons (cheap, stateless except the calibration store).
CROWD_SENSOR = get_crowd_sensor(settings)
CAL_STATE = CalibrationState()

METER_DENSITY = 2.5      # hold at mid LOS C (comfortably safe) before the FOB
FOB_EGRESS_MULT = 2.5


class Mitigations(BaseModel):
    # Crowd-engineering controls the operator can toggle in the what-if sandbox.
    metered_holding: bool = False    # hold people in roomy areas; meter onto FOB (LOS C)
    open_fob: bool = False           # one-way + extra foot-over-bridge lanes (egress x2.5)
    stagger_release: bool = False    # spread the platform release over more time
    extra_exits: bool = False        # open additional dispersal gates

    def describe(self):
        on = []
        if self.metered_holding: on.append("Metered holding (LOS C)")
        if self.open_fob: on.append("One-way / extra FOB lanes")
        if self.stagger_release: on.append("Staggered release")
        if self.extra_exits: on.append("Extra exit gates")
        return on


class SimRequest(BaseModel):
    scenario: str
    mitigations: Mitigations | None = None


def _run(scenario_key, mitigations: Mitigations | None):
    s = load_station()
    G = s["graph"]
    provider = get_demand_provider()
    ds = provider.get_scenario(scenario_key)
    if not ds:
        raise HTTPException(404, f"unknown scenario '{scenario_key}'")

    demands = [{"platform": d.platform, "people": d.people, "duration_s": d.duration_s}
               for d in ds.demands if d.platform in G]
    exits = [e for e in ds.exits if e in G]

    mit = {}
    cap_scale: dict = {}

    # Calibration (measured-density correction) applies to every run when enabled.
    if settings.calibration_enabled and CAL_STATE.capacity_scale:
        cap_scale.update(CAL_STATE.capacity_scale)

    if mitigations:
        if mitigations.metered_holding:
            mit["meter_density"] = METER_DENSITY
        if mitigations.stagger_release:
            mit["stagger"] = 0.5
        if mitigations.open_fob:
            for u, v in G.edges:
                if G.edges[u, v]["kind"] == "steps":
                    cap_scale[(u, v)] = cap_scale.get((u, v), 1.0) * FOB_EGRESS_MULT
        if mitigations.extra_exits:
            extra = [n for n in G.nodes
                     if G.nodes[n].get("kind") == "entrance" and n not in exits]
            exits = exits + extra

    if cap_scale:
        mit["capacity_scale"] = cap_scale

    res = simulate(G, demands, exits, horizon_s=ds.horizon_s, mitigations=mit)

    # Shape edge results for the client (string keys).
    edges = []
    for (u, v), dens in res.edge_density.items():
        grade, label = los_for(dens)
        edges.append({
            "u": u, "v": v,
            "density": dens,
            "people": res.edge_peak_count[(u, v)],
            "los": grade,
            "state": label,
            "kind": G.edges[u, v]["kind"],
        })

    # Per-node density (the crush metric) for every node, so the map can colour
    # holding areas / stair mouths, plus the ranked crush points.
    nodes = []
    for n, dens in res.node_density.items():
        grade, label = los_for(dens)
        nd = G.nodes[n]
        nodes.append({
            "node": n, "lat": nd["lat"], "lon": nd["lon"],
            "kind": nd.get("kind", "junction"), "name": nd.get("name"),
            "density": dens, "queue": round(res.node_queue_peak[n], 1),
            "los": grade, "state": label,
        })

    edge_peak = max((e["density"] for e in edges), default=0.0)
    node_peak = max((n["density"] for n in nodes), default=0.0)
    peak = max(edge_peak, node_peak)
    danger = [x for x in nodes + edges if x["los"] in ("E", "F")]
    return {
        "scenario": scenario_key,
        "title": ds.title,
        "source": ds.source,
        "generated_at": ds.generated_at,
        "demand_meta": ds.meta,
        "calibrated": settings.calibration_enabled and bool(CAL_STATE.capacity_scale),
        "edges": edges,
        "nodes": nodes,
        "hotspots": res.node_hotspots + res.hotspots,
        "node_hotspots": res.node_hotspots,
        "timeline": res.timeline,
        "summary": {
            "total_injected": res.total_injected,
            "total_cleared": res.total_cleared,
            "peak_density": round(peak, 2),
            "peak_los": los_for(peak)[0],
            "danger_count": len(danger),
            "crush_count": sum(1 for x in nodes + edges if x["los"] == "F"),
        },
    }


@app.get("/api/health")
def health():
    s = load_station()
    provider = get_demand_provider()
    return {
        "status": "ok",
        "version": settings.app_version,
        "station": s["meta"]["station"],
        "counts": s["meta"]["counts"],
        "demand_provider": provider.health(),
        "crowd_sensor": CROWD_SENSOR.health(),
        "calibration": CAL_STATE.as_dict(),
    }


@app.get("/api/station")
def station():
    """Geometry for the map: nodes, edges, platforms, exits."""
    s = load_station()
    return {
        "meta": s["meta"],
        "nodes": s["nodes"],
        "edges": s["edges"],
        "platforms": s["platforms"],
        "entrances": s["entrances"],
    }


@app.post("/api/station/refresh")
def station_refresh():
    """Hot-reload the station graph fixture (e.g. after a scheduled OSM rebuild)."""
    if not settings.allow_graph_refresh:
        raise HTTPException(403, "graph refresh disabled (set RAILSETU_ALLOW_GRAPH_REFRESH=true)")
    s = refresh_station()
    log.info("station graph refreshed: %s", s["meta"]["counts"])
    return {"refreshed": True, "counts": s["meta"]["counts"]}


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": get_demand_provider().list_scenarios()}


@app.get("/api/live/demand")
def live_demand():
    """Inspect the demand the live provider currently derives (transparency)."""
    if settings.demand_provider != "live":
        raise HTTPException(400, "demand_provider is not 'live' (set RAILSETU_DEMAND_PROVIDER=live)")
    ds = get_demand_provider().get_scenario("live_now")
    if not ds:
        raise HTTPException(503, "live demand unavailable")
    return {
        "key": ds.key, "title": ds.title, "source": ds.source,
        "generated_at": ds.generated_at, "horizon_s": ds.horizon_s,
        "total_people": ds.total_people, "meta": ds.meta,
        "demands": [{"platform": d.platform, "people": d.people,
                     "duration_s": d.duration_s, "label": d.label} for d in ds.demands],
    }


@app.post("/api/simulate")
def run_sim(req: SimRequest):
    return _run(req.scenario, req.mitigations)


@app.post("/api/whatif")
def whatif(req: SimRequest):
    """Run baseline vs. mitigated side by side for the what-if sandbox."""
    base = _run(req.scenario, None)
    mit = _run(req.scenario, req.mitigations)
    bp = base["summary"]["peak_density"]
    mp = mit["summary"]["peak_density"]
    reduction = round((bp - mp) / bp * 100, 1) if bp else 0.0
    return {
        "baseline": base,
        "mitigated": mit,
        "impact": {
            "peak_density_before": bp,
            "peak_density_after": mp,
            "peak_reduction_pct": reduction,
            "danger_before": base["summary"]["danger_count"],
            "danger_after": mit["summary"]["danger_count"],
            "crush_before": base["summary"]["crush_count"],
            "crush_after": mit["summary"]["crush_count"],
            "cleared_before": base["summary"]["total_cleared"],
            "cleared_after": mit["summary"]["total_cleared"],
        },
    }


@app.post("/api/calibration/run")
def calibration_run(scenario: str = Query("kumbh_surge")):
    """Pull measured crowd density and recompute the model's capacity calibration.

    Runs an uncalibrated baseline for `scenario`, compares predicted node density
    to the sensor's observations, and stores the resulting capacity corrections so
    subsequent simulations reflect reality. No-op (200) when no observations exist.
    """
    obs = CROWD_SENSOR.read()
    if not obs:
        return {"updated": False, "reason": "no observations from crowd sensor",
                "observations": 0, "sensor": CROWD_SENSOR.health()}

    s = load_station()
    G = s["graph"]
    provider = get_demand_provider()
    ds = provider.get_scenario(scenario)
    if not ds:
        raise HTTPException(404, f"unknown scenario '{scenario}'")

    demands = [{"platform": d.platform, "people": d.people, "duration_s": d.duration_s}
               for d in ds.demands if d.platform in G]
    exits = [e for e in ds.exits if e in G]
    res = simulate(G, demands, exits, horizon_s=ds.horizon_s)  # uncalibrated baseline

    scale = compute_capacity_scale(G, res.node_density, obs, settings)
    CAL_STATE.capacity_scale = scale
    CAL_STATE.observations = len(obs)
    CAL_STATE.edges_adjusted = len(scale)
    CAL_STATE.note = f"calibrated against {len(obs)} observation(s) on '{scenario}'"
    log.info("calibration updated: %d obs -> %d edges adjusted", len(obs), len(scale))
    return {"updated": True, "observations": len(obs),
            "edges_adjusted": len(scale), "calibration": CAL_STATE.as_dict()}


@app.post("/api/calibration/reset")
def calibration_reset():
    """Clear any active calibration (revert to textbook capacities)."""
    CAL_STATE.capacity_scale = {}
    CAL_STATE.observations = 0
    CAL_STATE.edges_adjusted = 0
    CAL_STATE.note = "reset"
    return {"reset": True, "calibration": CAL_STATE.as_dict()}
