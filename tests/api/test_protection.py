"""
Protection coverage: the corridor map and the gap-vs-incident analysis.

This module makes a POLICY claim in public ("these corridors carry N% of
collision-risk exposure at M% coverage"), so what matters is that the arithmetic
behind the claim is sound and that the caveat travels with it. A coverage figure
that silently changed definition, or a correlation quoted without its
disclaimer, would be worse than no figure at all.
"""
from harness import bootstrap, Report

bootstrap("protection")

from fastapi.testclient import TestClient           # noqa: E402
from app.main import app                            # noqa: E402
from app.policy.context import current              # noqa: E402

r = Report("PROTECTION COVERAGE")
c = TestClient(app)

cov = c.get("/api/m6/coverage").json()
cor = c.get("/api/m6/correlation").json()
corr = cov["corridors"]
summ = cov["summary"]

r.section("1. THE CORRIDOR SET")
r.check("corridors are returned", len(corr) >= 10, len(corr))
r.check("the count agrees with the summary", summ["n_corridors"] == len(corr))
r.check("every corridor is named", all(x.get("name") for x in corr))
r.check("every corridor has two endpoints to draw between",
        all(len(x.get("from_ll", [])) == 2 and len(x.get("to_ll", [])) == 2 for x in corr))
pts = [p for x in corr for p in (x["from_ll"], x["to_ll"])]
r.check("every endpoint is inside India's bounding box",
        all(6 < a < 37 and 68 < b < 98 for a, b in pts),
        [p for p in pts if not (6 < p[0] < 37 and 68 < p[1] < 98)][:3])
r.check("no corridor starts where it ends",
        all(x["from_ll"] != x["to_ll"] for x in corr))
r.check("every corridor carries its route length", all(x.get("route_km", 0) > 0 for x in corr))
r.check("every corridor carries daily traffic", all(x.get("daily_trains", 0) > 0 for x in corr))
r.check("daily traffic sums to the reported total",
        sum(x["daily_trains"] for x in corr) == summ["total_daily_trains"],
        (sum(x["daily_trains"] for x in corr), summ["total_daily_trains"]))
r.check("every corridor has a coverage percentage",
        all(0 <= x.get("kavach_pct", -1) <= 100 for x in corr))
r.check("corridor names are unique", len({x["name"] for x in corr}) == len(corr))

r.section("2. STATUS IS DERIVED FROM POLICY, NOT HARD-CODED")
eq = current().kavach_equipped_pct
pa = current().kavach_partial_pct
r.check("the equipped threshold comes from policy", 0 < eq <= 100, eq)
r.check("the partial threshold comes from policy", 0 < pa < eq, (pa, eq))


def expected(pct):
    if pct >= eq:
        return "equipped"
    return "partial" if pct >= pa else "none"


wrong = [(x["name"], x["kavach_pct"], x["status"], expected(x["kavach_pct"]))
         for x in corr if x["status"] != expected(x["kavach_pct"])]
r.check("every corridor's status follows the thresholds in force", not wrong, wrong[:3])
r.check("the status tally agrees with the corridors",
        {k: sum(1 for x in corr if x["status"] == k)
         for k in ("equipped", "partial", "none")} == summ["status_counts"],
        summ["status_counts"])
r.check("only the three defined statuses appear",
        {x["status"] for x in corr} <= {"equipped", "partial", "none"},
        sorted({x["status"] for x in corr}))

r.section("3. COVERAGE IS TRAFFIC-WEIGHTED, AND SAYS SO")
total = sum(x["daily_trains"] for x in corr)
weighted = sum(x["kavach_pct"] * x["daily_trains"] for x in corr) / total
r.check("the headline coverage is the traffic-weighted mean",
        abs(summ["traffic_weighted_coverage_pct"] - round(weighted, 1)) < 0.15,
        (summ["traffic_weighted_coverage_pct"], round(weighted, 1)))
r.check("the weighted mean lies within the range it averages",
        min(x["kavach_pct"] for x in corr) <= weighted <= max(x["kavach_pct"] for x in corr),
        (min(x["kavach_pct"] for x in corr), round(weighted, 1),
         max(x["kavach_pct"] for x in corr)))
# Weighting is what makes the figure honest: a busy unprotected trunk route must
# count for more than a quiet one. Verify the weights are the traffic, by
# re-weighting one corridor and checking the headline follows.
heavy = max(corr, key=lambda x: x["daily_trains"])
shifted = sum(x["kavach_pct"] * (x["daily_trains"] * (2 if x is heavy else 1))
              for x in corr) / sum(x["daily_trains"] * (2 if x is heavy else 1) for x in corr)
r.check("doubling the busiest corridor's traffic moves the weighted figure toward it",
        (shifted > weighted) == (heavy["kavach_pct"] > weighted),
        (heavy["name"], heavy["kavach_pct"], round(weighted, 2), round(shifted, 2)))
r.check("the coverage figure is a percentage",
        0 <= summ["traffic_weighted_coverage_pct"] <= 100)

