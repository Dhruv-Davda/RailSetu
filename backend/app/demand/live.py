"""
Live demand provider — turns a third-party rail feed into simulator demand.

Two feeds, selected by `rail_api_source`:
  * "timetable" (getTrainsByStation) — the full scheduled board, filtered here to
    trains arriving in the next N hours (IST). Populated + reliable, NOT delay-adjusted.
  * "liveboard" (getLiveStation) — delay-adjusted live board, but often empty / 429s.

NEITHER feed returns a platform number or a passenger count. So, honestly:
  * platform is ESTIMATED (round-robin across the station's platforms), and
  * crowd load is ESTIMATED (base × train-type × special surge).
The train list and arrival times ARE real. Replace the estimates with PRS/UTS
(counts) or CCTV (measured density) for production accuracy.

If the feed errors and `live_fallback_to_fixture` is set, a committed fixture is
replayed (flagged in `meta`) so the control room never goes blank.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.clients.rail_api import RailApiClient, RailApiError
from app.config import Settings
from app.m1_crowd import scenarios as scn

from .base import Demand, DemandProvider, DemandScenario
from .fixtures import FixtureDemandProvider

log = logging.getLogger("railsetu.demand.live")

LIVE_KEY = "live_now"
IST = timezone(timedelta(hours=5, minutes=30))  # the timetable is in IST


def _platform_number_index() -> dict[str, str]:
    """Expand the fixture's "14;15" -> {"14": node, "15": node} for live lookup."""
    idx: dict[str, str] = {}
    for ref, node in scn.PLATFORM_NODE.items():
        for num in str(ref).replace("/", ";").split(";"):
            num = num.strip()
            if num:
                idx[num] = node
    return idx


# Train-type → crowd-load multipliers (applied to default_alighting_per_train).
# Matched as substrings against the train type OR name, so "… Express"/"… Local"
# in the name is enough when the feed gives no explicit type.
_TYPE_MULTIPLIER = {
    "RAJDHANI": 1.4, "SHATABDI": 1.2, "DURONTO": 1.4, "TEJAS": 1.2,
    "SUPERFAST": 1.2, "GARIB": 1.3, "EXPRESS": 1.0, "MAIL": 1.1,
    "SPECIAL": 1.0, "PASSENGER": 0.5, "LOCAL": 0.5, "MEMU": 0.5, "EMU": 0.4,
}


def _type_multiplier(hint: str) -> float:
    t = (hint or "").upper()
    for key, mult in _TYPE_MULTIPLIER.items():
        if key in t:
            return mult
    return 1.0


def _parse_hhmm(s: str | None) -> int | None:
    """'09:38' -> minutes-of-day (mod 1440). Non-times ('Source', '--') -> None."""
    s = (s or "").strip()
    if ":" not in s:
        return None
    hh, _, mm = s.partition(":")
    if not (hh.isdigit() and mm.isdigit()) or int(mm) >= 60:
        return None
    return (int(hh) * 60 + int(mm)) % 1440


def _minutes_until(arr_min: int, now_min: int) -> int:
    return (arr_min - now_min) % 1440


