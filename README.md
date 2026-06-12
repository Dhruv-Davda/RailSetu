# 🚉 RailSetu — Indian Railway Intelligence Platform

**M1 Flagship: Station Crowd-Flow & Stampede Prevention — New Delhi (NDLS)**

RailSetu transplants proven Japanese rail-safety methods, adapted for India's
scale and crowding. The flagship module predicts dangerous station crowding and
shows operators how to prevent stampedes — modelled on Japan's crowd-flow
engineering at hubs like Shinjuku.

> **The demo in one line:** load the *Festival surge* scenario and the New Delhi
> station map lights up red — a crush forming on the foot-over-bridge between
> platforms 14 and 15, exactly where 18 people died in February 2025. Toggle
> **Metered holding** and the crush disappears: peak density falls **−81%**
> (17.4 → 3.3 persons/m²) and crush points go **4 → 0**.

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
│   │   ├── main.py               API: /station /scenarios /simulate /whatif
│   │   ├── data/station.py       loads the routable NDLS graph
│   │   └── m1_crowd/
│   │       ├── simulation.py     pedestrian O-D flow model + density/LOS + crush detection
│   │       └── scenarios.py      committed demand scenarios (normal / Kumbh surge / double arrival)
│   ├── scripts/build_station_graph.py   OSM → connected walk graph (run once)
│   └── fixtures/
│       ├── ndls_osm_raw.json     raw Overpass snapshot
│       └── station_graph.json    the M1 fixture (nodes, edges, capacities)
└── frontend/                     React + Leaflet control room
    └── src/
        ├── App.jsx               control-room layout, scenario + mitigation controls, impact panel
        ├── StationMap.jsx        Leaflet density heatmap + pulsing crush points
        └── los.js                Fruin LOS colour scale
```

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/station` | Station geometry (nodes, edges, platforms, exits) for the map |
| `GET /api/scenarios` | Available demand scenarios |
| `POST /api/simulate` | Run a scenario (+ optional mitigations); returns per-edge / per-node density, hotspots, timeline |
| `POST /api/whatif` | Baseline vs. mitigated side by side with the headline impact numbers |

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
