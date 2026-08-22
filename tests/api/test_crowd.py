"""
The pedestrian-flow model: geometry, capacity, mitigations, and the optimizer.

These assert the PHYSICS and the invariants, not memorised outputs. A test that
pins `peak_density == 17.39` breaks the moment anyone tunes a constant and tells
you nothing about whether the model is right. A test that asserts density rises
when demand exceeds capacity, that the crush concentrates on the articulation
point every passenger must cross, and that metering removes it, still holds
after a re-tune — and fails when the model stops being a flow model.
"""
from harness import bootstrap, Report

bootstrap("crowd")

from fastapi.testclient import TestClient           # noqa: E402
from app.main import app                            # noqa: E402
from app.m1_crowd.simulation import los_for         # noqa: E402
from app.policy.context import current              # noqa: E402

r = Report("CROWD MODEL")
c = TestClient(app)


def sim(scenario, **mit):
    body = {"scenario": scenario}
    if mit:
        body["mitigations"] = mit
    return c.post("/api/simulate", json=body).json()


# ---------------------------------------------------------------- geometry
r.section("1. THE STATION IS A REAL, CONNECTED GRAPH")
st = c.get("/api/station").json()
nodes, edges = st["nodes"], st["edges"]
r.check("nodes are present", len(nodes) > 100, len(nodes))
r.check("edges are present", len(edges) > 100, len(edges))
ids = {n["id"] for n in nodes}
r.check("every edge joins two known nodes",
        all(e["u"] in ids and e["v"] in ids for e in edges))
r.check("every node carries real coordinates",
        all(-90 <= n["lat"] <= 90 and -180 <= n["lon"] <= 180 for n in nodes))
r.check("the coordinates are New Delhi, not the origin",
        all(28.6 < n["lat"] < 28.7 and 77.1 < n["lon"] < 77.3 for n in nodes))
r.check("platforms are identified", len(st["platforms"]) >= 8, len(st["platforms"]))
r.check("entrances/exits are identified", len(st["entrances"]) >= 5, len(st["entrances"]))
r.check("track alignments are carried for the 3D view", len(st["rails"]) > 100, len(st["rails"]))
r.check("edges declare a walking capacity",
        all(e.get("capacity_pps", 0) > 0 for e in edges))
r.check("edges declare which level they are on — the FOB is a second deck",
        len({e.get("level") for e in edges}) > 1, sorted({e.get("level") for e in edges}))
r.check("edges carry a length", all(e.get("length_m", 0) > 0 for e in edges))
r.check("edges carry a width capacity", all(e.get("width_m", 0) > 0 for e in edges))

# Reachability: a flow model on a disconnected graph would strand passengers.
adj = {}
for e in edges:
    adj.setdefault(e["u"], []).append(e["v"])
    adj.setdefault(e["v"], []).append(e["u"])
seen, stack = set(), [nodes[0]["id"]]
while stack:
    n = stack.pop()
    if n in seen:
        continue
    seen.add(n)
    stack.extend(adj.get(n, []))
r.check("the walk graph is one connected component", len(seen) == len(ids),
        f"{len(seen)}/{len(ids)} reachable")

# ---------------------------------------------------------------- LOS bands
r.section("2. FRUIN LEVEL-OF-SERVICE GRADING")
bands = current().density_bands
crush = current().crush_threshold
grade = lambda d: los_for(d)[0]          # los_for returns (grade, label)
label = lambda d: los_for(d)[1]

r.check("the bands are read from the policy in force, not a literal",
        isinstance(bands, list) and len(bands) == 5, bands)
r.check("each band is (threshold, grade, label)",
        all(len(b) == 3 and isinstance(b[0], float) for b in bands), bands[0])
r.check("the thresholds increase strictly",
        [b[0] for b in bands] == sorted(b[0] for b in bands), [b[0] for b in bands])
r.check("empty space is free flow", grade(0.0) == "A" and label(0.0) == "free")
r.check("the crush regime is F", grade(crush + 0.1) == "F", grade(crush + 0.1))
r.check("...and is labelled a crush", label(crush + 0.1) == "crush")
r.check("just below the crush line is not F", grade(crush - 0.01) != "F")
r.check("the grading never improves as density rises",
        [grade(d) for d in (0.1, 1.5, 2.5, 3.4, 4.6, 9.0)]
        == sorted(grade(d) for d in (0.1, 1.5, 2.5, 3.4, 4.6, 9.0)))
# A band applies BELOW its threshold, so probe just under each one; if two bands
# returned the same grade, one of them would be unreachable dead configuration.
r.check("every band is reachable — none is shadowed by its neighbour",
        len({grade(b[0] - 0.01) for b in bands}) == len(bands),
        sorted({grade(b[0] - 0.01) for b in bands}))
r.check("a band boundary belongs to the band below it",
        grade(crush) == "F" and grade(crush - 1e-9) != "F")
r.check("explicit bands override the policy — the preview seam",
        los_for(3.0, bands=[(1.0, "A", "free"), (99.0, "F", "crush")])[0] == "F")

# ---------------------------------------------------------------- behaviour
r.section("3. MORE DEMAND THROUGH THE SAME GEOMETRY MEANS MORE DENSITY")
normal = sim("normal_evening")["summary"]
surge = sim("kumbh_surge")["summary"]
r.check("the surge injects more people",
        surge["total_injected"] > normal["total_injected"],
        (normal["total_injected"], surge["total_injected"]))
r.check("...and reaches a higher peak density",
        surge["peak_density"] > normal["peak_density"],
        (normal["peak_density"], surge["peak_density"]))
