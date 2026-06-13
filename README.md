# 🚉 RailSetu — Indian Railway Intelligence Platform

RailSetu transplants proven Japanese rail solutions, adapted for India's scale and
crowding. Each module pairs a documented Indian problem with the Japanese method
that solved it — two real algorithm cores plus a policy layer, on one shared
backbone, behind one control-room dashboard.

| Module | What it does | Japan method adapted | Status |
|---|---|---|---|
| **M1 · Crowd-Flow** | Predicts dangerous station crowding and prevents stampedes (NDLS) | Shinjuku pedestrian crowd-flow engineering | ✅ Built |
| **M2 · Delays** | Propagates a disruption across a corridor and reschedules trains to recover delay (Delhi → Kanpur) | Shinkansen systematic rescheduling / ATOS control | ✅ Built |
| **M6 · Kavach** | Maps where automatic train protection is missing and where the gap is most dangerous | Mature Automatic Train Control (gap analysis) | ✅ Built |

> **The demo in three beats:**
> 1. **M1** — load *Festival surge* and the NDLS map lights red: a crush on the
>    platform 14/15 foot-over-bridge, exactly where 18 died in Feb 2025. Toggle
>    **Metered holding** → peak density **−81%** (17.4 → 3.3 p/m²), crush points **4 → 0**.
> 2. **M2** — a slow passenger train is pathed ahead of the express fleet; the
>    running chart shows the cascade (**1106 delay-min**). Run the optimizer → the
>    lines fan out as expresses overtake: **~1100 delay-minutes saved (≈99%)**.
> 3. **M6** — the India map shows **8 high-traffic corridors carrying ~65% of
>    collision-risk exposure at ~7% Kavach coverage** (indicative).

---

## Why this is real modelling, not an animation

The core is a **macroscopic pedestrian origin–destination flow model** on the
real NDLS walk network, with capacity-constrained corridors and Fruin
Level-of-Service density thresholds — not an LLM wrapper.

- **Real geometry.** The station graph is built from live OpenStreetMap data
  (10 platforms, 50 staircases, 100+ footways, 12 exits), snapped into one
  connected walkable network. Committed as a fixture so the demo never depends
  on a network call.
- **Real flow physics.** People are injected at platforms (a train unloads / a
  surge builds), routed to the nearest exits, and pushed through corridors at a
  finite throughput (~1.3 persons/m/s, reduced on stairs). When demand exceeds a
  corridor's capacity, people queue and density rises.
- **The crush mechanism.** Density is measured in persons/m² and graded A→F. The
  lethal regime (≥ 5 p/m²) appears precisely at the foot-over-bridge landing off
  platform 14/15 — an *articulation point* every passenger on that platform must
  cross. The model finds this choke point on its own.
- **The fix is the science.** A real stampede happens when there is **no
  back-pressure** — people keep pressing into an already-packed space. The
  *Metered holding* mitigation adds that control: passengers are held in roomy
  areas and released onto the FOB only at a safe rate. That single change clears
  the crush in the model, which is exactly the crowd-engineering principle.

## The "Japan solved it" mapping (M1)

| India problem | Japanese solution adapted |
|---|---|
| Deadly station stampedes from overcrowding, no holding areas, no flow planning | Crowd-flow engineering at hubs like Shinjuku: pedestrian O-D forecasting + simulation to find choke points and keep flow unimpeded |

---

## Run it

```bash
./run.sh
```

Then open **http://localhost:5173**. (Backend API at http://127.0.0.1:8000, docs
at `/docs`.)

Or run the two halves manually:

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Try the demo
1. Scenario **Festival surge — Prayagraj specials (Feb 2025 pattern)** → status
   goes **CRITICAL**, the FOB lights red, alerts list the crush points.
2. Tick **Metered holding** → status drops to **MANAGED**, the headline shows
   **−81% peak density**, crush points **4 → 0**.
3. Compare **Normal evening peak** (managed, green/amber) to see the contrast.

---

## Architecture

