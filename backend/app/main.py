"""
RailSetu backend — Indian Railway Intelligence Platform.
M1 flagship: Station Crowd-Flow & Stampede Prevention (NDLS).

The HTTP layer is thin: it loads the station graph, asks a `DemandProvider` for a
scenario (committed fixtures OR a live train feed), runs the pedestrian-flow
simulation, optionally folds in calibration from measured crowd density, and
shapes the result for the control-room UI.
"""
from __future__ import annotations

import logging

from pathlib import Path

from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import configure_logging, get_settings
from app.data.station import load_rails, load_station, refresh_station
from app.demand.factory import get_demand_provider
from app.ingest.calibration import CalibrationState, compute_capacity_scale
from app.ingest.crowd_sensing import get_crowd_sensor
from app.m1_crowd.optimizer import search as optimizer_search
from app.clients.gemini import (
    GeminiClient, GeminiError, build_prompt, fallback_brief,
)
from app.m1_crowd.simulation import los_for, simulate
from app.policy import context as policy_context

settings = get_settings()
configure_logging(settings)
log = logging.getLogger("railsetu")

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Process-wide singletons (cheap, stateless except the calibration store).
CROWD_SENSOR = get_crowd_sensor(settings)
CAL_STATE = CalibrationState()
GEMINI = GeminiClient(settings)

# Both of these are POLICY, not physics — they now come from the active
# operating policy (app/policy). The constants remain only as the shape of the
# defaults; see DEFAULT_POLICY_YAML: crowd_safety.



class Mitigations(BaseModel):
    # Crowd-engineering controls the operator can toggle in the what-if sandbox.
    metered_holding: bool = False    # hold people in roomy areas; meter onto FOB (LOS C)
    open_fob: bool = False           # one-way + extra foot-over-bridge lanes (egress x2.5)
    stagger_release: bool = False    # spread the platform release over more time
    extra_exits: bool = False        # open additional dispersal gates

    def describe(self):
        on = []
        if self.metered_holding: on.append("Metered holding (LOS C)")
        if self.open_fob: on.append("One-way / extra FOB lanes")
        if self.stagger_release: on.append("Staggered release")
        if self.extra_exits: on.append("Extra exit gates")
        return on


class SimRequest(BaseModel):
    scenario: str
    mitigations: Mitigations | None = None


def _run(scenario_key, mitigations: Mitigations | None):
    s = load_station()
    G = s["graph"]
    provider = get_demand_provider()
    ds = provider.get_scenario(scenario_key)
    if not ds:
        raise HTTPException(404, f"unknown scenario '{scenario_key}'")

    demands = [{"platform": d.platform, "people": d.people, "duration_s": d.duration_s}
               for d in ds.demands if d.platform in G]
    exits = [e for e in ds.exits if e in G]

    pol = policy_context.current()
    mit = {}
    cap_scale: dict = {}

    # Calibration (measured-density correction) applies to every run when enabled.
    if settings.calibration_enabled and CAL_STATE.capacity_scale:
        cap_scale.update(CAL_STATE.capacity_scale)

    if mitigations:
        if mitigations.metered_holding:
            mit["meter_density"] = pol.meter_density
        if mitigations.stagger_release:
            mit["stagger"] = 0.5
        if mitigations.open_fob:
            for u, v in G.edges:
                if G.edges[u, v]["kind"] == "steps":
                    cap_scale[(u, v)] = cap_scale.get((u, v), 1.0) * pol.fob_egress_multiplier
        if mitigations.extra_exits:
            extra = [n for n in G.nodes
                     if G.nodes[n].get("kind") == "entrance" and n not in exits]
            exits = exits + extra

    if cap_scale:
        mit["capacity_scale"] = cap_scale

    res = simulate(G, demands, exits, horizon_s=ds.horizon_s, mitigations=mit)

    # Shape edge results for the client (string keys).
    edges = []
    for (u, v), dens in res.edge_density.items():
        grade, label = los_for(dens)
        edges.append({
            "u": u, "v": v,
            "density": dens,
            "people": res.edge_peak_count[(u, v)],
            "los": grade,
            "state": label,
            "kind": G.edges[u, v]["kind"],
        })

    # Per-node density (the crush metric) for every node, so the map can colour
    # holding areas / stair mouths, plus the ranked crush points.
    nodes = []
    for n, dens in res.node_density.items():
        grade, label = los_for(dens)
        nd = G.nodes[n]
        nodes.append({
            "node": n, "lat": nd["lat"], "lon": nd["lon"],
            "kind": nd.get("kind", "junction"), "name": nd.get("name"),
            "density": dens, "queue": round(res.node_queue_peak[n], 1),
            "los": grade, "state": label,
        })

    edge_peak = max((e["density"] for e in edges), default=0.0)
    node_peak = max((n["density"] for n in nodes), default=0.0)
    peak = max(edge_peak, node_peak)
    danger = [x for x in nodes + edges if x["los"] in ("E", "F")]
    return {
        "scenario": scenario_key,
        "title": ds.title,
        "source": ds.source,
        "generated_at": ds.generated_at,
        "demand_meta": ds.meta,
        "calibrated": settings.calibration_enabled and bool(CAL_STATE.capacity_scale),
        "edges": edges,
        "nodes": nodes,
        "hotspots": res.node_hotspots + res.hotspots,
        "node_hotspots": res.node_hotspots,
        "timeline": res.timeline,
        "summary": {
            "total_injected": res.total_injected,
            "total_cleared": res.total_cleared,
            "peak_density": round(peak, 2),
            "peak_los": los_for(peak)[0],
            "danger_count": len(danger),
            "crush_count": sum(1 for x in nodes + edges if x["los"] == "F"),
        },
    }


