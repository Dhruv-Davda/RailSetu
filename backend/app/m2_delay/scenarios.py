"""
M2 disruption scenarios — a primary disruption injected into the corridor, from
which the simulator propagates the cascade. Committed fixtures so the demo is
deterministic.

A disruption is one of:
  * a station delay  {"train", "station_index", "delay_min"} — a train held N min
    at a station; or
  * a re-path        {"train", "dep_override"} (minutes-of-day) — a train running
    late from an upstream section now entering the corridor out of its planned
    slot, e.g. a slow passenger train pathed ahead of the express fleet.

station_index runs NDLS(0) → GZB(1) → ALJN(2) → TDL(3) → ETW(4) → CNB(5).
"""

SCENARIOS = {
    "normal_running": {
        "title": "Normal running (planned timetable)",
        "description": (
            "The corridor as planned: nine trains, fastest pathed ahead and "
            "adequately spaced. Almost no conflict — the reference for a good day."
        ),
        "disruption": None,
    },
    "passenger_ahead": {
        "title": "Slow passenger train pathed ahead of the express fleet",
        "description": (
            "The 54471 Delhi–Kanpur Passenger (50 km/h) is running late from an "
            "upstream section and ends up on the main line just ahead of the morning "
            "express fleet — the Rajdhani, Duronto and Shatabdi (90+ km/h). On single "
            "track they cannot overtake mid-section, so the whole fleet is throttled "
            "to passenger speed. A documented cause of express delays in India."
        ),
        # 06:05 — just behind the Rajdhani, ahead of everyone else.
        "disruption": {"train": "54471", "dep_override": 365},
    },
    "passenger_ahead_fault": {
        "title": "Pathed-ahead passenger then fails at Aligarh",
        "description": (
            "As above, but the passenger train additionally develops a fault and is "
            "held 18 min at Aligarh Jn — deepening the cascade behind it mid-corridor."
        ),
        "disruption": {"train": "54471", "dep_override": 365,
                       "station_index": 2, "delay_min": 18},
    },
}


def list_scenarios() -> list[dict]:
    return [
        {"key": k, "title": v["title"], "description": v["description"],
         "disruption": v["disruption"]}
        for k, v in SCENARIOS.items()
    ]


def get_scenario(key: str):
    return SCENARIOS.get(key)
