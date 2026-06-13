"""
M6 — Kavach coverage × accident-risk data (representative, indicative).

IMPORTANT HONESTY NOTE: this is a *representative* dataset assembled from public
reporting, NOT an official corridor-level register. Kavach deployment figures are
news-sourced and approximate; accident statistics are published mostly at zone
level. So the DIRECTION of the analysis is sound (busy, unequipped trunk routes
carry disproportionate collision risk), but specific numbers are INDICATIVE and
must be labelled as such — never quoted as hard fact.

Each corridor carries:
  * geometry (endpoint lat/lon) so the frontend can draw it on a map of India;
  * daily_trains  — traffic intensity (proxy for exposure);
  * kavach_pct    — share of the route equipped with Kavach (0–100);
  * incidents_5yr — representative count of collisions / SPAD-type incidents
                    on or near the corridor over ~5 years.
"""
from __future__ import annotations

# Major-city coordinates [lat, lon].
_C = {
    "Delhi": (28.64, 77.22), "Mumbai": (19.07, 72.88), "Howrah": (22.58, 88.34),
    "Chennai": (13.08, 80.27), "Secunderabad": (17.43, 78.50), "Nagpur": (21.15, 79.09),
    "Bhopal": (23.26, 77.41), "Vijayawada": (16.51, 80.65), "Kanpur": (26.45, 80.33),
    "Guwahati": (26.18, 91.75), "Ahmedabad": (23.03, 72.58), "Bengaluru": (12.97, 77.59),
    "Wadi": (17.05, 76.99), "Vadodara": (22.31, 73.18),
}

# kavach_pct reflects the rollout priority order publicly reported: the SCR pilot
# corridors first, then the Delhi–Mumbai and Delhi–Howrah high-density routes.
CORRIDORS = [
    {"id": "ndls_bct", "name": "Delhi – Mumbai",        "from": "Delhi", "to": "Mumbai",      "route_km": 1384, "daily_trains": 310, "kavach_pct": 38, "incidents_5yr": 9},
    {"id": "ndls_hwh", "name": "Delhi – Howrah",        "from": "Delhi", "to": "Howrah",      "route_km": 1451, "daily_trains": 300, "kavach_pct": 34, "incidents_5yr": 11},
    {"id": "ndls_mas", "name": "Delhi – Chennai",       "from": "Delhi", "to": "Chennai",     "route_km": 2180, "daily_trains": 180, "kavach_pct": 6,  "incidents_5yr": 10},
    {"id": "bct_hwh",  "name": "Mumbai – Howrah",       "from": "Mumbai", "to": "Howrah",     "route_km": 1968, "daily_trains": 165, "kavach_pct": 4,  "incidents_5yr": 12},
    {"id": "hwh_mas",  "name": "Howrah – Chennai",      "from": "Howrah", "to": "Chennai",    "route_km": 1659, "daily_trains": 150, "kavach_pct": 3,  "incidents_5yr": 13},
    {"id": "bct_mas",  "name": "Mumbai – Chennai",      "from": "Mumbai", "to": "Chennai",    "route_km": 1279, "daily_trains": 140, "kavach_pct": 5,  "incidents_5yr": 8},
    {"id": "ndls_ghy", "name": "Delhi – Guwahati",      "from": "Delhi", "to": "Guwahati",    "route_km": 1880, "daily_trains": 120, "kavach_pct": 2,  "incidents_5yr": 9},
    {"id": "bct_adi",  "name": "Mumbai – Ahmedabad",    "from": "Mumbai", "to": "Ahmedabad",  "route_km": 491,  "daily_trains": 170, "kavach_pct": 22, "incidents_5yr": 5},
    {"id": "mas_sbc",  "name": "Chennai – Bengaluru",   "from": "Chennai", "to": "Bengaluru", "route_km": 362,  "daily_trains": 130, "kavach_pct": 8,  "incidents_5yr": 4},
    {"id": "ndls_adi", "name": "Delhi – Ahmedabad",     "from": "Delhi", "to": "Ahmedabad",   "route_km": 934,  "daily_trains": 110, "kavach_pct": 9,  "incidents_5yr": 6},
    {"id": "sc_bza",   "name": "Secunderabad – Vijayawada", "from": "Secunderabad", "to": "Vijayawada", "route_km": 350, "daily_trains": 120, "kavach_pct": 92, "incidents_5yr": 2},
    {"id": "sc_wadi",  "name": "Secunderabad – Wadi",   "from": "Secunderabad", "to": "Wadi", "route_km": 218,  "daily_trains": 95,  "kavach_pct": 88, "incidents_5yr": 1},
    {"id": "ngp_sc",   "name": "Nagpur – Secunderabad", "from": "Nagpur", "to": "Secunderabad","route_km": 581, "daily_trains": 100, "kavach_pct": 27, "incidents_5yr": 5},
    {"id": "kanpur_bct","name": "Kanpur – Mumbai",      "from": "Kanpur", "to": "Mumbai",     "route_km": 1419, "daily_trains": 105, "kavach_pct": 5,  "incidents_5yr": 7},
]


def with_geometry(c: dict) -> dict:
    return {**c, "from_ll": list(_C[c["from"]]), "to_ll": list(_C[c["to"]])}