@app.get("/api/health")
def health():
    s = load_station()
    provider = get_demand_provider()
    return {
        "status": "ok",
        "version": settings.app_version,
        "station": s["meta"]["station"],
        "counts": s["meta"]["counts"],
        "demand_provider": provider.health(),
        "crowd_sensor": CROWD_SENSOR.health(),
        "calibration": CAL_STATE.as_dict(),
        "gemini": GEMINI.health(),
        "policy": _policy_health(),
        "accounts": ACCOUNTS.store.health() if "ACCOUNTS" in globals() else None,
    }


def _policy_health() -> dict:
    """Defined below the register is built; called lazily so import order is free."""
    try:
        lib = POLICY.library_payload()
        return {"store": lib["store"], "documents": lib["count"],
                "amended": sum(1 for d in lib["documents"] if (d["versions"] or 0) > 1)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


@app.get("/api/station")
def station():
    """Geometry for the map: nodes, edges, platforms, exits."""
    s = load_station()
    rails = load_rails()
    return {
        "meta": s["meta"],
        "nodes": s["nodes"],
        "edges": s["edges"],
        "platforms": s["platforms"],
        "entrances": s["entrances"],
        # Real OSM track alignments (decorative, for the 3D yard). Optional.
        "rails": rails["ways"],
        "rails_meta": rails["meta"],
    }


@app.post("/api/station/refresh")
def station_refresh():
    """Hot-reload the station graph fixture (e.g. after a scheduled OSM rebuild)."""
    if not settings.allow_graph_refresh:
        raise HTTPException(403, "graph refresh disabled (set RAILSETU_ALLOW_GRAPH_REFRESH=true)")
    s = refresh_station()
    log.info("station graph refreshed: %s", s["meta"]["counts"])
    return {"refreshed": True, "counts": s["meta"]["counts"]}


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": get_demand_provider().list_scenarios()}


@app.get("/api/live/demand")
def live_demand():
    """Inspect the demand the live provider currently derives (transparency)."""
    if settings.demand_provider != "live":
        raise HTTPException(400, "demand_provider is not 'live' (set RAILSETU_DEMAND_PROVIDER=live)")
    ds = get_demand_provider().get_scenario("live_now")
    if not ds:
        raise HTTPException(503, "live demand unavailable")
    return {
        "key": ds.key, "title": ds.title, "source": ds.source,
        "generated_at": ds.generated_at, "horizon_s": ds.horizon_s,
        "total_people": ds.total_people, "meta": ds.meta,
        "demands": [{"platform": d.platform, "people": d.people,
                     "duration_s": d.duration_s, "label": d.label} for d in ds.demands],
    }


@app.post("/api/simulate")
def run_sim(req: SimRequest):
    return _run(req.scenario, req.mitigations)


@app.post("/api/whatif")
def whatif(req: SimRequest):
    """Run baseline vs. mitigated side by side for the what-if sandbox."""
    base = _run(req.scenario, None)
    mit = _run(req.scenario, req.mitigations)
    bp = base["summary"]["peak_density"]
    mp = mit["summary"]["peak_density"]
    reduction = round((bp - mp) / bp * 100, 1) if bp else 0.0
    return {
        "baseline": base,
        "mitigated": mit,
        "impact": {
            "peak_density_before": bp,
            "peak_density_after": mp,
            "peak_reduction_pct": reduction,
            "danger_before": base["summary"]["danger_count"],
            "danger_after": mit["summary"]["danger_count"],
            "crush_before": base["summary"]["crush_count"],
            "crush_after": mit["summary"]["crush_count"],
            "cleared_before": base["summary"]["total_cleared"],
            "cleared_after": mit["summary"]["total_cleared"],
        },
    }


class OptimizeRequest(BaseModel):
    scenario: str
    explain: bool = True     # ask Gemini for the operator brief


@app.post("/api/optimize")
def optimize(req: OptimizeRequest):
    """M1.4 — pick the best mitigation plan, then explain it.

    The PLAN is computed: every one of the 16 mitigation combinations is run
    through the real pedestrian-flow simulation and ranked (crush points, then
    peak density, then throughput, then how many measures it takes). Gemini is
    asked only to write the control-room brief for the winning plan, and if it
    is unconfigured or unreachable we fall back to a deterministic summary — so
    the recommendation itself never depends on a network call or an LLM.
    """
    provider = get_demand_provider()
    ds = provider.get_scenario(req.scenario)
    if not ds:
        raise HTTPException(404, f"unknown scenario '{req.scenario}'")

    result = optimizer_search(_run, req.scenario, Mitigations)

    brief, source, error = fallback_brief(result), "fallback", None
    if req.explain and GEMINI.configured:
        try:
            brief = GEMINI.brief(build_prompt(result, ds.title))
            source = "gemini"
        except GeminiError as e:
            error = str(e)
            log.warning("gemini brief failed, using fallback: %s", e)

    result["brief"] = {
        "text": brief,
        "source": source,               # "gemini" | "fallback"
        "model": settings.gemini_model if source == "gemini" else None,
        "error": error,
    }
    log.info(
        "optimizer: %s -> %s (peak %.2f -> %.2f, crush %d -> %d) brief=%s",
        req.scenario, result["recommended"]["active"] or ["none"],
        result["impact"]["peak_before"], result["impact"]["peak_after"],
        result["impact"]["crush_before"], result["impact"]["crush_after"], source,
    )
    return result


@app.post("/api/calibration/run")
def calibration_run(scenario: str = Query("kumbh_surge")):
    """Pull measured crowd density and recompute the model's capacity calibration.

    Runs an uncalibrated baseline for `scenario`, compares predicted node density
    to the sensor's observations, and stores the resulting capacity corrections so
    subsequent simulations reflect reality. No-op (200) when no observations exist.
    """
    obs = CROWD_SENSOR.read()
    if not obs:
        return {"updated": False, "reason": "no observations from crowd sensor",
                "observations": 0, "sensor": CROWD_SENSOR.health()}

    s = load_station()
    G = s["graph"]
    provider = get_demand_provider()
    ds = provider.get_scenario(scenario)
    if not ds:
        raise HTTPException(404, f"unknown scenario '{scenario}'")

    demands = [{"platform": d.platform, "people": d.people, "duration_s": d.duration_s}
               for d in ds.demands if d.platform in G]
    exits = [e for e in ds.exits if e in G]
    res = simulate(G, demands, exits, horizon_s=ds.horizon_s)  # uncalibrated baseline

    scale = compute_capacity_scale(G, res.node_density, obs, settings)
    CAL_STATE.capacity_scale = scale
    CAL_STATE.observations = len(obs)
    CAL_STATE.edges_adjusted = len(scale)
    CAL_STATE.note = f"calibrated against {len(obs)} observation(s) on '{scenario}'"
    log.info("calibration updated: %d obs -> %d edges adjusted", len(obs), len(scale))
    return {"updated": True, "observations": len(obs),
            "edges_adjusted": len(scale), "calibration": CAL_STATE.as_dict()}


@app.post("/api/calibration/reset")
def calibration_reset():
    """Clear any active calibration (revert to textbook capacities)."""
    CAL_STATE.capacity_scale = {}
    CAL_STATE.observations = 0
    CAL_STATE.edges_adjusted = 0
    CAL_STATE.note = "reset"
    return {"reset": True, "calibration": CAL_STATE.as_dict()}


# ----------------------------------------------------------------------------
# M2 — Delay Propagation & Smart Rescheduling (Delhi → Kanpur corridor)
# ----------------------------------------------------------------------------
from app.m2_delay import service as m2_service  # noqa: E402


class M2Request(BaseModel):
    scenario: str
    optimize: bool = True


@app.get("/api/m2/network")
def m2_network():
    """Corridor geometry (stations, sections) + the planned train sheet."""
    return m2_service.network_payload()


@app.get("/api/m2/scenarios")
def m2_scenarios():
    return m2_service.scenarios_payload()


@app.post("/api/m2/simulate")
def m2_simulate(req: M2Request):
    """Propagate the disruption (FCFS) and, if optimize, the rescheduled plan."""
    out = m2_service.simulate_payload(req.scenario, req.optimize)
    if out is None:
        raise HTTPException(404, f"unknown M2 scenario '{req.scenario}'")
    return out


# ----------------------------------------------------------------------------
# M6 — Kavach Gap Analysis (coverage map + accident correlation)
# ----------------------------------------------------------------------------
from app.m6_kavach import service as m6_service  # noqa: E402


@app.get("/api/m6/coverage")
def m6_coverage():
    """Kavach coverage map: corridors with status, geometry, and risk exposure."""
    return m6_service.coverage_payload()


@app.get("/api/m6/correlation")
def m6_correlation():
    """Kavach gap × accident correlation (indicative policy analysis)."""
    return m6_service.correlation_payload()


# ----------------------------------------------------------------------------
# Policy register — preview a rule change, activate it, inspect the history
# ----------------------------------------------------------------------------
from fastapi import Header  # noqa: E402
from app.accounts.service import AccountError, AccountService  # noqa: E402
from app.accounts.store import build_account_store  # noqa: E402
from app.policy.schema import PolicyError  # noqa: E402
from app.policy.service import PolicyConflict, PolicyService  # noqa: E402
from app.policy.store import build_policy_store  # noqa: E402

POLICY = PolicyService(build_policy_store(settings), settings)
POLICY.bootstrap()   # restore the policy in force (or seed the genesis version)
ACCOUNTS = AccountService(build_account_store(settings))

USER_HEADER = "x-railsetu-user"


def require_user(x_railsetu_user: str | None = Header(default=None)):
    """Resolve the signed-in account, or refuse the request.

    The policy surface is gated here rather than only in the UI: hiding a tab
    is a presentation choice, and a change register whose writes can be made
    without an identity is not a register at all.
    """
    account = ACCOUNTS.resolve(x_railsetu_user)
    if account is None:
        raise HTTPException(401, "sign in to view or change the operating policy")
    return account


class SignInRequest(BaseModel):
    email: str


@app.post("/api/session")
def session_sign_in(req: SignInRequest):
    """Register an address as the current user."""
    try:
        return {"account": ACCOUNTS.sign_in(req.email).public()}
    except AccountError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/session")
def session_current(x_railsetu_user: str | None = Header(default=None)):
    """Who the caller is, if anyone. Used to restore a session on page load."""
    account = ACCOUNTS.resolve(x_railsetu_user)
    return {"account": account.public() if account else None}


@app.delete("/api/session")
def session_sign_out(x_railsetu_user: str | None = Header(default=None)):
    ACCOUNTS.touch_sign_out(x_railsetu_user or "")
    return {"signed_out": True}


@app.get("/api/accounts")
def accounts_list(_user=Depends(require_user)):
    """Everyone the platform has seen — the people behind the change history."""
    return ACCOUNTS.list_payload()


class DraftRequest(BaseModel):
    text: str


class LocationPayload(BaseModel):
    """What the browser was able to determine, with the author's permission."""
    available: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    captured_at: str | None = None
    reason: str | None = None


class ActivateRequest(BaseModel):
    text: str
    title: str
    description: str = ""
    location: LocationPayload | None = None


class RollbackRequest(BaseModel):
    version_id: str
    location: LocationPayload | None = None


class RevertRequest(BaseModel):
    version_id: str
    location: LocationPayload | None = None


def _client_ip(request: Request) -> str | None:
    """The caller's address as the server actually saw it.

    nginx terminates TLS and proxies, so the socket address is always
    127.0.0.1; the original is in X-Forwarded-For, whose FIRST entry is the
    client and the rest the proxy chain.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


@app.get("/api/policy/library")
def policy_library(_user=Depends(require_user)):
    """Every policy document, and where each one currently stands."""
    return POLICY.library_payload()


class NewDocumentRequest(BaseModel):
    """file type -> name -> body."""
    format: str
    title: str
    summary: str = ""
    department: str = ""
    text: str
    location: LocationPayload | None = None


@app.post("/api/policy/documents")
def policy_document_create(req: NewDocumentRequest, request: Request,
                           user=Depends(require_user)):
    """Add a written standard to the library, recorded like any other change."""
    try:
        return POLICY.create_document(
            title=req.title, summary=req.summary, department=req.department,
            fmt=req.format, text=req.text,
            author_name=user.display_name, author_email=user.email,
            location=req.location.model_dump() if req.location else None,
            client_ip=_client_ip(request))
    except PolicyError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/policy/documents/{key}")
def policy_document(key: str, _user=Depends(require_user)):
    """One document: its text in force, and which version that is."""
    out = POLICY.document_payload(key)
    if out is None:
        raise HTTPException(404, f"unknown policy document '{key}'")
    return out


@app.get("/api/policy/documents/{key}/default")
def policy_document_default(key: str, _user=Depends(require_user)):
    """The text this document shipped with — lets the editor offer a reset."""
    text = POLICY.default_text(key)
    if text is None:
        raise HTTPException(404, f"unknown policy document '{key}'")
    return {"key": key, "text": text}


@app.post("/api/policy/documents/{key}/validate")
def policy_document_validate(key: str, req: DraftRequest, _user=Depends(require_user)):
    """Cheap check for live feedback while typing."""
    return POLICY.validate_payload(key, req.text)


@app.post("/api/policy/documents/{key}/preview")
def policy_document_preview(key: str, req: DraftRequest, _user=Depends(require_user)):
    """Run the real models under the library as it stands, and with this draft.

    This is the 'before activation' step: it reports what the change would do
    without writing anything or altering the rules in force.
    """
    return POLICY.preview(key, req.text, _run)


@app.post("/api/policy/documents/{key}/activate")
def policy_document_activate(key: str, req: ActivateRequest, request: Request,
                             user=Depends(require_user)):
    """Record an immutable version of this document and put it in force.

    Attribution comes from the signed-in account, never from the request body —
    so a change cannot be recorded against someone the caller merely names.
    """
    try:
        return POLICY.activate(
            key, req.text, title=req.title, description=req.description,
            author_name=user.display_name, author_email=user.email, run_crowd=_run,
            location=req.location.model_dump() if req.location else None,
            client_ip=_client_ip(request),
        )
    except PolicyError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/policy/documents/{key}/history")
def policy_document_history(key: str, limit: int = Query(50, ge=1, le=200),
                            _user=Depends(require_user)):
    """Every activation of this document, newest first."""
    out = POLICY.history_payload(key, limit)
    if out is None:
        raise HTTPException(404, f"unknown policy document '{key}'")
    return out


@app.get("/api/policy/documents/{key}/versions/{version_id}")
def policy_document_version(key: str, version_id: str, _user=Depends(require_user)):
    """One version: its text, its diff against its parent, what changed."""
    out = POLICY.version_payload(key, version_id)
    if out is None:
        raise HTTPException(404, f"unknown version '{version_id}' for '{key}'")
    return out


@app.post("/api/policy/documents/{key}/revert")
def policy_document_revert(key: str, req: RevertRequest, request: Request,
                           user=Depends(require_user)):
    """Back out ONE earlier change, keeping every later one — like `git revert`.

    Returns 409 with the conflicting blocks when a later version has already
    edited the same lines, rather than producing a document nobody authored.
    """
    try:
        return POLICY.revert_change(
            key, req.version_id, author_name=user.display_name,
            author_email=user.email, run_crowd=_run,
            location=req.location.model_dump() if req.location else None,
            client_ip=_client_ip(request))
    except PolicyConflict as exc:
        raise HTTPException(409, {"message": str(exc), "conflicts": exc.conflicts,
                                  "seq": exc.seq})
    except PolicyError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/policy/documents/{key}/rollback")
def policy_document_rollback(key: str, req: RollbackRequest, request: Request,
                             user=Depends(require_user)):
    """Reinstate an earlier text — recorded as a new version, not a rewrite."""
    try:
        return POLICY.rollback(
            key, req.version_id, author_name=user.display_name,
            author_email=user.email, run_crowd=_run,
            location=req.location.model_dump() if req.location else None,
            client_ip=_client_ip(request))
    except PolicyError as exc:
        raise HTTPException(400, str(exc))

# M3 — Rail Surface Defect Inspection (EfficientNet-B0 + YOLO11-s)
# ----------------------------------------------------------------------------
from app.m3_defect import service as m3_service  # noqa: E402

# Phone photos are routinely 3-8 MB. The cap exists so a hostile upload cannot
# park hundreds of MB in the single worker's memory, not to stop normal use.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@app.get("/api/m3/status")
def m3_status():
    """Readiness, device, architectures and published test metrics."""
    return m3_service.status()


@app.post("/api/m3/warm")
def m3_warm():
    """Force the model load now, so the first real request does not pay for it."""
    return m3_service.warm()


@app.get("/api/m3/samples")
def m3_samples():
    """The bundled held-out test photos, with ground truth where it is known."""
    return {"samples": m3_service.list_samples()}


@app.get("/api/m3/samples/{sample_id:path}")
def m3_sample(sample_id: str):
    path = m3_service.sample_path(sample_id)
    if path is None:
        raise HTTPException(404, f"unknown sample '{sample_id}'")
    return FileResponse(path, media_type="image/jpeg")


@app.post("/api/m3/analyse")
async def m3_analyse(
    file: UploadFile | None = File(default=None),
    sample: str | None = Form(default=None),
    localizer: bool = Form(default=True),
    cam: bool = Form(default=True),
    conf: float | None = Form(default=None),
):
    """Run both models over one image — uploaded, or one of the bundled samples."""
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"image exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        frame_id = Path(file.filename).stem
    elif sample:
        path = m3_service.sample_path(sample)
        if path is None:
            raise HTTPException(404, f"unknown sample '{sample}'")
        data = path.read_bytes()
        frame_id = path.stem
    else:
        raise HTTPException(400, "provide either an uploaded file or a sample id")

    try:
        return m3_service.analyse(
            data,
            localizer=localizer,
            cam=cam,
            conf=settings.m3_conf if conf is None else conf,
            frame_id=frame_id,
        )
    except RuntimeError as exc:            # models unavailable -> not the caller's fault
        raise HTTPException(503, str(exc))
    except HTTPException:
        raise
    except Exception as exc:               # unreadable/corrupt image
        log.exception("m3: analyse failed")
        raise HTTPException(400, f"could not analyse image: {exc}")
