"""
Build a connected, walkable station graph for New Delhi (NDLS) from a raw
OpenStreetMap Overpass extract.

Input : backend/fixtures/ndls_osm_raw.json   (Overpass `out body geom`)
Output: backend/fixtures/station_graph.json   (nodes + edges, the M1 fixture)

The raw OSM footway/step network is *almost* a graph: ways share endpoints in
the real world but their coordinates rarely match exactly, so we snap every
vertex to a small grid and merge vertices that fall within SNAP_M metres. Each
resulting edge carries a walkable `width_m`, a `capacity_pps` (people per
second it can pass) and a `kind` (footway | steps | platform_link). Stairs and
foot-over-bridges get a deliberately lower capacity — they are the choke points
where crowd crushes happen (e.g. the NDLS platform 14/15 FOB, Feb 2025).

This runs ONCE to produce a committed fixture, so the demo never depends on a
live Overpass call (PRD risk: messy/unreliable India data).
"""
import json
import math
import os
from collections import defaultdict

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "fixtures", "ndls_osm_raw.json")
OUT = os.path.join(HERE, "..", "fixtures", "station_graph.json")

# Snap tolerance: OSM way endpoints within this distance are treated as one node.
SNAP_M = 6.0

# Default walkable width (m) and the throughput it allows. ~1.3 persons/m/s is the
# standard maximum specific flow for level pedestrian movement (Fruin / HCM).
FLOW_PER_M_PER_S = 1.3
DEFAULT_WIDTH = {
    "footway": 4.0,
    "pedestrian": 6.0,
    "path": 2.5,
    "steps": 2.5,        # stairs are narrower AND slower -> choke point
    "platform_link": 3.5,
}
# Stairs move people slower than flat ground; scale their effective capacity.
STEP_CAPACITY_FACTOR = 0.7

R_EARTH = 6371000.0


