"""
M6 service — Kavach coverage map (M6.1) and gap × accident correlation (M6.3).

Risk exposure proxy = daily_trains × (1 − kavach_pct/100): "unprotected train
movements per day" on a corridor. It is deliberately simple and transparent. All
outputs are INDICATIVE (see data.py) and the payloads say so, so the UI can label
them honestly.
"""
from __future__ import annotations

from .data import CORRIDORS, with_geometry

DISCLAIMER = ("Indicative analysis on representative public data — Kavach figures "
              "are news-sourced and approximate; accident data is largely zone-level. "
              "Direction is sound; specific numbers are not official.")


def _status(kavach_pct: float) -> str:
    if kavach_pct >= 75:
        return "equipped"
    if kavach_pct >= 25:
        return "partial"
    return "none"


def _risk_exposure(c: dict) -> float:
    return round(c["daily_trains"] * (1 - c["kavach_pct"] / 100.0), 1)


def coverage_payload() -> dict:
    corridors = []
    for c in CORRIDORS:
        g = with_geometry(c)
        g["status"] = _status(c["kavach_pct"])
        g["risk_exposure"] = _risk_exposure(c)
        corridors.append(g)
    corridors.sort(key=lambda x: x["risk_exposure"], reverse=True)

    counts = {"equipped": 0, "partial": 0, "none": 0}
    for c in corridors:
        counts[c["status"]] += 1
    # Traffic-weighted national coverage (share of train-movements protected).
    tot_tr = sum(c["daily_trains"] for c in corridors)
    protected = sum(c["daily_trains"] * c["kavach_pct"] / 100.0 for c in corridors)
    return {
        "disclaimer": DISCLAIMER,
        "corridors": corridors,
        "summary": {
            "n_corridors": len(corridors),
            "status_counts": counts,
            "traffic_weighted_coverage_pct": round(protected / tot_tr * 100, 1) if tot_tr else 0,
            "total_daily_trains": tot_tr,
        },
    }


def _pearson(xs, ys) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(cov / (vx * vy), 2) if vx and vy else 0.0


def correlation_payload() -> dict:
    enriched = []
    for c in CORRIDORS:
        enriched.append({**c, "status": _status(c["kavach_pct"]),
                         "risk_exposure": _risk_exposure(c)})
    enriched.sort(key=lambda x: x["risk_exposure"], reverse=True)

    total_risk = sum(c["risk_exposure"] for c in enriched) or 1.0
    unequipped = [c for c in enriched if c["kavach_pct"] < 25]
    unequipped.sort(key=lambda x: x["risk_exposure"], reverse=True)

    # Headline: the top unequipped corridors and their share of total risk exposure.
    top = unequipped[: min(8, len(unequipped))]
    top_share = round(sum(c["risk_exposure"] for c in top) / total_risk * 100, 1)
    avg_kavach_top = round(sum(c["kavach_pct"] for c in top) / len(top), 1) if top else 0

    # Indicative correlation: more Kavach ↔ fewer incidents.
    r = _pearson([c["kavach_pct"] for c in enriched],
                 [c["incidents_5yr"] for c in enriched])
    low = [c for c in enriched if c["kavach_pct"] < 25]
    high = [c for c in enriched if c["kavach_pct"] >= 75]
    avg_inc_low = round(sum(c["incidents_5yr"] for c in low) / len(low), 1) if low else 0
    avg_inc_high = round(sum(c["incidents_5yr"] for c in high) / len(high), 1) if high else 0

    return {
        "disclaimer": DISCLAIMER,
        "headline": {
            "n_corridors": len(top),
            "risk_share_pct": top_share,
            "avg_kavach_pct": avg_kavach_top,
            "text": (f"These {len(top)} high-traffic corridors carry ~{top_share}% of "
                     f"national collision-risk exposure and average just "
                     f"{avg_kavach_top}% Kavach coverage."),
        },
        "ranked": enriched,
        "top_unequipped": top,
        "incident_comparison": {
            "low_coverage_avg_incidents": avg_inc_low,
            "high_coverage_avg_incidents": avg_inc_high,
            "pearson_kavach_vs_incidents": r,
            "interpretation": ("Negative correlation: corridors with more Kavach "
                               "coverage show fewer reported incidents (indicative)."),
        },
    }
