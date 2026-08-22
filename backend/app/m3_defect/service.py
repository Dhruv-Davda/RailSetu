"""
M3 — Rail Surface Defect Inspection.

Two networks answer two different questions about one photograph:

  Model A  EfficientNet-B0   *what* the surface condition is  (4 classes)
  Model B  YOLO11-s          *where* the damage is            (1 class, `defect`)

Neither is useful alone. Together they produce an inspection record: a named
defect, a confidence, a location, and an estimated severity.

`railsetu-m3/predict.py` is the CLI twin of this module. Rather than
re-implementing checkpoint loading, preprocessing and Grad-CAM here -- where the
two copies would silently drift apart -- this imports that file and drives it.
The API and the command line therefore cannot disagree about what the models do.

Torch is imported lazily, on the first request that needs it. Importing at
module load would cost the whole backend several seconds of start-up and a few
hundred MB of RSS for a feature most requests never touch, and would take the
entire API down on a box where the ML extras are not installed. Instead a
missing runtime degrades to `available: false` with the reason attached, and the
UI says so plainly.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import logging
import threading
from pathlib import Path
from time import perf_counter

log = logging.getLogger("railsetu.m3")

# backend/app/m3_defect/service.py -> repo root is four levels up
REPO_ROOT = Path(__file__).resolve().parents[3]
M3_ROOT = REPO_ROOT / "railsetu-m3"
PREDICT_PY = M3_ROOT / "predict.py"
TESTPACK = M3_ROOT / "testpack"

MODEL_A_FILE = "model_a_best.pt"
# v2 was retrained with ballast background negatives; prefer it when present so
# a dropped-in upgrade needs no code change, but keep working without it.
MODEL_B_FILES = ("model_b_v2_best.pt", "model_b_best.pt")

# Transport ceiling for the returned image. 1100px keeps a 1280x720 frame
# essentially full-size while bounding the base64 payload to a few hundred KB.
MAX_SIDE = 1100
JPEG_Q = 88

# The photo folders shipped for testing. rail_frames are wide 1280x720 track
# shots (Model A's domain); railhead_crops are tight close-ups (Model B's).
SAMPLE_FOLDERS = {
    "rail_frames": {
        "kind": "Track frame",
        "note": "Wide 1280x720 frame, vehicle-mounted camera — Model A's training domain.",
    },
    "railhead_crops": {
        "kind": "Railhead crop",
        "note": "Tight railhead close-up — Model B's training domain.",
    },
}

# Filmstrip order. The crack close-ups lead because they are the clearest
# defect to read at thumbnail size and the domain Model B is strongest in;
# squats follow as the most serious of the four surface conditions.
FOLDER_ORDER = {"railhead_crops": 0, "rail_frames": 1}
CLASS_ORDER = {"squat": 0, "flaking": 1, "spalling": 2, "shelling": 3}

# Shelling is the weakest class (F1 0.45 on 19 held-out images) and six near
# identical thumbnails of it crowded the strip without adding information.
MAX_PER_CLASS = {"shelling": 2}

_LOCK = threading.Lock()      # guards both loading and inference
_M: dict = {"tried": False, "ok": False, "error": None}


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def _artifacts_dir() -> Path:
    from app.config import get_settings

    override = get_settings().m3_artifacts_dir.strip()
    return Path(override).expanduser() if override else M3_ROOT / "artifacts"


def _weight_paths() -> tuple[Path | None, Path | None]:
    d = _artifacts_dir()
    a = d / MODEL_A_FILE
    b = next((d / n for n in MODEL_B_FILES if (d / n).exists()), None)
    return (a if a.exists() else None), b


def _read_metrics() -> dict:
    """Published test metrics, read from the training run's own output."""
    d = _artifacts_dir()
    out: dict = {}
    a = d / "metrics_model_a.json"
    if a.exists():
        try:
            m = json.loads(a.read_text())
            out["a"] = {
                "macro_f1": round(m.get("test_macro_f1", 0), 3),
                "accuracy": round(m.get("test_accuracy", 0), 3),
                "per_class": {
                    k: round(v["f1-score"], 2)
                    for k, v in m.get("test_report", {}).items()
                    if isinstance(v, dict) and "f1-score" in v and k in m.get("classes", [])
                },
                "split_sizes": m.get("split_sizes", {}),
            }
        except Exception as exc:  # a corrupt metrics file must not break inference
            log.warning("m3: unreadable metrics_model_a.json (%s)", exc)
    for name in ("metrics_model_b_v2.json", "metrics_model_b.json"):
        p = d / name
        if not p.exists():
            continue
        try:
            m = json.loads(p.read_text())
            out["b"] = {
                "map50": round(m.get("map50", 0), 3),
                "map50_95": round(m.get("map50_95", 0), 3),
                "precision": round(m.get("precision", 0), 3),
                "recall": round(m.get("recall", 0), 3),
                "variant": m.get("variant", "v1"),
                "wide_frame_boxes_per_image": m.get("wide_frame_boxes_per_image"),
            }
            break
        except Exception as exc:
            log.warning("m3: unreadable %s (%s)", name, exc)
    return out


