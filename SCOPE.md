# RailSetu — Project Scope & Feature Specification

**Indian Railway Intelligence Platform · FAR AWAY 2026 Hackathon (Railways Track)**

A modular software platform that makes Indian Railways safer and more punctual by
transplanting proven **Japanese** rail solutions, adapted for India's scale and
crowding. Every module pairs a documented Indian problem with the Japanese method
that solved it — that "Japan solved it" pairing is the spine of the whole pitch.

> **This document is the agreed scope.** It explains *what* we are building and what
> each feature does from a **user's point of view** — not how it's coded. Read it to
> understand the product we're delivering and where your work fits.

---

## 1. Scope decision (what we're building vs. deferring)

| | Modules | Status |
|---|---|---|
| ✅ **In scope** | **M1** Station Crowd-Flow & Stampede Prevention (flagship) | Largely built |
| ✅ **In scope** | **M2** Delay Propagation & Smart Rescheduling | To build |
| ✅ **In scope** | **M6** Kavach Gap Analysis (light: M6.1 + M6.3) | To build |
| ✅ **In scope** | **Dashboard glue** D1 Incident Timeline + D2 Japan Benchmark Panel | To build (cheap) |
| ⏸️ **Deferred** | **M3** Track maintenance, **M4** Level-crossing, **M5** Waitlist/coach-load | Present as architecture only |

**Why this shape:** two genuine algorithm cores (pedestrian-flow modelling + constraint-based
rescheduling) plus one policy/impact layer (Kavach gaps). Depth beats breadth — this is the mix
the PRD says wins on "Innovation & Technical Depth" without over-scoping.

---

## 2. Current status at a glance

| Module | Feature | Priority | Status |
|---|---|---|---|
| M1 | Station layout model | MVP | ✅ Built |
| M1 | Pedestrian flow simulation | MVP | ✅ Built |
| M1 | Density / danger-zone heatmap | MVP | ✅ Built |
| M1 | Surge prediction | MVP | ⚠️ Partial (scenario-driven, not live forecast) |
| M1 | What-if mitigation sandbox | Diff | ✅ Built |
| M1 | Real-time alerts to control room | MVP | ✅ Built |
| M1 | Emergency escalation | Diff | ⚠️ Partial (cosmetic text) |
| M1 | Public Crowd Status App (PWA) | MVP | 🆕 To build |
| M1 | Festival Surge Calendar | Diff | 🆕 To build |
| M2 | Network model | MVP | ⬜ To build |
| M2 | Delay-propagation simulator | MVP | ⬜ To build |
| M2 | Rescheduling optimizer | MVP | ⬜ To build |
| M2 | Before/after comparison | MVP | ⬜ To build |
| M2 | Live ripple visualisation | Diff | ⬜ To build |
| M2 | Historical validation replay | Diff | 🆕 To build (data-gated) |
| M6 | Coverage map | Diff | ⬜ To build |
| M6 | Kavach Gap × Accident Correlation | Diff | 🆕 To build |
| M6 | Risk-based rollout planner | Future | ⏸️ Deferred |
| D1 | Cross-Module Incident Timeline | MVP | 🆕 To build |
| D2 | Japan vs. India Benchmark Panel | MVP | 🆕 To build |

**Legend:** ✅ built · ⚠️ partial · ⬜ to build · 🆕 new in PRD v4.0 · ⏸️ deferred

---

## 3. The shared backbone (why it's a "platform," not three apps)

All modules share one data + map backbone and one dashboard. An event in one module can
inform another (a predicted crowd surge in M1 affects platform decisions; a Kavach gap in M6
informs M2 rerouting priorities). Concretely, everything is built on the same foundation:
a graph model of the real world, a simulation/optimization core on top, and a unified
control-room dashboard with a public passenger layer. The **D1 Incident Timeline** is what
makes this shared backbone *visible* in the demo.

---

## 4. Module M1 — Station Crowd-Flow & Stampede Prevention (FLAGSHIP) — *built*

