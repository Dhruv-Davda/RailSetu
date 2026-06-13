"""
M2.1 — Corridor network model for Delhi → Kanpur (NDLS → CNB).

Stations are nodes, the track between consecutive stations is a section (edge).
A committed, representative timetable of real trains runs over it. This is the
M2 analogue of M1's station_graph fixture: a frozen, network-free snapshot so the
demo never depends on a live call. Train numbers/names and the running order are
realistic; exact minutes are a representative schedule (label it as such).

Geography is down-direction only (NDLS → CNB) — a single, busy direction is
enough to show catch-up, holding, and overtake conflicts, and keeps the model
honest and legible. Up-direction is a future extension.
"""
from __future__ import annotations

# Ordered stations along the corridor (km = distance from New Delhi).
# `loop` = the station has loop lines / spare platforms, so a train can be held
# there to let another overtake (the lever the optimizer uses).
STATIONS = [
    {"code": "NDLS", "name": "New Delhi",      "km": 0,   "platforms": 16, "loop": True},
    {"code": "GZB",  "name": "Ghaziabad",      "km": 25,  "platforms": 6,  "loop": True},
    {"code": "ALJN", "name": "Aligarh Jn",     "km": 131, "platforms": 7,  "loop": True},
    {"code": "TDL",  "name": "Tundla Jn",      "km": 204, "platforms": 6,  "loop": True},
    {"code": "ETW",  "name": "Etawah",         "km": 281, "platforms": 4,  "loop": True},
    {"code": "CNB",  "name": "Kanpur Central", "km": 440, "platforms": 10, "loop": True},
]

HEADWAY_MIN = 5.0          # minimum separation between trains on one section
STOP_DWELL_MIN = 2.0       # time a stopping train holds a platform
TERMINAL_DWELL_MIN = 4.0   # at the final station

# Train-type → priority weight. Higher = more important to keep on time; the
# optimizer minimises priority-weighted total delay, so it protects a Rajdhani
# over a passenger.
TYPE_PRIORITY = {
    "RAJDHANI": 10, "SHATABDI": 9, "DURONTO": 9, "SUPERFAST": 7,
    "MAIL": 6, "EXPRESS": 5, "PASSENGER": 2, "MEMU": 2, "GOODS": 1,
}

# The corridor's train sheet for the demo window (~06:00–07:20 departures from
# NDLS). The PLANNED timetable is well sequenced — faster trains pathed ahead of
# slower ones and adequately spaced — so a normal run is nearly conflict-free.
# A disruption is what breaks the sequence (e.g. a fast train delayed at the start
# drops into the slow pack and gets throttled behind trains it cannot overtake
# mid-section), and that is exactly what the rescheduling optimizer recovers.
# stops: "all" = halts at every corridor station; otherwise the listed codes
# (the train passes through the rest without stopping).
TRAINS = [
    {"no": "12302", "name": "Howrah Rajdhani",        "type": "RAJDHANI",  "speed": 95, "dep": "06:00", "stops": ["NDLS", "CNB"]},
    {"no": "12274", "name": "Howrah Duronto",         "type": "DURONTO",   "speed": 90, "dep": "06:10", "stops": ["NDLS", "CNB"]},
    {"no": "12004", "name": "Lucknow Shatabdi",       "type": "SHATABDI",  "speed": 92, "dep": "06:20", "stops": ["NDLS", "CNB"]},
    {"no": "12555", "name": "Gorakhdham Express",     "type": "SUPERFAST", "speed": 78, "dep": "06:31", "stops": ["NDLS", "GZB", "ALJN", "CNB"]},
    {"no": "12230", "name": "Lucknow Mail",           "type": "MAIL",      "speed": 70, "dep": "06:42", "stops": ["NDLS", "ALJN", "TDL", "CNB"]},
    {"no": "12420", "name": "Gomti Express",          "type": "EXPRESS",   "speed": 68, "dep": "06:53", "stops": ["NDLS", "GZB", "ALJN", "TDL", "ETW", "CNB"]},
    {"no": "14163", "name": "Sangam Express",         "type": "EXPRESS",   "speed": 66, "dep": "07:04", "stops": "all"},
    {"no": "15484", "name": "Sikkim Mahananda",       "type": "EXPRESS",   "speed": 64, "dep": "07:14", "stops": ["NDLS", "GZB", "ALJN", "ETW", "CNB"]},
    {"no": "54471", "name": "Delhi–Kanpur Passenger", "type": "PASSENGER", "speed": 50, "dep": "07:24", "stops": "all"},
]


def _parse_hhmm(s: str) -> float:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def hhmm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def sections() -> list[dict]:
    """Track sections between consecutive stations."""
    out = []
    for a, b in zip(STATIONS, STATIONS[1:]):
        out.append({
            "from": a["code"], "to": b["code"],
            "km": b["km"] - a["km"],
            "headway_min": HEADWAY_MIN,
            "line": "double",
        })
    return out


def station_index() -> dict[str, int]:
    return {s["code"]: i for i, s in enumerate(STATIONS)}


def running_time_min(km: float, speed_kmph: float) -> float:
    return km / speed_kmph * 60.0


def train_priority(t: dict) -> int:
    return TYPE_PRIORITY.get(t["type"], 5)


def stops_at(t: dict, code: str) -> bool:
    return t["stops"] == "all" or code in t["stops"]


def corridor_meta() -> dict:
    return {
        "name": "New Delhi → Kanpur Central",
        "from": "NDLS", "to": "CNB",
        "length_km": STATIONS[-1]["km"],
        "n_stations": len(STATIONS),
        "n_trains": len(TRAINS),
        "headway_min": HEADWAY_MIN,
        "source": "Representative timetable snapshot (real trains; representative timings)",
    }


def trains_with_priority() -> list[dict]:
    out = []
    for t in TRAINS:
        out.append({**t, "priority": train_priority(t), "dep_min": _parse_hhmm(t["dep"])})
    return out
