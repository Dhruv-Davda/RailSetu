"""
Where a policy change was made from.

A change register answers who and why; this adds where. On a railway that is
not incidental — an amendment raised from the station it governs reads
differently from one raised from head office, and the record should be able to
tell them apart.

Two rules, both deliberate:

  * Coordinates come from the browser's geolocation API, with the author's
    explicit permission. If permission is refused or the device cannot fix a
    position, the version records that plainly. An approximate position guessed
    from an IP address would be a fabrication dressed as evidence, and a
    register that fabricates is worse than one that admits a gap.

  * The client address is recorded alongside, because it is what the server
    actually observed. It corroborates the coordinates without pretending to
    be them.
"""
from __future__ import annotations

from datetime import datetime, timezone

MAX_ACCURACY_M = 100_000      # beyond ~100 km a "coordinate" is not a location


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def normalise(payload: dict | None, client_ip: str | None = None) -> dict:
    """Turn whatever the browser sent into a record we are willing to store."""
    seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out: dict = {"client_ip": client_ip or None, "recorded_at": seen_at}

    if not isinstance(payload, dict):
        return {**out, "available": False, "reason": "not provided"}

    if payload.get("available") is False or "reason" in payload and "latitude" not in payload:
        return {**out, "available": False,
                "reason": str(payload.get("reason") or "not provided")[:120]}

    lat, lon = payload.get("latitude"), payload.get("longitude")
    if not (_num(lat) and _num(lon)) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return {**out, "available": False, "reason": "no valid coordinates supplied"}

    acc = payload.get("accuracy_m")
    if _num(acc) and acc > MAX_ACCURACY_M:
        # A fix this coarse is not a location. Recording the coordinate anyway
        # would put a precise-looking pin on the map for a position that could
        # be a hundred kilometres out.
        return {**out, "available": False,
                "reason": f"position too imprecise (±{round(acc):,} m)"}
    if not _num(acc) or acc < 0:
        acc = None

    return {
        **out,
        "available": True,
        "latitude": round(float(lat), 6),
        "longitude": round(float(lon), 6),
        "accuracy_m": round(float(acc)) if acc is not None else None,
        "source": "browser geolocation",
        "captured_at": str(payload.get("captured_at") or seen_at)[:40],
    }


def describe(loc: dict | None) -> str:
    """One line, for logs."""
    if not loc or not loc.get("available"):
        return f"location unavailable ({(loc or {}).get('reason', 'not provided')})"
    acc = f" ±{loc['accuracy_m']} m" if loc.get("accuracy_m") is not None else ""
    return f"{loc['latitude']:.5f}, {loc['longitude']:.5f}{acc}"