**India problem:** recurring deadly stampedes from overcrowding — no holding areas, no one-way
flow planning at major stations during surges (e.g. New Delhi, Feb 2025: 18 killed on the
platform 14/15 foot-over-bridge during a Maha Kumbh rush).

**Japan solution adapted:** crowd-flow engineering at hubs like Shinjuku (~3M/day) — pedestrian
origin-destination forecasting and simulation to find choke points and keep flow unimpeded.

**Station we model:** **New Delhi (NDLS)** — chosen because it has the richest open map data
*and* the most relevant recent stampede, on a specific, mappable foot-over-bridge.

**The user:** a station control-room operator (plus a public passenger view).

### Features (user point of view)

| ID | Feature | What the user does / sees | Status |
|---|---|---|---|
| M1.1 | Station layout model | Sees the real NDLS station as a live map — platforms, stairs, foot-over-bridges, concourse, exits. | ✅ |
| M1.2 | Pedestrian flow simulation | Picks a scenario; the system models thousands of people moving off platforms toward exits during a train arrival or festival surge. | ✅ |
| M1.3 | Density / danger-zone heatmap | The map lights up green→red showing where crowd density crosses unsafe levels — with the lethal "crush" zones pulsing red **before** it becomes dangerous. | ✅ |
| M1.4 | Surge prediction | Selects a surge scenario (e.g. festival specials) and sees the crowd build-up it will cause. *(Today: chosen from preset scenarios; upgrade = drive it live from incoming-train data.)* | ⚠️ |
| M1.5 | What-if mitigation sandbox | Toggles interventions — metered holding, one-way/extra FOB lanes, staggered release, extra exits — and watches the risk drop, with a headline number (e.g. **−81% peak density, crush points 4 → 0**). | ✅ |
| M1.6 | Real-time alerts to control room | Sees a ranked alert list of danger spots, each with a recommended action ("hold gate, open exit, deploy staff"). | ✅ |
| M1.7 | Emergency escalation | On a critical crush, the alert recommends notifying RPF/medical with the hotspot location. *(Today: text only; upgrade = a labelled simulated dispatch log.)* | ⚠️ |
| M1.8 | Public Crowd Status App | **New.** A passenger-facing mobile page showing live crowd level (Green/Yellow/Red) per gate/platform with guidance — "Platform 14 congested → use Gate 3." Closes the operator→passenger loop. | 🆕 |
| M1.9 | Festival Surge Calendar | **New.** Pulls the festival/holiday calendar (Diwali, Chhath, Kumbh, Eid) and shows a forward-looking warning: "Chhath in 3 days — here's the station if we act now vs. don't." | 🆕 |

### How honest we are about it
The simulation is a **real capacity-constrained pedestrian-flow model graded by the Fruin
density standard (persons/m²)** — not an animation. It finds the choke point (the platform
14/15 foot-over-bridge) on its own. Numbers are **modelled**, not validated against real
footfall counts, so we label them "modelled," and the headline what-if reduction is real
*relative to the model's own baseline*.

### Data source
Real station geometry from **OpenStreetMap** (10 platforms, 50 staircases, 100+ footways, 12
exits), captured once as a frozen snapshot so the demo never depends on a live call. Crowd
demand comes from hand-built scenarios (one reproduces the Feb 2025 pattern).

### Known issues to fix before demo (from code review)
1. **Fetch error handling** — if the backend hiccups, the dashboard can hang on "simulating…"; add error handling.
2. **Staggered-release accuracy** — currently under-counts people when staggering; clamp it.
3. **Map re-init in dev** — add Leaflet cleanup to avoid a blank map on hot-reload.

---

## 5. Module M2 — Delay Propagation & Smart Rescheduling — *to build*

**India problem:** one late train on a saturated corridor (many run >150% capacity) cascades
network-wide, and recovery is done manually by controllers.

**Japan solution adapted:** punctuality from *systematic rescheduling* — holds, overtakes,
re-platforming computed centrally (ATOS-style control; Tokaido Shinkansen ~1.6 min avg delay).

