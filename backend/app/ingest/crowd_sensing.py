"""
Measured-crowd ingestion.

The simulator predicts density; this is where *observed* density comes in so the
model can be checked and calibrated against reality. A production sensor wraps:

  * CCTV crowd-counting CV (e.g. CSRNet-style density maps over RailTel VSS feeds), or
  * anonymised WiFi / AFC-gate counts.

In every case it emits AGGREGATE density per zone only — never identifiable
individuals (matches the project's privacy stance). The stub below reads optional
observations from a JSON fixture so the calibration path runs end-to-end without
that hardware; swap in a real sensor by implementing `CrowdSensor.read`.
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings

log = logging.getLogger("railsetu.crowd")


@dataclass
class CrowdObservation:
    node: str            # graph node id the measurement covers
    density: float       # measured persons / m^2 (AGGREGATE only)
    source: str = "stub"
    observed_at: str | None = None


class CrowdSensor(ABC):
    @abstractmethod
    def read(self) -> list[CrowdObservation]:
        """Latest measured densities. Empty list = no data this cycle."""

    def health(self) -> dict:
        return {"sensor": type(self).__name__, "status": "ok"}


class NullCrowdSensor(CrowdSensor):
    """No measured-crowd feed configured."""

    def read(self) -> list[CrowdObservation]:
        return []

    def health(self) -> dict:
        return {"sensor": "NullCrowdSensor", "status": "disabled"}


class StubCrowdSensor(CrowdSensor):
    """Reads observations from a JSON fixture (see fixtures/crowd_observations.sample.json).

    Stands in for a real CCTV/WiFi feed so calibration can be exercised.
    """

    def __init__(self, settings: Settings):
        self.path = settings.crowd_sensor_fixture

    def read(self) -> list[CrowdObservation]:
        if not self.path or not os.path.exists(self.path):
            return []
        try:
            raw = json.load(open(self.path))
        except (OSError, ValueError) as exc:
            log.warning("crowd fixture read failed (%s): %s", self.path, exc)
            return []
        now = datetime.now(timezone.utc).isoformat()
        out = []
        for o in raw.get("observations", []):
            try:
                out.append(CrowdObservation(
                    node=str(o["node"]), density=float(o["density"]),
                    source=o.get("source", "stub"),
                    observed_at=o.get("observed_at", now),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("skipping bad observation %r: %s", o, exc)
        return out

    def health(self) -> dict:
        return {
            "sensor": "StubCrowdSensor",
            "status": "ok" if self.path and os.path.exists(self.path) else "no-fixture",
            "fixture": self.path or None,
        }


def get_crowd_sensor(settings: Settings) -> CrowdSensor:
    if settings.crowd_sensor == "stub":
        return StubCrowdSensor(settings)
    return NullCrowdSensor()