def haversine(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (
        math.sin((lat2 - lat1) * p / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    )
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def snap_key(lat, lon):
    # Grid size in degrees roughly equal to SNAP_M near NDLS latitude.
    dlat = SNAP_M / 111320.0
    dlon = SNAP_M / (111320.0 * math.cos(28.64 * math.pi / 180))
    return (round(lat / dlat), round(lon / dlon))


def width_for(tags, kind):
    w = tags.get("width") or tags.get("est_width")
    if w:
        try:
            return max(1.0, float(str(w).split()[0]))
        except ValueError:
            pass
    return DEFAULT_WIDTH.get(kind, 3.0)


def capacity_pps(width_m, kind):
    cap = width_m * FLOW_PER_M_PER_S
    if kind == "steps":
        cap *= STEP_CAPACITY_FACTOR
    return round(cap, 2)


def main():
    raw = json.load(open(RAW))
    elements = raw["elements"]

    nodes = {}          # node_id -> {id, lat, lon, kind, name}
    snap_to_node = {}   # snap_key -> node_id
    edges = []
    platforms = []
    entrances = []
    next_id = [0]

    def get_node(lat, lon, kind="junction", name=None):
        k = snap_key(lat, lon)
        if k in snap_to_node:
            nid = snap_to_node[k]
            # Promote a plain junction if it turns out to be something meaningful.
            if kind != "junction" and nodes[nid]["kind"] == "junction":
                nodes[nid]["kind"] = kind
                if name:
                    nodes[nid]["name"] = name
            return nid
        nid = f"n{next_id[0]}"
        next_id[0] += 1
        nodes[nid] = {"id": nid, "lat": round(lat, 7), "lon": round(lon, 7),
                      "kind": kind, "name": name}
        snap_to_node[k] = nid
        return nid

    def centroid(geom):
        return (sum(g["lat"] for g in geom) / len(geom),
                sum(g["lon"] for g in geom) / len(geom))

    # ---- Pass 1: linear ways (footways, steps) become chains of edges ----
    for el in elements:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        hw = tags.get("highway")
        is_platform = tags.get("railway") == "platform" or tags.get("public_transport") == "platform"

        if is_platform:
            lat, lon = centroid(geom)
            ref = tags.get("ref") or tags.get("name") or ""
            pid = get_node(lat, lon, kind="platform", name=f"Platform {ref}".strip())
            platforms.append({"node": pid, "ref": ref, "name": nodes[pid]["name"]})
            continue

        if hw in ("footway", "pedestrian", "path", "steps"):
            kind = "steps" if hw == "steps" else (hw if hw in DEFAULT_WIDTH else "footway")
            width = width_for(tags, kind)
            cap = capacity_pps(width, kind)
            prev = None
            for g in geom:
                cur = get_node(g["lat"], g["lon"])
                if prev is not None and prev != cur:
                    d = haversine(nodes[prev]["lat"], nodes[prev]["lon"],
                                  nodes[cur]["lat"], nodes[cur]["lon"])
                    if d > 0.1:
                        edges.append({
                            "u": prev, "v": cur,
                            "length_m": round(d, 2),
                            "kind": kind,
                            "width_m": width,
                            "capacity_pps": cap,
                        })
                prev = cur

    # ---- Pass 2: point features (entrances, elevators) ----
    for el in elements:
        if el["type"] != "node":
            continue
        tags = el.get("tags", {})
        if "entrance" in tags or tags.get("railway") == "subway_entrance":
            nid = get_node(el["lat"], el["lon"], kind="entrance",
                           name=tags.get("name", "Entrance"))
            entrances.append({"node": nid, "name": nodes[nid]["name"]})
        elif tags.get("highway") == "elevator":
            get_node(el["lat"], el["lon"], kind="elevator", name="Elevator")

    # ---- Pass 3: stitch platforms into the walk network ----
    # Real platforms have access (stairs/FOB) at several points along their
    # length, so connect each platform centroid to its few nearest walkable
    # junctions, not just one. A single link would be an artificial bottleneck
    # that hides the true choke point (the foot-over-bridge stairs).
    walk_nodes = [n for n in nodes.values() if n["kind"] in ("junction", "entrance")]
    PLATFORM_ACCESS_POINTS = 3
    for p in platforms:
        pn = nodes[p["node"]]
        ranked = sorted(
            ((haversine(pn["lat"], pn["lon"], wn["lat"], wn["lon"]), wn) for wn in walk_nodes),
            key=lambda t: t[0],
        )
        for d, wn in ranked[:PLATFORM_ACCESS_POINTS]:
            if d > 150:
                break
            edges.append({
                "u": p["node"], "v": wn["id"],
                "length_m": round(max(d, 1.0), 2),
                "kind": "platform_link",
                "width_m": DEFAULT_WIDTH["platform_link"],
                "capacity_pps": capacity_pps(DEFAULT_WIDTH["platform_link"], "platform_link"),
            })

    # ---- Pass 4: bridge disconnected components ----
    # OSM ways frequently fail to meet at junctions, leaving the network in
    # islands. Repeatedly connect the largest component to its nearest island by
    # the closest node pair (a "transfer_link"), until the graph is connected or
    # no island is within BRIDGE_M of it.
    import networkx as nx
    BRIDGE_M = 35.0

    def build_graph():
        g = nx.Graph()
        g.add_nodes_from(nodes)
        for e in edges:
            g.add_edge(e["u"], e["v"])
        return g

    for _ in range(40):
        G = build_graph()
        comps = sorted(nx.connected_components(G), key=len, reverse=True)
        if len(comps) <= 1:
            break
        main_comp = comps[0]
        best = None  # (dist, u, v)
        for other in comps[1:]:
            for a in other:
                na = nodes[a]
                for b in main_comp:
                    nb = nodes[b]
                    # cheap bounding pre-filter before haversine
                    if abs(na["lat"] - nb["lat"]) > 0.0005 or abs(na["lon"] - nb["lon"]) > 0.0005:
                        continue
                    d = haversine(na["lat"], na["lon"], nb["lat"], nb["lon"])
                    if best is None or d < best[0]:
                        best = (d, a, b)
        if best is None or best[0] > BRIDGE_M:
            break
        d, a, b = best
        edges.append({
            "u": a, "v": b,
            "length_m": round(max(d, 0.5), 2),
            "kind": "transfer_link",
            "width_m": 3.0,
            "capacity_pps": capacity_pps(3.0, "footway"),
        })

    # ---- Connectivity report ----
    G = build_graph()
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    largest = comps[0] if comps else set()

    station = {
        "meta": {
            "station": "New Delhi (NDLS)",
            "code": "NDLS",
            "source": "OpenStreetMap via Overpass (snapshot fixture)",
            "center": {"lat": 28.6428, "lon": 77.2191},
            "snap_m": SNAP_M,
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "platforms": len(platforms),
                "entrances": len(entrances),
                "components": len(comps),
                "largest_component": len(largest),
            },
        },
        "nodes": list(nodes.values()),
        "edges": edges,
        "platforms": platforms,
        "entrances": entrances,
    }
    json.dump(station, open(OUT, "w"), indent=2)
    print(f"Wrote {OUT}")
    print(json.dumps(station["meta"]["counts"], indent=2))


if __name__ == "__main__":
    main()