# ---------------------------------------------------------------------------
# lazy load
# ---------------------------------------------------------------------------
def _load() -> None:
    """Import torch, load both checkpoints. Runs once; records why if it fails."""
    if _M["tried"]:
        return
    _M["tried"] = True
    t0 = perf_counter()
    try:
        path_a, path_b = _weight_paths()
        if path_a is None:
            raise FileNotFoundError(
                f"{MODEL_A_FILE} not found in {_artifacts_dir()} — "
                "model weights are not committed to git; fetch them into that folder."
            )
        if not PREDICT_PY.exists():
            raise FileNotFoundError(f"{PREDICT_PY} missing — the M3 module is incomplete.")

        from app.config import get_settings

        spec = importlib.util.spec_from_file_location("railsetu_m3_predict", PREDICT_PY)
        pred = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pred)  # this is where torch actually gets imported

        device = pred.pick_device(get_settings().m3_device)
        cond = pred.ConditionModel(path_a, device)

        det = None
        n_b = 0
        if path_b is not None:
            from ultralytics import YOLO

            det = YOLO(str(path_b))
            n_b = sum(p.numel() for p in det.model.parameters())

        _M.update(
            ok=True,
            pred=pred,
            cond=cond,
            det=det,
            device=str(device),
            path_a=path_a,
            path_b=path_b,
            params_a=sum(p.numel() for p in cond.model.parameters()),
            params_b=n_b,
            load_ms=round((perf_counter() - t0) * 1000),
        )
        log.info(
            "m3: loaded on %s in %dms (A=%s, B=%s)",
            device, _M["load_ms"], path_a.name, path_b.name if path_b else "none",
        )
    except Exception as exc:
        _M["error"] = f"{type(exc).__name__}: {exc}"
        log.warning("m3: unavailable — %s", _M["error"])


# ---------------------------------------------------------------------------
# public surface
# ---------------------------------------------------------------------------
def status() -> dict:
    """Report readiness without forcing a load, unless a load has been tried."""
    path_a, path_b = _weight_paths()
    out = {
        "loaded": bool(_M.get("ok")),
        "error": _M.get("error"),
        "device": _M.get("device"),
        "load_ms": _M.get("load_ms"),
        "weights_present": {"model_a": path_a is not None, "model_b": path_b is not None},
        "artifacts_dir": str(_artifacts_dir()),
        "n_samples": len(list_samples()),
        "metrics": _read_metrics(),
        "models": [
            {
                "key": "a",
                "name": "Model A · Condition",
                "arch": "EfficientNet-B0",
                "task": "classification",
                "question": "What is wrong with the rail surface?",
                "classes": _M["cond"].classes if _M.get("ok") else
                           ["flaking", "shelling", "spalling", "squat"],
                "input": "224x224 RGB, ImageNet normalised",
                "params": _M.get("params_a"),
                "file": path_a.name if path_a else None,
            },
            {
                "key": "b",
                "name": "Model B · Localizer",
                "arch": "YOLO11-s",
                "task": "detection",
                "question": "Where on the railhead is the damage?",
                "classes": ["defect"],
                "input": "640x640 letterboxed",
                "params": _M.get("params_b"),
                "file": path_b.name if path_b else None,
            },
        ],
    }
    return out


def warm() -> dict:
    """Force the load now — used at start-up so no user pays the first-load cost."""
    _load()
    return status()