**Corridor we model:** **Delhi–Kanpur (NDLS→CNB)** — a busy double-line trunk shared by many trains.

**The user:** a railway **section controller** keeping the corridor on time.

### Features (user point of view)

| ID | Feature | What the user does / sees | Status |
|---|---|---|---|
| M2.1 | Network model | Sees a live control board of the corridor — every station in order, every train at its position; click a train for its schedule, a station for its platforms. | ⬜ |
| M2.2 | Delay-propagation simulator | Flags a train as late ("20 min delay") and immediately sees the knock-on: which other trains get stuck, how the delay spreads, the total damage ("delays 11 trains, +240 delay-minutes"). | ⬜ |
| M2.3 | Rescheduling optimizer | Clicks "Suggest recovery plan" and gets concrete moves: "Hold 12309 4 min at Aligarh," "Let the Shatabdi overtake at Tundla," "Move 12015 to Platform 3." | ⬜ |
| M2.4 | Before/after comparison | Sees the scoreboard: "Do nothing: 240 delay-min · Follow plan: 90 · **You save 150 delay-minutes.**" | ⬜ |
| M2.5 | Live ripple visualisation | Hits play and watches the delay spread as a red wave down the corridor, then watches the optimized version contain it. | ⬜ |
| M2.6 | Historical validation replay | Picks a real past disruption and watches what actually happened vs. what the optimizer would have done — "on real events, this would've cut delays by X%." | 🆕 |

### The 30-second user story
Controller watches the corridor board (**M2.1**) → a train reports a fault, screen shows the
cascade about to hit 11 trains (**M2.2**) → clicks "Suggest recovery plan," gets three concrete
moves (**M2.3**) → scoreboard shows they save 150 delay-minutes (**M2.4**) → hits play and watches
the wave get contained (**M2.5**) → already trusts it from past-event replays (**M2.6**).

### Data source & honesty
Real **timetable** from data.gov.in open schedules (exact); platform counts/headways are
reasoned estimates (moderate). The optimizer genuinely solves the scheduling problem — the
"delay-minutes saved" is real *within our model*; real-world savings are **indicative**. M2.6
is the highest-credibility feature but **data-gated** (no clean open NTES history) — frame it
as a back-test on captured data, not a live guarantee.

---

## 6. Module M6 — Kavach Gap Analysis — *to build (light)*

**Critical framing: M6 is NOT Kavach and does not prevent collisions.**

- **Real Kavach** is physical anti-collision *hardware* on trains and track that automatically
  brakes a train in real time to prevent a crash. Its rollout is slow and limited to select routes.
- **RailSetu M6** is a **desk-level software analysis tool** that sits *above* Kavach and answers
  a policy question: *where is the missing Kavach most dangerous, and where should the next rupee go?*
  It never touches a train. **Kavach is the seatbelt; M6 tells you which cars lack one and which of
  those are driven on the most dangerous roads.**

**The user:** a railway **safety planner / policymaker** allocating a limited Kavach budget.

### Features (user point of view)

| ID | Feature | What the user does / sees | Status |
|---|---|---|---|
| M6.1 | Coverage map | Sees a network map colored by Kavach coverage — green = equipped, red = not — shaded by traffic, so the dangerous gaps stand out. | ⬜ |
| M6.3 | Kavach Gap × Accident Correlation | Overlays historical accident data and gets a policy headline: "These ~12 high-traffic corridors carry most of the collision risk and have 0% Kavach." An investment argument, not just a map. | 🆕 |
| M6.2 | Risk-based rollout planner | *(Deferred)* Would rank the next corridors to equip for the most safety per rupee. | ⏸️ |

### Honesty
Accident/coverage data is **coarse** (often zone-level, coverage news-sourced). The *direction*
is solid; any specific percentage is labelled **"indicative,"** never stated as hard fact. M6 is
a deliberately light policy/impact add-on (~1 day) — the technical depth lives in M1 and M2.

---

## 7. Dashboard extensions (the glue) — *to build, cheap*

