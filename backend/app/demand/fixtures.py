"""
Fixture demand provider — the committed scenarios in app/m1_crowd/scenarios.py.

This is the replay / test / demo path: deterministic, network-free, and the
fallback when a live feed is unavailable.
"""
from __future__ import annotations

from app.m1_crowd import scenarios as scn

from .base import Demand, DemandProvider, DemandScenario


class FixtureDemandProvider(DemandProvider):
    def list_scenarios(self) -> list[dict]:
        return scn.list_scenarios()

    def get_scenario(self, key: str | None) -> DemandScenario | None:
        key = key or "kumbh_surge"
        sc = scn.get_scenario(key)
        if not sc:
            return None
        demands = [
            Demand(
                platform=d["platform"],
                people=float(d["people"]),
                duration_s=float(d["duration_s"]),
                label=d.get("label", ""),
            )
            for d in sc["demands"]
        ]
        return DemandScenario(
            key=key,
            title=sc["title"],
            description=sc["description"],
            demands=demands,
            exits=list(sc["exits"]),
            horizon_s=sc["horizon_s"],
            source="fixture",
        )