def list_samples() -> list[dict]:
    """The bundled test photos, ordered for the filmstrip.

    Ground truth comes from the filename prefix, so a viewer can mark the
    model's answer without being told it.
    """
    found: list[dict] = []
    for folder, meta in SAMPLE_FOLDERS.items():
        d = TESTPACK / folder
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.jpg")):
            # rail_frames are named <trueclass>_<video>_<frame>.jpg; the crops
            # carry no class label of their own.
            truth = p.stem.split("_")[0] if folder == "rail_frames" else None
            found.append({
                "id": f"{folder}/{p.name}",
                "folder": folder,
                "kind": meta["kind"],
                "note": meta["note"],
                "name": p.name,
                "truth": truth,
            })

    # Cap over-represented classes. Filename order is stable, so "the first two"
    # means the same two photographs on every machine.
    kept, seen = [], {}
    for s in found:
        cap = MAX_PER_CLASS.get(s["truth"])
        if cap is not None:
            seen[s["truth"]] = seen.get(s["truth"], 0) + 1
            if seen[s["truth"]] > cap:
                continue
        kept.append(s)

    kept.sort(key=lambda s: (
        FOLDER_ORDER.get(s["folder"], 9),
        CLASS_ORDER.get(s["truth"], 9),
        s["name"],
    ))
    return kept


def sample_path(sample_id: str) -> Path | None:
    """Resolve a sample id, but only if it is one we actually enumerated.

    Matching against the known list rather than joining user input onto a base
    path is what makes `../../etc/passwd` a 404 instead of a file read.
    """
    if sample_id not in {s["id"] for s in list_samples()}:
        return None
    p = TESTPACK / sample_id
    return p if p.is_file() else None


def _fit(img, max_side: int):
    from PIL import Image

    if max(img.size) <= max_side:
        return img
    scale = max_side / max(img.size)
    return img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.LANCZOS,
    )


def _to_data_uri(img, quality: int = JPEG_Q) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def analyse(
    data: bytes,
    *,
    localizer: bool = True,
    cam: bool = True,
    conf: float = 0.25,
    frame_id: str = "upload",
) -> dict:
    """Run the full pipeline over one image, timing each stage.

    Stage timings are measured, not estimated — the UI shows them to make the
    work visible instead of hiding two networks behind a spinner.
    """
    _load()
    if not _M.get("ok"):
        raise RuntimeError(_M.get("error") or "M3 models are not loaded")

    from PIL import Image

    pred, cond, det = _M["pred"], _M["cond"], _M["det"]
    timings: dict[str, float] = {}

    with _LOCK:  # torch hooks + backward are not safe to run concurrently
        t = perf_counter()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img = _fit(img, MAX_SIDE)
        timings["decode"] = (perf_counter() - t) * 1000

        t = perf_counter()
        condition, cam_map = cond.predict(img, want_cam=cam)
        timings["classify"] = (perf_counter() - t) * 1000

        t = perf_counter()
        boxes, scores = [], []
        if localizer and det is not None:
            res = det.predict(source=img, conf=conf, device=_M["device"], verbose=False)[0]
            for b in res.boxes:
                boxes.append([round(float(v), 1) for v in b.xyxy[0].tolist()])
                scores.append(float(b.conf[0]))
        timings["localize"] = (perf_counter() - t) * 1000

        t = perf_counter()
        sev = pred.severity(condition, boxes, img)
        timings["severity"] = (perf_counter() - t) * 1000

        t = perf_counter()
        payload_img = _to_data_uri(img)
        overlay = None
        if cam and cam_map is not None:
            import numpy as np

            heat = np.zeros((img.height, img.width, 3), dtype=np.float32)
            heat[..., 0] = cam_map  # red channel carries attention
            base = np.asarray(img, dtype=np.float32) / 255.0
            blend = np.clip(base * 0.72 + heat * 0.28, 0, 1)
            overlay = _to_data_uri(Image.fromarray((blend * 255).astype(np.uint8)))
        timings["render"] = (perf_counter() - t) * 1000

    W, H = img.width, img.height
    return {
        "frame_id": frame_id,
        "width": W,
        "height": H,
        "image": payload_img,
        "overlay": overlay,
        "condition": condition,
        "defects": [
            {
                "bbox_xyxy": b,
                # normalised so the UI can place boxes at any display size
                "bbox_pct": [
                    round(b[0] / W * 100, 3), round(b[1] / H * 100, 3),
                    round((b[2] - b[0]) / W * 100, 3), round((b[3] - b[1]) / H * 100, 3),
                ],
                "confidence": round(s, 3),
                "provenance": "Modelled",
            }
            for b, s in zip(boxes, scores)
        ],
        "defect_count": len(boxes),
        "severity": sev,
        "localizer_ran": bool(localizer and det is not None),
        "timings_ms": {k: round(v, 1) for k, v in timings.items()}
        | {"total": round(sum(timings.values()), 1)},
        "device": _M["device"],
    }