| ID | Feature | What it does | Status |
|---|---|---|---|
| D1 | Cross-Module Incident Timeline | A chronological event feed at the top of the dashboard — M1 crowd alerts + M2 delay cascades shown as one stream. Click an incident to see which modules responded. Makes the shared backbone visible. | 🆕 |
| D2 | Japan vs. India Benchmark Panel | A live widget comparing India's on-time rate vs. Shinkansen, avg delay on the demo corridor, recent crowd incidents. Keeps the Japan framing on-screen during the demo. | 🆕 |

---

## 8. Deferred modules (present as architecture, don't build)

- **M3 — Predictive Track Maintenance:** CV defect detection from cab-camera/drone footage.
- **M4 — Level-Crossing Safety:** CV obstacle detection at crossings + emergency dispatch.
- **M5 — Passenger Crowd & Waitlist Intelligence:** coach-load forecasting, waitlist prediction, the waitlist-clearance notifier.

These are shown as a one-line architecture entry + one mocked screen, to demonstrate the platform
extends — without spending build time on them.

---

## 9. Accuracy & honesty principles (apply everywhere)

Judges reward honesty; overclaiming loses. The rule for every feature:

- **Exact facts** (station geometry, timetable, festival dates) — state plainly.
- **Modelled outputs** (crowd density, delay cascades, savings) — label **"modelled"**; they're
  real relative to our own baseline, not validated against ground truth.
- **Indicative analysis** (Kavach correlation, historical back-test) — label **"indicative"**;
  never quote a hard percentage as proven.
- **Mocked** items — say so.

A small "modelled / indicative / cited / mocked" tag in the UI costs nothing and earns trust.

---

## 10. Tech stack (for coordination)

- **Backend:** Python (FastAPI) — home of the simulation, optimization (OR-Tools for M2), and
  geospatial analysis (M6). Graphs via NetworkX.
- **Frontend:** React + Leaflet (maps) + Recharts (charts). A control-room dashboard plus a public
  passenger layer (M1.8 PWA).
- **Data:** committed snapshots/fixtures so the demo never depends on a live fetch (OSM for M1,
  open timetable for M2, public accident/coverage data for M6).
- **Run:** `./run.sh` starts both servers; see `README.md`.

---

## 11. Build plan & suggested ownership

| Order | Work | Rough effort | Owner |
|---|---|---|---|
| 1 | Fix the 3 M1 review bugs (protect the working demo) | 1–2 hrs | _(frontend)_ |
| 2 | **M2.1 → M2.4** (corridor board → cascade sim → optimizer → before/after) | 2–3 days | _(backend + sim)_ |
| 3 | **M6.1 + M6.3** (coverage map + accident correlation) | ~1 day | _(geo/data)_ |
| 4 | **D1 + D2** (incident timeline + benchmark panel) | ~half day | _(frontend)_ |
| 5 | **M1.8 + M1.9** (public crowd app + festival calendar) — if time | ~1 day | _(full-stack)_ |
| 6 | **M2.5 / M2.6** (ripple animation, historical replay) — if time | varies | _(sim)_ |

**Team split suggestion:** 1–2 on the M1 flow model + public app (the flagship moat), 1 on M2
rescheduling + optimizer, 1 on data/geospatial (timetable + Kavach correlation), 1 on
frontend/dashboard + the demo. Smaller team: M1 fully + M2 propagation (mock the optimizer) +
D1/D2, present M6 and the rest as architecture.

---

## 12. What the final demo looks like

Open on the **NDLS heatmap turning red** during a festival surge with the headline lives/risk
number in the first 15 seconds → toggle a mitigation, watch the crush clear (**M1**) → switch to
the **Delhi–Kanpur board**, inject a delay, watch the cascade, hit "optimize," show
delay-minutes saved (**M2**) → flash the **Kavach gap map** as the policy argument (**M6**) → the
**Incident Timeline** and **Japan Benchmark Panel** tie it together as one platform (**D1/D2**).
Honest non-goals slide closes it (privacy: aggregate density only; no hardware; no live signalling).
