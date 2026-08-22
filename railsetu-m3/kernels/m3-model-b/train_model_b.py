"""RailSetu M3 · Model B — rail surface defect localizer.

Single class, `defect`. Model A answers *what* the surface condition is;
Model B answers *where* on the railhead it is.

Training data (277 images, 493 boxes) merges the only two annotated sources:
  RSDDs        113 images with pixel ground-truth masks -> connected-component boxes
  cracks-coco  164 images with COCO bounding boxes

The Mendeley crack images are NOT included: all 40 are one contiguous frame run,
i.e. a single physical crack photographed 40 times. They would add no signal and
would leak across any split.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

INPUT_ROOT = Path("/kaggle/input")
OUT = Path("/kaggle/working")


def resolve_data_root(marker: str = "data.yaml") -> Path:
    """Locate the attached dataset, failing loudly with what *is* mounted.

    Kaggle does not mount at a fixed depth -- the same dataset has appeared at
    both /kaggle/input/<slug>/ and /kaggle/input/datasets/<owner>/<slug>/ --
    so search recursively rather than assuming a level.
    """
    candidates = sorted(INPUT_ROOT.rglob(marker))
    if candidates:
        # shallowest match wins, so a nested copy never shadows the real root
        return min(candidates, key=lambda p: len(p.parts)).parent
    mounted = [str(p) for p in INPUT_ROOT.rglob("*") if p.is_dir()][:40]
    raise SystemExit(
        f"could not find {marker} under {INPUT_ROOT}.\n"
        f"mounted dirs: {mounted or '(none - dataset failed to attach)'}"
    )


DATA = resolve_data_root()
print(f"data root: {DATA}")
EPOCHS = 120
IMG_SIZE = 640
BATCH = 16
SEED = 1337

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics"], check=True)
from ultralytics import YOLO  # noqa: E402

import torch  # noqa: E402

print(f"cuda={torch.cuda.is_available()} | {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'}")

# ultralytics needs a writable copy of the data, but anything under
# /kaggle/working becomes kernel *output* -- staging there means every future
# download drags all 277 training images along before reaching the weights.
# /kaggle/tmp is writable and is not collected as output.
SCRATCH = Path("/kaggle/tmp")
SCRATCH.mkdir(parents=True, exist_ok=True)
stage = SCRATCH / "dataset"
if stage.exists():
    shutil.rmtree(stage)
shutil.copytree(DATA, stage)

data_yaml = stage / "data.yaml"
data_yaml.write_text(
    f"path: {stage}\n"
    "train: images/train\n"
    "val: images/val\n"
    "nc: 1\n"
    "names: [defect]\n"
)
print(data_yaml.read_text())

for split in ("train", "val"):
    n_img = len(list((stage / "images" / split).glob("*.jpg")))
    n_lbl = len(list((stage / "labels" / split).glob("*.txt")))
    print(f"{split}: {n_img} images, {n_lbl} label files")

model = YOLO("yolo11s.pt")
results = model.train(
    data=str(data_yaml),
    epochs=EPOCHS,
    imgsz=IMG_SIZE,
    batch=BATCH,
    seed=SEED,
    project=str(SCRATCH / "runs"),
    name="model_b",
    exist_ok=True,
    patience=30,
    # 277 images is small: lean hard on augmentation, and keep mosaic off at the
    # end so the model sees realistic full frames before training stops
    close_mosaic=15,
    degrees=10.0,
    translate=0.15,
    scale=0.5,
    fliplr=0.5,
    flipud=0.3,
    hsv_v=0.4,
    hsv_s=0.5,
    plots=True,
    verbose=True,
)

metrics = model.val(data=str(data_yaml), imgsz=IMG_SIZE, plots=True)
box = metrics.box
summary = {
    "model": "yolo11s",
    "classes": ["defect"],
    "epochs_requested": EPOCHS,
    "map50": float(box.map50),
    "map50_95": float(box.map),
    "precision": float(box.mp),
    "recall": float(box.mr),
    "save_dir": str(results.save_dir),
}
print(json.dumps(summary, indent=2))
(OUT / "metrics_model_b.json").write_text(json.dumps(summary, indent=2))

best = Path(results.save_dir) / "weights" / "best.pt"
if best.exists():
    shutil.copy(best, OUT / "model_b_best.pt")
    print(f"saved model_b_best.pt ({best.stat().st_size / 1e6:.1f} MB)")

# copy only the small diagnostic plots into the output, not the whole run dir
for plot in ("results.png", "PR_curve.png", "confusion_matrix.png", "val_batch0_pred.jpg"):
    src = Path(results.save_dir) / plot
    if src.exists():
        shutil.copy(src, OUT / plot)

print("output contents:", sorted(p.name for p in OUT.iterdir()))
