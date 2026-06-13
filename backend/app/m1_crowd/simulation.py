"""
M1 — Pedestrian flow simulation for station crowd / stampede risk.

This is a *macroscopic* origin-destination flow model on the station walk graph,
not a cosmetic animation. People are injected at platform nodes (a train unloads,
or a festival surge builds), each routed along the shortest walk to an exit. Every
edge has a finite throughput (capacity_pps) and a walk delay; when demand on an
edge exceeds its capacity, people queue at the upstream node and density rises.

Density is reported in persons/m^2 and graded with Fruin Level-of-Service bands:
    < 1.0   free flow      (A/B)
    1.0-2.0 restricted     (C)
    2.0-3.5 constrained    (D)
    3.5-5.0 dangerous      (E)   <- intervene
    > 5.0   crush risk     (F)   <- lethal, the stampede regime

The Feb 2025 NDLS disaster occurred when a foot-over-bridge between platforms 14
and 15 hit the crush regime. This model reproduces that mechanism: a narrow,
low-capacity stair/FOB downstream of a high-demand platform becomes the choke
point, and density there crosses 5 p/m^2.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import networkx as nx

WALK_SPEED_MPS = 1.30          # mean walking speed on the flat
STEP_SPEED_FACTOR = 0.65       # stairs are slower
DT = 2.0                       # simulation timestep (seconds)

# Fruin-style density bands (persons / m^2).
LOS_BANDS = [
    (1.0, "A", "free"),
    (2.0, "C", "restricted"),
    (3.5, "D", "constrained"),
    (5.0, "E", "dangerous"),
    (99.0, "F", "crush"),
]


def los_for(density: float):
    for thresh, grade, label in LOS_BANDS:
        if density < thresh:
            return grade, label
    return "F", "crush"


@dataclass
class Cohort:
    """A blob of people sharing the same remaining route."""
    dest: str
    route: list           # list of node ids, route[0] is current node
    idx: int              # index of current node within route
    count: float


@dataclass
class EdgeState:
    on_edge: float = 0.0           # people currently traversing
    peak_density: float = 0.0
    peak_count: float = 0.0


@dataclass
class SimResult:
    edge_density: dict             # (u,v) -> peak persons/m^2
    edge_peak_count: dict
    node_queue_peak: dict          # node -> peak queued people
    node_density: dict             # node -> peak persons/m^2 in its holding area
    hotspots: list                 # ranked dangerous edges
    node_hotspots: list            # ranked crush points (nodes)
    timeline: list                 # per-step max density (for the ripple chart)
    total_injected: float
    total_cleared: float
    params: dict


# Effective "catchment" area (m^2) over which people waiting at a node actually
# stand. A crush happens when this fills up. The foot of a stair / foot-over-
# bridge is a tight landing, but a queue there does not pack into a single point
# -- it spills back along the approach corridors. So a node's catchment is its
# own landing plus a share of the walkable area of the corridors feeding into it.
# Tight stair mouths with little approach room are exactly where density spikes.
BASE_AREA = {
    "platform": 1400.0,
    "entrance": 90.0,
    "elevator": 12.0,
}
STAIR_LANDING_AREA = 18.0       # bare landing at the foot of a stair / FOB
JUNCTION_LANDING_AREA = 30.0    # bare open-junction apron
SPILLBACK_SHARE = 0.5           # fraction of an approach corridor a queue can use


def _node_area(G, node):
    kind = G.nodes[node].get("kind", "junction")
    if kind in BASE_AREA:
        return BASE_AREA[kind]
    incident = [G.edges[node, nb] for nb in G.neighbors(node)]
    if not incident:
        return JUNCTION_LANDING_AREA
    only_stairs = all(e["kind"] == "steps" for e in incident)
    base = STAIR_LANDING_AREA if only_stairs else JUNCTION_LANDING_AREA
    # Queue spills back onto the flat approach corridors (not up the stairs).
    spill = sum(e["width_m"] * e["length_m"] for e in incident if e["kind"] != "steps")
    return base + SPILLBACK_SHARE * spill


def _edge_attr(G, u, v):
    return G.edges[u, v]


def _travel_time(G, u, v):
    e = _edge_attr(G, u, v)
    speed = WALK_SPEED_MPS * (STEP_SPEED_FACTOR if e["kind"] == "steps" else 1.0)
    return max(DT, e["length_m"] / speed)


def _shortest_route(G, src, dst, cache):
    key = (src, dst)
    if key in cache:
        return cache[key]
    try:
        route = nx.shortest_path(G, src, dst, weight="length_m")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        route = None
    cache[key] = route
    return route


def simulate(G, demands, exits, *, horizon_s=300, mitigations=None):
    """
    demands : list of {"platform": node_id, "people": N, "duration_s": D}
              N people emerge from the platform spread over D seconds.
    exits   : list of exit node ids people head toward (nearest exit chosen).
    mitigations : optional dict applied before the run, e.g.
              {"capacity_scale": {(u,v): 1.5}, "stagger": 0.5}
    """
    mitigations = mitigations or {}
    cap_scale = mitigations.get("capacity_scale", {})
    stagger = mitigations.get("stagger", 1.0)   # <1 spreads demand over more time
    # Back-pressure / metering: when set, people are NOT pushed into a downstream
    # space that is already at or above this density (persons/m^2). They wait in
    # the roomy upstream area (platform / holding pen) instead. This is the core
    # crowd-engineering control: the disaster happens precisely when it is absent
    # and people keep pressing into a packed foot-over-bridge landing.
    meter_density = mitigations.get("meter_density")   # e.g. 3.5 = hold at LOS D

    steps = int(horizon_s / DT)
    route_cache = {}

    # Effective edge capacity (people per timestep) and per-edge geometry.
    edge_caps = {}
    edge_area = {}
    for u, v in G.edges:
        e = _edge_attr(G, u, v)
        scale = cap_scale.get((u, v), cap_scale.get((v, u), 1.0))
        edge_caps[(u, v)] = e["capacity_pps"] * scale * DT
        edge_caps[(v, u)] = edge_caps[(u, v)]
        edge_area[(u, v)] = max(1.0, e["width_m"] * e["length_m"])
        edge_area[(v, u)] = edge_area[(u, v)]

    # Pre-route every platform's crowd. Real crowds do NOT all use one staircase;
    # they spread across the nearest few exits/foot-over-bridges. So for each
    # platform we take its K nearest exits and split the demand across those
    # routes, weighted toward closer exits. A surge still overwhelms the shared
    # choke points (the P14/15 FOB), but routine flow is no longer artificially
    # gridlocked behind a single stair.
    K_ROUTES = 3
    plan = []  # each: {src, dest, route, total, per_step, n_steps}
    for d in demands:
        src = d["platform"]
        routed = []
        for ex in exits:
            r = _shortest_route(G, src, ex, route_cache)
            if r:
                length = sum(G.edges[a, b]["length_m"] for a, b in zip(r, r[1:]))
                routed.append((length, ex, r))
        if not routed:
            continue
        routed.sort(key=lambda t: t[0])
        chosen = routed[:K_ROUTES]
        # Inverse-distance weights -> closer exits take more of the crowd.
        weights = [1.0 / max(length, 1.0) for length, _, _ in chosen]
        wsum = sum(weights)
        dur = max(DT, d["duration_s"] / max(stagger, 0.05))
        # Clamp to the simulation horizon: without this, staggering can push the
        # injection window past `steps`, so the tail of the demand is never
        # injected and people silently vanish from the count (making "staggered
        # release" look better merely by losing crowd). Capping keeps every
        # person injected; staggering still lowers the per-step rate.
        n_steps = max(1, min(int(dur / DT), steps))
        for (length, ex, r), w in zip(chosen, weights):
            share = float(d["people"]) * w / wsum
            plan.append({
                "src": src, "dest": ex, "route": r,
                "total": share,
                "per_step": share / n_steps,
                "n_steps": n_steps,
            })

    # State.
    node_queue = {n: [] for n in G.nodes}      # node -> list[Cohort] waiting to advance
    edges_in_transit = {}                       # (u,v) -> list[[count, t_remaining, dest, route, idx]]
    edge_state = {(u, v): EdgeState() for u, v in G.edges}
    edge_state.update({(v, u): EdgeState() for u, v in G.edges})

    node_queue_peak = {n: 0.0 for n in G.nodes}
    node_density_peak = {n: 0.0 for n in G.nodes}
    node_area = {n: _node_area(G, n) for n in G.nodes}
    exits_set = set(exits)
    timeline = []
    total_injected = 0.0
    total_cleared = 0.0

    for step in range(steps):
        # 1) Inject this step's demand at platform nodes.
        for p in plan:
            if step < p["n_steps"]:
                node_queue[p["src"]].append(
                    Cohort(dest=p["dest"], route=p["route"], idx=0, count=p["per_step"])
                )
                total_injected += p["per_step"]

        # 2) Advance people already traversing edges.
        arrivals = {}
        for ekey, cohorts in list(edges_in_transit.items()):
            still = []
            for c in cohorts:
                c[1] -= DT
                if c[1] <= 0:
                    arrivals.setdefault(ekey[1], []).append(c)
                else:
                    still.append(c)
            if still:
                edges_in_transit[ekey] = still
            else:
                edges_in_transit.pop(ekey, None)

        # Deposit arrivals into downstream node queues (or clear at destination).
        for node, cs in arrivals.items():
            for c in cs:
                count, _, dest, route, idx = c
                if node == dest or idx >= len(route) - 1:
                    total_cleared += count
                else:
                    node_queue[node].append(Cohort(dest=dest, route=route, idx=idx, count=count))

        # 3) Move queued people onto their next edge, capped by edge capacity
        #    (and, if metering is on, by downstream space availability).
        edge_admitted = {}
        node_inflow = {}          # people admitted INTO a node this step (back-pressure)
        node_current = {n: sum(c.count for c in node_queue[n]) for n in node_queue}
        for node, cohorts in node_queue.items():
            if not cohorts:
                continue
            remaining = []
            for c in cohorts:
                nxt = c.route[c.idx + 1] if c.idx + 1 < len(c.route) else None
                if nxt is None:
                    total_cleared += c.count
                    continue
                ekey = (node, nxt)
                used = edge_admitted.get(ekey, 0.0)
                free = max(0.0, edge_caps.get(ekey, 0.0) - used)
                # Back-pressure: don't push people into an already-packed space.
                if meter_density is not None and nxt not in exits_set:
                    projected = node_current.get(nxt, 0.0) + node_inflow.get(nxt, 0.0)
                    headroom = meter_density * node_area[nxt] - projected
                    free = min(free, max(0.0, headroom))
                move = min(c.count, free)
                if move > 0:
                    node_inflow[nxt] = node_inflow.get(nxt, 0.0) + move
                    edge_admitted[ekey] = used + move
                    tt = _travel_time(G, node, nxt)
                    edges_in_transit.setdefault(ekey, []).append(
                        [move, tt, c.dest, c.route, c.idx + 1]
                    )
                    c.count -= move
                if c.count > 1e-6:
                    remaining.append(c)   # blocked this step -> stays queued (pressure!)
            node_queue[node] = remaining

        # 4) Measure density on every edge and queue pressure at every node.
        step_max_density = 0.0
        for ekey, cohorts in edges_in_transit.items():
            people = sum(c[0] for c in cohorts)
            dens = people / edge_area[ekey]
            es = edge_state[ekey]
            es.on_edge = people
            if dens > es.peak_density:
                es.peak_density = dens
            if people > es.peak_count:
                es.peak_count = people
            step_max_density = max(step_max_density, dens)

        for node, cohorts in node_queue.items():
            q = sum(c.count for c in cohorts)
            if q > node_queue_peak[node]:
                node_queue_peak[node] = q
            dens = q / node_area[node]
            if dens > node_density_peak[node]:
                node_density_peak[node] = dens
            step_max_density = max(step_max_density, dens)

        timeline.append(round(step_max_density, 3))

    # Aggregate undirected edge peaks (max of both directions).
    edge_density = {}
    edge_peak_count = {}
    for u, v in G.edges:
        d = max(edge_state[(u, v)].peak_density, edge_state[(v, u)].peak_density)
        c = max(edge_state[(u, v)].peak_count, edge_state[(v, u)].peak_count)
        edge_density[(u, v)] = round(d, 3)
        edge_peak_count[(u, v)] = round(c, 1)

    hotspots = []
    for (u, v), dens in edge_density.items():
        grade, label = los_for(dens)
        if grade in ("D", "E", "F"):
            e = _edge_attr(G, u, v)
            hotspots.append({
                "u": u, "v": v,
                "density": dens,
                "people": edge_peak_count[(u, v)],
                "los": grade,
                "state": label,
                "kind": e["kind"],
                "width_m": e["width_m"],
            })
    hotspots.sort(key=lambda h: h["density"], reverse=True)

    node_density = {n: round(d, 3) for n, d in node_density_peak.items()}
    node_hotspots = []
    for n, dens in node_density.items():
        grade, label = los_for(dens)
        if grade in ("D", "E", "F"):
            nd = G.nodes[n]
            node_hotspots.append({
                "node": n,
                "lat": nd["lat"], "lon": nd["lon"],
                "kind": nd.get("kind", "junction"),
                "name": nd.get("name"),
                "density": dens,
                "queue": round(node_queue_peak[n], 1),
                "los": grade,
                "state": label,
            })
    node_hotspots.sort(key=lambda h: h["density"], reverse=True)

    return SimResult(
        edge_density=edge_density,
        edge_peak_count=edge_peak_count,
        node_queue_peak=node_queue_peak,
        node_density=node_density,
        hotspots=hotspots,
        node_hotspots=node_hotspots,
        timeline=timeline,
        total_injected=round(total_injected, 1),
        total_cleared=round(total_cleared, 1),
        params={"horizon_s": horizon_s, "dt": DT, "stagger": stagger},
    )
