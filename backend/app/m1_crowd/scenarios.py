"""
Demand scenarios for the NDLS flagship demo.

A scenario is a named set of platform demands + the exits people head for. These
are committed fixtures so the live demo never depends on a network call. Each
demand says: N people emerge from a platform over D seconds (a train unloading,
or a surge of intending passengers arriving for a special train).

`kumbh_surge` reproduces the conditions of the Feb 2025 disaster: a very large
crowd concentrated on platform 14/15 (node n24) for Prayagraj specials, released
fast, funnelling onto the narrow foot-over-bridge stairs.
"""

# Exit / dispersal targets (station and metro gates) that are in the routable graph.
DEFAULT_EXITS = ["n114", "n113", "n111", "n96", "n271", "n265", "n262", "n254"]

# Platform node lookup by human ref.
PLATFORM_NODE = {
    "1": "n129", "2;3": "n128", "4;5": "n19", "6;7": "n18",
    "8;9": "n20", "10;11": "n22", "12;13": "n21", "14;15": "n24", "16": "n23",
}

SCENARIOS = {
    "normal_evening": {
        "title": "Normal evening peak",
        "description": "Routine evening: several trains unload moderate crowds across platforms.",
        "exits": DEFAULT_EXITS,
        "horizon_s": 420,
        "demands": [
            {"platform": "n19", "people": 700, "duration_s": 200, "label": "12309 arr P4/5"},
            {"platform": "n18", "people": 550, "duration_s": 200, "label": "12423 arr P6/7"},
            {"platform": "n20", "people": 650, "duration_s": 220, "label": "12015 arr P8/9"},
            {"platform": "n22", "people": 500, "duration_s": 220, "label": "12001 arr P10/11"},
        ],
    },
    "kumbh_surge": {
        "title": "Festival surge — Prayagraj specials (Feb 2025 pattern)",
        "description": (
            "A very large crowd for Maha Kumbh specials concentrates on Platform 14/15 "
            "and is released onto the foot-over-bridge faster than the stairs can pass. "
            "This is the mechanism behind the Feb 2025 NDLS stampede."
        ),
        "exits": DEFAULT_EXITS,
        "horizon_s": 420,
        "demands": [
            {"platform": "n24", "people": 3200, "duration_s": 120, "label": "Kumbh surge P14/15"},
            {"platform": "n21", "people": 1600, "duration_s": 150, "label": "Spill-over P12/13"},
            {"platform": "n23", "people": 1200, "duration_s": 150, "label": "Platform 16 crowd"},
            {"platform": "n20", "people": 1000, "duration_s": 180, "label": "12015 arr P8/9"},
        ],
    },
    "double_arrival": {
        "title": "Simultaneous arrivals + platform change",
        "description": "Two trains arrive together and a late platform-change announcement reverses flow on a shared FOB.",
        "exits": DEFAULT_EXITS,
        "horizon_s": 300,
        "demands": [
            {"platform": "n21", "people": 1800, "duration_s": 90, "label": "Train A P12/13"},
            {"platform": "n24", "people": 1900, "duration_s": 90, "label": "Train B P14/15"},
            {"platform": "n22", "people": 1300, "duration_s": 120, "label": "Train C P10/11"},
        ],
    },
}


def get_scenario(key):
    return SCENARIOS.get(key)


def list_scenarios():
    return [
        {"key": k, "title": v["title"], "description": v["description"],
         "total_people": sum(d["people"] for d in v["demands"])}
        for k, v in SCENARIOS.items()
    ]
