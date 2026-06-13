"""
The DemandProvider seam.

The simulation core consumes a simple shape: "N people emerge from platform P
over D seconds, heading for these exits, over this horizon." Everything upstream
of that — committed fixtures, a live train feed, or (later) measured crowd
counts — is just a different `DemandProvider`. Swapping the data source never
touches the physics in app/m1_crowd/simulation.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Demand:
    platform: str          # graph node id the crowd emerges from
    people: float
    duration_s: float
    label: str = ""


@dataclass
class DemandScenario:
    key: str
    title: str
    description: str
    demands: list[Demand]
    exits: list[str]
    horizon_s: int
    source: str = "fixture"          # "fixture" | "live" | "fixture_fallback"
    generated_at: str | None = None  # ISO8601 for live; None for fixtures
    meta: dict = field(default_factory=dict)

    @property
    def total_people(self) -> float:
        return round(sum(d.people for d in self.demands), 1)


class DemandProvider(ABC):
    """Returns demand scenarios for the simulator to run."""

    @abstractmethod
    def list_scenarios(self) -> list[dict]:
        """Lightweight catalogue for the UI dropdown."""

    @abstractmethod
    def get_scenario(self, key: str | None) -> DemandScenario | None:
        """Resolve a scenario by key (None = the provider's default)."""

    def health(self) -> dict:
        return {"provider": type(self).__name__, "status": "ok"}