r.check("the routine evening produces no crush point", normal["crush_count"] == 0)
r.check("the surge does", surge["crush_count"] > 0, surge["crush_count"])
r.check("the peak grade matches the peak density",
        surge["peak_los"] == grade(surge["peak_density"]),
        (surge["peak_density"], surge["peak_los"]))
r.check("danger locations are a superset of crush points",
        surge["danger_count"] >= surge["crush_count"],
        (surge["danger_count"], surge["crush_count"]))

r.section("4. THE MODEL FINDS THE CHOKE POINT BY ITSELF")
full = sim("kumbh_surge")
hot = full["node_hotspots"]
r.check("hotspots are returned", len(hot) > 0, len(hot))
r.check("they are ranked worst first",
        [h["density"] for h in hot] == sorted([h["density"] for h in hot], reverse=True))
worst = hot[0]
r.check("the worst location is the FOB landing the crowd must cross",
        worst["node"] == "n150", worst["node"])
r.check("the worst reading is the reported peak",
        abs(worst["density"] - full["summary"]["peak_density"]) < 0.01,
        (worst["density"], full["summary"]["peak_density"]))
r.check("a queue is reported where people cannot pass", worst.get("queue", 0) > 0,
        worst.get("queue"))
r.check("every hotspot carries the grade that justifies raising it",
        all(h.get("los") and h.get("state") for h in full["hotspots"]),
        full["hotspots"][0])
r.check("every hotspot is locatable on the map",
        all(h.get("lat") and h.get("lon") for h in full["hotspots"]))
r.check("hotspot grades agree with their own densities",
        all(h["los"] == grade(h["density"]) for h in full["hotspots"]))

r.section("5. THE MITIGATION IS THE SCIENCE, NOT A FUDGE")
metered = sim("kumbh_surge", metered_holding=True)["summary"]
r.check("metering lowers the peak", metered["peak_density"] < surge["peak_density"],
        (surge["peak_density"], metered["peak_density"]))
r.check("...and clears the crush entirely", metered["crush_count"] == 0,
        metered["crush_count"])
r.check("it does not achieve that by stranding people",
        metered["total_cleared"] >= surge["total_cleared"] * 0.99,
        (surge["total_cleared"], metered["total_cleared"]))
r.check("the crowd injected is unchanged — only its release is",
        metered["total_injected"] == surge["total_injected"])

each = {k: sim("kumbh_surge", **{k: True})["summary"]["peak_density"]
        for k in ("metered_holding", "open_fob", "stagger_release", "extra_exits")}
r.check("no single measure makes the station more dangerous",
        all(v <= surge["peak_density"] + 1e-6 for v in each.values()), each)
allfour = sim("kumbh_surge", metered_holding=True, open_fob=True,
              stagger_release=True, extra_exits=True)["summary"]
r.check("applying everything is at least as safe as the best single measure",
        allfour["crush_count"] == 0, allfour["crush_count"])

r.section("6. WHAT-IF RETURNS BOTH SIDES, NOT JUST THE GOOD ONE")
w = c.post("/api/whatif", json={"scenario": "kumbh_surge",
                                "mitigations": {"metered_holding": True}}).json()
r.check("baseline is returned", "baseline" in w)
r.check("mitigated is returned", "mitigated" in w)
imp = w["impact"]
r.check("the reduction is stated as a percentage", imp["peak_reduction_pct"] > 0,
        imp["peak_reduction_pct"])
r.check("the percentage matches the two densities",
        abs(imp["peak_reduction_pct"]
            - round((1 - imp["peak_density_after"] / imp["peak_density_before"]) * 100, 1)) < 0.2,
        imp["peak_reduction_pct"])
r.check("baseline matches an unmitigated run",
        abs(imp["peak_density_before"] - surge["peak_density"]) < 0.01)

r.section("7. THE OPTIMIZER IS EXHAUSTIVE, NOT A GUESS")
o = c.post("/api/optimize", json={"scenario": "kumbh_surge"}).json()
r.check("all sixteen combinations of four levers are evaluated",
        o["evaluated"] == 16, o["evaluated"])
r.check("the method is named as enumeration, not inference",
        "exhaust" in o["method"].lower() or "enumerat" in o["method"].lower(), o["method"])
rec = o["recommended"]
r.check("the winner removes every crush point", rec["crush_count"] == 0, rec["crush_count"])
r.check("the winner is at least as good as the baseline",
        rec["peak_density"] <= o["baseline"]["peak_density"])
r.check("the ranking is ordered by the policy objective",
        [x["score"] for x in o["ranking"]] == sorted(x["score"] for x in o["ranking"]))
r.check("the winner is the top of the ranking",
        o["ranking"][0]["score"] == rec["score"], (o["ranking"][0]["score"], rec["score"]))
r.check("it does not recommend more measures than it needs",
        rec["n_active"] <= min(x["n_active"] for x in o["ranking"]
                               if x["crush_count"] == 0
                               and x["peak_density"] <= rec["peak_density"] + 1e-9),
        rec["n_active"])
r.check("the objective it optimised is echoed back", len(o["objective"]) >= 2, o["objective"])
r.check("every lever is reported, applied or not",
        set(rec["mitigations"]) == {"metered_holding", "open_fob",
                                    "stagger_release", "extra_exits"})
r.check("a brief is produced for the operator", bool(o.get("brief")))
r.check("the decision itself is not attributed to a language model",
        "score" in rec and isinstance(rec["score"], list))

r.section("8. DETERMINISM")
a = sim("kumbh_surge")["summary"]
b = sim("kumbh_surge")["summary"]
r.check("the same scenario twice gives the same answer", a == b)
r.check("an unknown scenario is refused",
        c.post("/api/simulate", json={"scenario": "no_such_scenario"}).status_code >= 400)

r.finish()