r.section("4. RISK EXPOSURE RANKS THE UNPROTECTED BUSY ROUTES FIRST")
risky = [x for x in corr if x.get("risk_exposure") is not None]
r.check("risk exposure is computed per corridor", len(risky) == len(corr))
r.check("exposure is never negative", all(x["risk_exposure"] >= 0 for x in risky))
if len(risky) > 2:
    top = max(risky, key=lambda x: x["risk_exposure"])
    bot = min(risky, key=lambda x: x["risk_exposure"])
    r.check("the most exposed route is busier or less protected than the least",
            top["daily_trains"] >= bot["daily_trains"] or top["kavach_pct"] <= bot["kavach_pct"],
            ((top["name"], top["daily_trains"], top["kavach_pct"]),
             (bot["name"], bot["daily_trains"], bot["kavach_pct"])))
    r.check("a fully equipped corridor carries less exposure than an unequipped twin",
            all(a["risk_exposure"] <= b["risk_exposure"]
                for a in risky for b in risky
                if a["daily_trains"] == b["daily_trains"] and a["kavach_pct"] > b["kavach_pct"]))

r.section("5. THE PUBLIC HEADLINE ADDS UP")
h = cor["headline"]
r.check("the headline names how many corridors it is about", h["n_corridors"] > 0, h["n_corridors"])
r.check("it is a subset of the mapped corridors", h["n_corridors"] <= len(corr))
r.check("the risk share is a percentage", 0 < h["risk_share_pct"] <= 100, h["risk_share_pct"])
r.check("the quoted average coverage is a percentage", 0 <= h["avg_kavach_pct"] <= 100,
        h["avg_kavach_pct"])
r.check("the sentence quotes its own numbers",
        str(h["n_corridors"]) in h["text"]
        and f"{h['risk_share_pct']}" in h["text"]
        and f"{h['avg_kavach_pct']}" in h["text"], h["text"])
r.check("the corridors it is about are the most exposed ones",
        h["risk_share_pct"] > h["n_corridors"] / len(corr) * 100,
        (h["risk_share_pct"], round(h["n_corridors"] / len(corr) * 100, 1)))

r.section("6. THE CORRELATION IS REPORTED HONESTLY")
ic = cor["incident_comparison"]
rho = ic["pearson_kavach_vs_incidents"]
r.check("a correlation coefficient is given", -1 <= rho <= 1, rho)
r.check("more coverage correlates with fewer incidents", rho < 0, rho)
r.check("both groups are reported",
        ic["low_coverage_avg_incidents"] is not None
        and ic["high_coverage_avg_incidents"] is not None)
r.check("the low-coverage group averages more incidents",
        ic["low_coverage_avg_incidents"] > ic["high_coverage_avg_incidents"],
        (ic["low_coverage_avg_incidents"], ic["high_coverage_avg_incidents"]))
r.check("the interpretation is labelled indicative, not proven",
        "indicative" in ic["interpretation"].lower(), ic["interpretation"])
r.check("it says correlation, and does not claim causation",
        "correlation" in ic["interpretation"].lower()
        and "caus" not in ic["interpretation"].lower(), ic["interpretation"])
r.check("the direction stated matches the sign of the coefficient",
        ("negative" in ic["interpretation"].lower()) == (rho < 0), (rho, ic["interpretation"][:40]))

r.section("6b. THE RANKED LIST AND THE WORST OFFENDERS")
ranked = cor["ranked"]
r.check("every corridor is ranked", len(ranked) == len(corr), (len(ranked), len(corr)))
r.check("the ranking is ordered by exposure, worst first",
        [x["risk_exposure"] for x in ranked]
        == sorted((x["risk_exposure"] for x in ranked), reverse=True))
top = cor["top_unequipped"]
r.check("a shortlist of unequipped corridors is published", len(top) > 0, len(top))
r.check("every one of them is unprotected — not merely partial",
        all(x["status"] == "none" for x in top),
        [(x["name"], x["status"]) for x in top if x["status"] != "none"])
r.check("the shortlist is the head of the ranking, not a hand-picked set",
        [x["id"] for x in top]
        == [x["id"] for x in ranked if x["status"] == "none"][:len(top)],
        [x["id"] for x in top])
r.check("it does not silently drop an unprotected corridor that ranks higher",
        not [x["id"] for x in ranked if x["status"] == "none"
             and x["risk_exposure"] > top[0]["risk_exposure"]])
r.check("the headline is about exactly that shortlist",
        cor["headline"]["n_corridors"] == len(top),
        (cor["headline"]["n_corridors"], len(top)))
share = sum(x["risk_exposure"] for x in top) / sum(x["risk_exposure"] for x in corr) * 100
r.check("the quoted risk share is that shortlist's share of total exposure",
        abs(cor["headline"]["risk_share_pct"] - round(share, 1)) < 0.15,
        (cor["headline"]["risk_share_pct"], round(share, 1)))
avg = sum(x["kavach_pct"] for x in top) / len(top)
r.check("the quoted average coverage is that shortlist's mean",
        abs(cor["headline"]["avg_kavach_pct"] - round(avg, 1)) < 0.15,
        (cor["headline"]["avg_kavach_pct"], round(avg, 1)))

r.section("7. THE CAVEAT TRAVELS WITH THE NUMBER")
for name, payload in (("coverage", cov), ("correlation", cor)):
    d = payload.get("disclaimer", "")
    r.check(f"{name} carries a disclaimer", bool(d), d[:70])
    r.check(f"{name} says the figures are indicative, not official",
            "indicative" in d.lower() and "not official" in d.lower(), d[:90])
    r.check(f"{name} does not overclaim precision",
            "approximate" in d.lower() or "representative" in d.lower(), d[:90])
r.check("neither payload claims the numbers are official",
        "not official" in cov["disclaimer"].lower()
        and "not official" in cor["disclaimer"].lower())

r.section("8. STABILITY")
r.check("coverage is deterministic", c.get("/api/m6/coverage").json() == cov)
r.check("correlation is deterministic", c.get("/api/m6/correlation").json() == cor)

r.finish()
