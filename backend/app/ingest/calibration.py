"""
Model calibration from measured crowd density.

The corridor capacities in the sim are textbook Fruin/HCM constants. Real
stations deviate (luggage, counter-flow, obstructions). When a measured-density
feed is available, this module nudges the model toward reality:

  scale = clamp(predicted_density / observed_density, min, max)

  observed > predicted  ->  scale < 1  : the model was too optimistic about that
                                         node, so tighten the capacity of the flat
                                         corridors feeding it (people back up more).
  observed < predicted  ->  scale > 1  : loosen them.

Stair / FOB edges are left alone — their throughput is fixed geometry, not a
calibration free-parameter. The result is a `{(u, v): scale}` dict fed straight
into `simulate(..., mitigations={"capacity_scale": ...})`, so the physics core
needs no changes.

This is a deliberately simple, transparent feedback rule (a calibration *hook*,
not an optimiser). A production version would fit capacities over many
(predicted, observed) pairs across time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import Settings

from .crowd_sensing import CrowdObservation

log = logging.getLogger("railsetu.calibration")


@dataclass
class CalibrationState:
    """In-memory current calibration, merged into every sim when enabled."""
    capacity_scale: dict = field(default_factory=dict)  # (u, v) -> scale
    observations: int = 0
    edges_adjusted: int = 0
    updated_at: str | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "active": bool(self.capacity_scale),
            "observations": self.observations,
            "edges_adjusted": self.edges_adjusted,
            "updated_at": self.updated_at,
            "note": self.note,
        }


def compute_capacity_scale(G, predicted_node_density: dict,
                           observations: list[CrowdObservation],
                           settings: Settings) -> dict:
    """Return {(u, v): scale} corrections from observed vs predicted density."""
    scale: dict = {}
    lo, hi = settings.calibration_min_scale, settings.calibration_max_scale
    for obs in observations:
        if obs.node not in G or obs.density <= 0.05:
            continue
        predicted = predicted_node_density.get(obs.node, 0.0)
        ratio = predicted / obs.density if obs.density else 1.0
        ratio = max(lo, min(hi, ratio))
        for nb in G.neighbors(obs.node):
            edge = G.edges[obs.node, nb]
            if edge["kind"] == "steps":      # fixed geometry, not tunable
                continue
            scale[(obs.node, nb)] = round(ratio, 3)
    return scale
