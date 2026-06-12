"""
RailSetu backend — Indian Railway Intelligence Platform.
M1 flagship: Station Crowd-Flow & Stampede Prevention (NDLS).
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.data.station import load_station
from app.m1_crowd import scenarios as scn
from app.m1_crowd.simulation import los_for, simulate

app = FastAPI(title="RailSetu API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    s = load_station()
    return {"status": "ok", "station": s["meta"]["station"], "counts": s["meta"]["counts"]}


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


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": scn.list_scenarios()}


class Mitigations(BaseModel):
    # Crowd-engineering controls the operator can toggle in the what-if sandbox.
    metered_holding: bool = False    # hold people in roomy areas; meter onto FOB (LOS D)
    open_fob: bool = False           # one-way + extra foot-over-bridge lanes (egress x2.5)
    stagger_release: bool = False    # spread the platform release over more time
    extra_exits: bool = False        # open additional dispersal gates

    def describe(self):
        on = []
        if self.metered_holding: on.append("Metered holding (LOS D)")
        if self.open_fob: on.append("One-way / extra FOB lanes")
        if self.stagger_release: on.append("Staggered release")
        if self.extra_exits: on.append("Extra exit gates")
        return on


class SimRequest(BaseModel):
    scenario: str
    mitigations: Mitigations | None = None


METER_DENSITY = 2.5      # hold at mid LOS C (comfortably safe) before the FOB
FOB_EGRESS_MULT = 2.5


def _run(scenario_key, mitigations: Mitigations | None):
    s = load_station()
    G = s["graph"]
    sc = scn.get_scenario(scenario_key)
    if not sc:
        raise HTTPException(404, f"unknown scenario '{scenario_key}'")

    demands = [{"platform": d["platform"], "people": d["people"],
                "duration_s": d["duration_s"]} for d in sc["demands"]
               if d["platform"] in G]
    exits = [e for e in sc["exits"] if e in G]

    mit = {}
    if mitigations:
        if mitigations.metered_holding:
            mit["meter_density"] = METER_DENSITY
        if mitigations.stagger_release:
            mit["stagger"] = 0.5
        if mitigations.open_fob:
            mit["capacity_scale"] = {
                (u, v): FOB_EGRESS_MULT for u, v in G.edges
                if G.edges[u, v]["kind"] == "steps"
            }
        if mitigations.extra_exits:
            extra = [n for n in G.nodes
                     if G.nodes[n].get("kind") == "entrance" and n not in exits]
            exits = exits + extra

    res = simulate(G, demands, exits, horizon_s=sc["horizon_s"], mitigations=mit)

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
        "title": sc["title"],
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