class LiveDemandProvider(DemandProvider):
    def __init__(self, settings: Settings, client: RailApiClient | None = None,
                 fallback: DemandProvider | None = None):
        self.s = settings
        self.client = client or RailApiClient(settings)
        self.fallback = fallback or FixtureDemandProvider()
        self._pnum = _platform_number_index()
        # Unique platform nodes, stable order — used to ESTIMATE platform
        # assignment, since no feed provides it.
        self._platform_nodes = list(dict.fromkeys(scn.PLATFORM_NODE.values()))

    def list_scenarios(self) -> list[dict]:
        live = {
            "key": LIVE_KEY,
            "title": f"LIVE — {self.s.station_code} arrivals (next {self.s.rail_api_window_hours}h)",
            "description": ("Real scheduled arrivals from the live feed. Platform + "
                            "crowd load are estimated (the API provides neither)."),
            "total_people": 0,
            "live": True,
        }
        return [live] + self.fallback.list_scenarios()  # fixtures stay available

    def get_scenario(self, key: str | None) -> DemandScenario | None:
        if key not in (None, LIVE_KEY):
            return self.fallback.get_scenario(key)  # explicit fixture request
        try:
            if self.s.rail_api_source == "liveboard":
                records = self.client.live_station(self.s.station_code)
                return self._build(records, endpoint="getLiveStation",
                                   timetable_total=len(records), in_window=len(records))
            records = self.client.trains_by_station(self.s.station_code)
            return self._build_from_timetable(records)
        except RailApiError as exc:
            log.warning("live demand unavailable: %s", exc)
            if not self.s.live_fallback_to_fixture:
                raise
            fb = self.fallback.get_scenario("kumbh_surge")
            if fb:
                fb.source = "fixture_fallback"
                fb.meta = {"live_error": str(exc), "fellback_to": "kumbh_surge"}
            return fb

    # ---- builders ----

    def _build_from_timetable(self, records: list[dict]) -> DemandScenario:
        now_min = (lambda n: n.hour * 60 + n.minute)(datetime.now(IST))
        window_min = self.s.rail_api_window_hours * 60
        upcoming = []
        for r in records:
            am = _parse_hhmm(r.get("arrival"))
            if am is None:
                continue
            d = _minutes_until(am, now_min)
            if d <= window_min:
                upcoming.append((d, r))
        upcoming.sort(key=lambda x: x[0])
        in_window = len(upcoming)
        chosen = [r for _, r in upcoming[:self.s.live_max_trains]]
        if in_window > len(chosen):
            log.info("timetable: %d trains in window, capped to %d (live_max_trains)",
                     in_window, len(chosen))
        return self._build(chosen, endpoint="getTrainsByStation",
                           timetable_total=len(records), in_window=in_window)

    def _build(self, records: list[dict], *, endpoint: str,
               timetable_total: int, in_window: int) -> DemandScenario:
        demands, from_api, estimated = self._make_demands(records)
        return DemandScenario(
            key=LIVE_KEY,
            title=f"LIVE — {self.s.station_code} arrivals (next {self.s.rail_api_window_hours}h)",
            description=("Real scheduled arrivals from the live feed. Passenger load "
                         "is ESTIMATED (the API returns no counts) and platform "
                         "assignment is ESTIMATED (the API returns no platform) — "
                         "calibrate via PRS/UTS or CCTV for real numbers."),
            demands=demands,
            exits=[e for e in scn.DEFAULT_EXITS],
            horizon_s=self.s.live_horizon_s,
            source="live",
            generated_at=datetime.now(timezone.utc).isoformat(),
            meta={
                "endpoint": endpoint,
                "timetable_total": timetable_total,
                "in_window": in_window,
                "used": len(demands),
                "capped": max(0, in_window - len(demands)),
                "window_hours": self.s.rail_api_window_hours,
                "platform_from_api": from_api,
                "platform_estimated": estimated,
                "load": "estimated",
                "platform": "estimated" if estimated and not from_api else "mixed",
            },
        )

    def _make_demands(self, records: list[dict]):
        demands: list[Demand] = []
        from_api = 0       # platform came from the feed (never, with this API)
        estimated = 0      # platform we had to estimate
        rr = 0             # round-robin cursor
        for a in records:
            node = self._pnum.get(a["platform"]) if a.get("platform") else None
            if node:
                from_api += 1
            elif self._platform_nodes:
                node = self._platform_nodes[rr % len(self._platform_nodes)]
                rr += 1
                estimated += 1
            else:
                continue
            mult = _type_multiplier(a.get("train_type") or a.get("train_name", ""))
            load = self.s.default_alighting_per_train * mult
            if a.get("special"):
                load *= self.s.special_train_multiplier
            label = f"{a.get('train_no', '')} {a.get('train_name', '')}".strip()
            demands.append(Demand(platform=node, people=round(load, 1),
                                  duration_s=float(self.s.unload_duration_s), label=label))
        return demands, from_api, estimated

    def health(self) -> dict:
        return {
            "provider": "LiveDemandProvider",
            "configured": self.client.configured,
            "station": self.s.station_code,
            "source": self.s.rail_api_source,
            "base_url": self.s.rail_api_base_url,
        }
