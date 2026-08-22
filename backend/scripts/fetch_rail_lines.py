"""
Fetch the real rail-track alignments around NDLS from OpenStreetMap (Overpass)
and freeze them as a committed fixture.

Input : Overpass API (run out-of-band, like build_station_graph.py)
Output: backend/fixtures/ndls_rails.json

These are DECORATIVE for the 3D scene — the crowd simulation runs on the walk
graph, not on track geometry — but they are REAL: every polyline is an actual
`railway=rail|siding|yard|crossover|spur` way at New Delhi station. That is why
the 2D basemap looks dense (the tiles draw the true yard) and the schematic 3D
previously did not; this closes that gap with data instead of set-dressing.

Committed fixture, so the demo stays network-free at runtime. Re-run this on a
schedule alongside build_station_graph.py to pick up mapping improvements.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

import httpx

CENTER = (28.6428, 77.2191)          # NDLS, same center as the walk graph
RADIUS_M = 800                        # covers the platforms + both approach throats
MIN_PT_SPACING_M = 2.5                # drop redundant vertices; keep endpoints

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "..", "fixtures", "ndls_rails.json")

QUERY = f"""
[out:json][timeout:60];
way(around:{RADIUS_M},{CENTER[0]},{CENTER[1]})
  ["railway"~"^(rail|siding|yard|crossover|spur)$"];
out geom tags;
"""

R_LAT = 110540.0
R_LON = 111320.0 * math.cos(CENTER[0] * math.pi / 180)


def dist_m(a, b) -> float:
    return math.hypot((a[1] - b[1]) * R_LON, (a[0] - b[0]) * R_LAT)


def simplify(pts, min_gap):
    """Keep points at least min_gap apart; always keep both endpoints."""
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    for p in pts[1:-1]:
        if dist_m(out[-1], p) >= min_gap:
            out.append(p)
    out.append(pts[-1])
    return out


MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def fetch():
    last = None
    for url in MIRRORS:
        try:
            resp = httpx.post(
                url,
                data={"data": QUERY},
                timeout=90,
                # Overpass returns 406 to clients with no meaningful User-Agent.
                headers={"User-Agent": "RailSetu/1.0 (station-graph fixture builder)"},
            )
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except Exception as e:  # noqa: BLE001 — try the next mirror
            print(f"  {url} -> {e}")
            last = e
    raise SystemExit(f"all Overpass mirrors failed: {last}")


def main():
    elements = fetch()

    ways = []
    raw_pts = kept_pts = 0
    total_m = 0.0
    for el in elements:
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        pts = [[g["lat"], g["lon"]] for g in geom]
        raw_pts += len(pts)
        pts = simplify(pts, MIN_PT_SPACING_M)
        kept_pts += len(pts)
        total_m += sum(dist_m(a, b) for a, b in zip(pts, pts[1:]))
        ways.append({
            "t": el.get("tags", {}).get("railway", "rail"),
            "pts": [[round(lat, 6), round(lon, 6)] for lat, lon in pts],
        })

    fixture = {
        "meta": {
            "source": "OpenStreetMap via Overpass (snapshot fixture)",
            "center": {"lat": CENTER[0], "lon": CENTER[1]},
            "radius_m": RADIUS_M,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": {
                "ways": len(ways),
                "points": kept_pts,
                "points_raw": raw_pts,
                "track_km": round(total_m / 1000, 1),
            },
        },
        "ways": ways,
    }
    json.dump(fixture, open(OUT, "w"))
    print(json.dumps(fixture["meta"], indent=2))
    print(f"wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
