"""
Thin client over a third-party (RapidAPI) Indian Railways *live-station* API.

These endpoints are NTES scrapers, so:
  * field names differ between providers -> all parsing is funnelled through
    `normalise_arrivals`, the one method you edit when swapping providers;
  * they are rate-limited / metered -> responses are cached for a TTL;
  * they fail intermittently -> requests retry with backoff and raise a typed
    `RailApiError` the caller can fall back on.

No passenger counts are returned by these APIs — only which train is arriving on
which platform. Turning that into a crowd size is the estimation step, done in
app/demand/live.py (and ultimately replaced by PRS/UTS or CCTV).
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import Settings

log = logging.getLogger("railsetu.rail_api")


class RailApiError(RuntimeError):
    """Live rail data could not be fetched."""


def _clean_platform(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    # Common junk: "-", "PF 5", "Platform No. 5", "5/6".
    if s in ("", "-", "0", "NA", "N/A", "--"):
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits


_SPECIAL_HINTS = ("special", "spl", "festival", "kumbh", "mela", "puja", "holiday")


def _is_special(train_name: str) -> bool:
    n = (train_name or "").lower()
    return any(h in n for h in _SPECIAL_HINTS)


class RailApiClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._cache: dict = {}  # (path, params) -> (fetched_at, json)

    @property
    def configured(self) -> bool:
        return bool(self.s.rail_api_key)

    def _headers(self) -> dict:
        return {
            "X-RapidAPI-Key": self.s.rail_api_key,
            "X-RapidAPI-Host": self.s.rail_api_host,
            "accept": "application/json",
        }

    def _get(self, path: str, params: dict) -> dict:
        cache_key = (path, tuple(sorted(params.items())))
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < self.s.rail_api_cache_ttl_s:
            return cached[1]

        url = self.s.rail_api_base_url.rstrip("/") + path
        last_exc = None
        for attempt in range(self.s.rail_api_retries + 1):
            try:
                resp = httpx.get(
                    url, params=params, headers=self._headers(),
                    timeout=self.s.rail_api_timeout_s,
                )
                resp.raise_for_status()
                data = resp.json()
                self._cache[cache_key] = (now, data)
                return data
            except Exception as exc:  # noqa: BLE001 - one fallback path for any failure
                last_exc = exc
                log.warning("rail api attempt %d/%d failed: %s",
                            attempt + 1, self.s.rail_api_retries + 1, exc)
                if attempt < self.s.rail_api_retries:
                    time.sleep(min(0.5 * (attempt + 1), 2.0))
        raise RailApiError(f"rail api request failed: {last_exc}")

    def live_station(self, station_code: str) -> list[dict]:
        """Live (delay-adjusted) arrivals board, normalised. Often sparse/empty."""
        if not self.configured:
            raise RailApiError("rail_api_key is not configured")
        params = {
            "fromStationCode": station_code,
            "hours": self.s.rail_api_window_hours,
        }
        raw = self._get(self.s.rail_api_live_path, params)
        return self.normalise_arrivals(raw)

    def trains_by_station(self, station_code: str) -> list[dict]:
        """Full scheduled timetable for `station_code` — trains that ARRIVE
        (terminating + passing), normalised. No platform / no counts in the feed.
        """
        if not self.configured:
            raise RailApiError("rail_api_key is not configured")
        raw = self._get(self.s.rail_api_timetable_path, {"stationCode": station_code})
        return self.normalise_timetable(raw)

    @staticmethod
    def normalise_timetable(raw) -> list[dict]:
        """Flatten getTrainsByStation into arriving-train records.

        Shape: data.{originating|passing|destination}[] with trainNo / trainName /
        arrivalTime / departureTime. We take `destination` (terminates here) and
        `passing` (arrives then continues) as the alighting demand; `originating`
        trains have no arrival, so they're skipped.
        """
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, dict):
            return []
        out: list[dict] = []
        for category in ("destination", "passing"):
            for t in data.get(category) or []:
                if not isinstance(t, dict):
                    continue
                name = str(t.get("trainName") or "")
                out.append({
                    "train_no": str(t.get("trainNo") or t.get("train_no") or ""),
                    "train_name": name,
                    "train_type": "",                     # not provided; inferred from name
                    "arrival": str(t.get("arrivalTime") or ""),
                    "category": category,
                    "platform": "",                       # not provided by this API
                    "special": _is_special(name),
                })
        return out

    @staticmethod
    def normalise_arrivals(raw) -> list[dict]:
        """Map provider JSON to [{train_no, train_name, train_type, platform, special}].

        Tolerant of field-name variation between RapidAPI providers. Edit HERE
        (and only here) to support a different endpoint shape.

        NOTE on irctc1 `getLiveStation`: it returns the *schedule* of trains at the
        station in the next N hours — train number/name/type and arrival time, but
        NO platform number and NO passenger count. Platform is therefore usually
        empty here and gets estimated downstream (app/demand/live.py).
        """
        data = raw.get("data") if isinstance(raw, dict) else raw
        if isinstance(data, dict):
            data = data.get("trains") or data.get("arrivals") or data.get("stationFrom") or []
        out: list[dict] = []
        for t in data or []:
            if not isinstance(t, dict):
                continue
            name = str(t.get("train_name") or t.get("name") or t.get("trainName") or "")
            ttype = str(t.get("trainType") or t.get("train_type") or "")
            plat = (t.get("platform_number") or t.get("platform")
                    or t.get("expected_platform") or t.get("platformNumber"))
            arr = t.get("arrivalTime") or t.get("arrival_time") or t.get("eta") or ""
            out.append({
                "train_no": str(t.get("train_number") or t.get("train_no")
                                 or t.get("number") or t.get("trainNumber") or ""),
                "train_name": name,
                "train_type": ttype,
                "arrival": str(arr),
                "platform": _clean_platform(plat),
                "special": _is_special(f"{name} {ttype}"),
            })
        return out