```
railsetu/
├── backend/                      FastAPI + the simulation core
│   ├── app/
│   │   ├── main.py               API surface (see table above)
│   │   ├── config.py             env-driven settings (RAILSETU_*) + logging
│   │   ├── data/station.py       loads / hot-reloads the routable NDLS graph
│   │   ├── m1_crowd/
│   │   │   ├── simulation.py     pedestrian O-D flow model + density/LOS + crush detection
│   │   │   └── scenarios.py      committed demand scenarios (normal / Kumbh surge / double arrival)
│   │   ├── demand/               DemandProvider seam: fixtures | live (third-party rail API)
│   │   ├── clients/rail_api.py   third-party (RapidAPI) live-arrivals adapter
│   │   └── ingest/               measured-crowd ingestion (CCTV/WiFi stub) + calibration
│   ├── scripts/build_station_graph.py   OSM → connected walk graph (run on a schedule)
│   ├── .env.example              all config knobs, documented
│   └── fixtures/
│       ├── ndls_osm_raw.json     raw Overpass snapshot
│       ├── station_graph.json    the M1 fixture (nodes, edges, capacities)
│       └── crowd_observations.sample.json   sample measured density for calibration
└── frontend/                     React + Leaflet control room
    └── src/
        ├── App.jsx               control-room layout, scenario + mitigation controls, impact panel
        ├── StationMap.jsx        Leaflet density heatmap + pulsing crush points
        └── los.js                Fruin LOS colour scale
```

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness + station counts, demand-provider / crowd-sensor / calibration status |
| `GET /api/station` | Station geometry (nodes, edges, platforms, exits) for the map |
| `POST /api/station/refresh` | Hot-reload the graph fixture after a scheduled OSM rebuild (guarded) |
| `GET /api/scenarios` | Available demand scenarios (fixtures, plus `live_now` when live data is on) |
| `GET /api/live/demand` | Inspect the demand the live provider currently derives (transparency) |
| `POST /api/simulate` | Run a scenario (+ optional mitigations); returns per-edge / per-node density, hotspots, timeline |
| `POST /api/whatif` | Baseline vs. mitigated side by side with the headline impact numbers |
| `POST /api/calibration/run` | Pull measured crowd density and recompute the model's capacity calibration |
| `POST /api/calibration/reset` | Revert to textbook (uncalibrated) capacities |

### Going live — real-time data (production)

Everything is fixture-driven by default so the demo is deterministic and
network-free. Production swaps the two static inputs for live feeds **without
touching the simulation core**, via env config (see `backend/.env.example`):

- **Live demand.** A pluggable `DemandProvider` ([app/demand/](backend/app/demand/))
  is the seam between data and physics. `RAILSETU_DEMAND_PROVIDER=live` switches
  from committed scenarios to a third-party (RapidAPI) Indian-Railways
  live-arrivals feed: set `RAILSETU_RAIL_API_KEY` + host. The adapter maps each
  arriving train's platform → graph node and estimates the alighting crowd (these
  APIs return arrivals, not passenger counts — tune the estimation constants, or
  feed PRS/UTS later). If the feed is down it falls back to a fixture and flags it.
- **Measured crowd + calibration.** A `CrowdSensor` ([app/ingest/](backend/app/ingest/))
  ingests *observed* aggregate density (a real one wraps CCTV crowd-counting CV or
  anonymised WiFi/AFC counts — **aggregate only, no individuals**). `POST
  /api/calibration/run` compares observed vs. predicted density and nudges
  corridor capacities toward reality. A JSON sample
  (`fixtures/crowd_observations.sample.json`) exercises the path without hardware.
- **Geometry refresh.** Re-run `scripts/build_station_graph.py` on a schedule
  against a fresh OSM snapshot, then `POST /api/station/refresh` hot-reloads it.

> The third-party live API is an NTES scraper — fine for a pilot, but a true
> deployment should use authorised CRIS/RailTel/zonal-railway data access.

### Rebuild the station graph from OSM (optional)

```bash
cd backend && source .venv/bin/activate
python scripts/build_station_graph.py   # regenerates fixtures/station_graph.json
```

---

## Scope & honesty (per PRD)

- **In scope:** M1 end-to-end on real NDLS layout data with a working what-if
  sandbox. Built to extend to M2 (delay rescheduling) on the shared backbone.
- **Out of scope:** live integration with Railways signalling; trackside
  hardware; surveillance of identifiable individuals — this model uses
  **aggregate density only** (privacy).
- The crowd model is a planning/operations decision-support tool. Capacities and
  holding thresholds are calibrated to standard pedestrian-flow constants and
  should be tuned against site-specific data before any real deployment.

*Framed preventively, in memory of those lost — the goal is to save lives.*
