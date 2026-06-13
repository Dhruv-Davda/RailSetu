"""Load the NDLS station graph fixture into a routable NetworkX graph."""
import json
import os
from functools import lru_cache

import networkx as nx

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "station_graph.json")


@lru_cache(maxsize=1)
def load_station():
    data = json.load(open(FIXTURE))

    G = nx.Graph()
    for n in data["nodes"]:
        G.add_node(n["id"], **n)
    for e in data["edges"]:
        # Undirected walk graph; weight = length so shortest path = shortest walk.
        G.add_edge(e["u"], e["v"],
                   length_m=e["length_m"],
                   kind=e["kind"],
                   width_m=e["width_m"],
                   capacity_pps=e["capacity_pps"])

    # Keep only the largest connected component for routing sanity.
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    if comps:
        G = G.subgraph(comps[0]).copy()

    platforms = [p for p in data["platforms"] if p["node"] in G]
    entrances = [e for e in data["entrances"] if e["node"] in G]

    return {
        "graph": G,
        "meta": data["meta"],
        "platforms": platforms,
        "entrances": entrances,
        "nodes": [G.nodes[n] for n in G.nodes],
        "edges": [
            {"u": u, "v": v, **G.edges[u, v]} for u, v in G.edges
        ],
    }


def refresh_station():
    """Drop the cached graph so the next load re-reads the fixture from disk.

    The fixture is regenerated out-of-band by scripts/build_station_graph.py
    (run on a schedule against a fresh OSM/Overpass snapshot). This lets the API
    pick up a new layout without a restart.
    """
    load_station.cache_clear()
    return load_station()
