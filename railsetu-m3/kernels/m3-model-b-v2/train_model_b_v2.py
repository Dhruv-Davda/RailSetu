"""RailSetu M3 · Model B v2 — localizer retrained with ballast background negatives.

v1 (mAP@50 0.828) was trained only on tight railhead close-ups: RSDDs crops and
Roboflow crack crops, every one of which contained at least one defect. It had
therefore never seen ballast, and had no concept of "this image contains
nothing". Run on the wide 1280x720 Mendeley track frames it boxed gravel --
measured at 2.6 boxes per frame, firing on 12 of 12 images.

The fix is background negatives, but they have to be mined carefully. The
Mendeley frames CANNOT be used whole: every one of them is a defect image, so
labelling a full frame empty would teach the model that a genuine rail defect is
not a defect.

Instead only the ballast shoulders are taken. In these vehicle-mounted EKEN
frames the railhead runs vertically through the centre, at its widest spanning
roughly x 350-900, so the strips x<300 and x>980 are ballast, sleepers,
fasteners and litter in every frame inspected -- never railhead. Cropping there
teaches "gravel is not a defect" without ever asserting anything false about a
rail surface.

The validation set is left EXACTLY as v1: the same 56 positive images, so
mAP@50 stays directly comparable to 0.828 and any recall lost to the negatives
is visible rather than hidden.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

INPUT_ROOT = Path("/kaggle/input")
OUT = Path("/kaggle/working")
SCRATCH = Path("/kaggle/tmp")

EPOCHS = 120
IMG_SIZE = 640
BATCH = 16
SEED = 1337

# Negative mining. 110 frames x 2 shoulders = 220 negatives against 221 positive
# train images. That is far above the usual 10% background guidance, which is
# deliberate: the failure being corrected is a domain shift, not label noise.
N_NEG_FRAMES = 110
LEFT_MAX_X = 300     # right edge of the guaranteed-ballast left shoulder
RIGHT_MIN_X = 980    # left edge of the guaranteed-ballast right shoulder
MIN_CROP_W, MIN_CROP_H = 200, 300

# Wide-frame diagnostic: how many boxes does the finished model draw on full
# Mendeley frames? v1 averaged 2.6. Lower is better, but not zero -- these frames
# really do contain defects.
N_WIDE_EVAL = 60

rng = np.random.default_rng(SEED)


def resolve(marker: str) -> Path:
    """Locate an attached dataset by a marker file, failing loudly."""
    hits = sorted(INPUT_ROOT.rglob(marker))
    if hits:
        return min(hits, key=lambda p: len(p.parts)).parent
    mounted = [str(p) for p in INPUT_ROOT.rglob("*") if p.is_dir()][:40]
    raise SystemExit(f"could not find {marker} under {INPUT_ROOT}.\nmounted: {mounted}")


LOC = resolve("data.yaml")       # railsetu-m3-localization
COND = resolve("manifest.csv")   # railsetu-m3-condition
print(f"localization: {LOC}\ncondition   : {COND}")

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics"], check=True)
from ultralytics import YOLO  # noqa: E402

import torch  # noqa: E402
print(f"cuda={torch.cuda.is_available()} | {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'}")

# ---- stage the v1 dataset ---------------------------------------------------
# /kaggle/working is collected as kernel output; staging there would drag every
# training image into the download. /kaggle/tmp is writable and is not collected.
SCRATCH.mkdir(parents=True, exist_ok=True)
stage = SCRATCH / "dataset"
if stage.exists():
    shutil.rmtree(stage)
shutil.copytree(LOC, stage)

before = {s: len(list((stage / "images" / s).glob("*.jpg"))) for s in ("train", "val")}
print(f"v1 positives: {before}")

# ---- mine ballast negatives -------------------------------------------------
manifest = pd.read_csv(COND / "manifest.csv")
train_rows = manifest[manifest["split"] == "train"]

# spread the sample across classes so no single surface texture dominates
per_class = max(1, N_NEG_FRAMES // train_rows["label"].nunique())
picked = (
    train_rows.groupby("label", group_keys=False)
    .apply(lambda d: d.sample(min(per_class, len(d)), random_state=SEED))
    .reset_index(drop=True)
)
print(f"negative source frames: {len(picked)} | {picked['label'].value_counts().to_dict()}")

neg_img_dir = stage / "images" / "train"
neg_lbl_dir = stage / "labels" / "train"
n_neg = 0
for i, row in picked.iterrows():
    src = COND / row["filepath"]
    if not src.exists():
        continue
    img = Image.open(src).convert("RGB")
    W, H = img.size
    if W < 1000:  # unexpected geometry -> skip rather than crop blindly
        continue
    for side, (x_lo, x_hi) in (("l", (0, LEFT_MAX_X)), ("r", (RIGHT_MIN_X, W))):
        span = x_hi - x_lo
        if span < MIN_CROP_W:
            continue
        cw = int(rng.integers(MIN_CROP_W, span + 1))
        ch = int(rng.integers(MIN_CROP_H, H + 1))
        x0 = int(rng.integers(x_lo, x_hi - cw + 1))
        y0 = int(rng.integers(0, H - ch + 1))
        crop = img.crop((x0, y0, x0 + cw, y0 + ch))
        stem = f"neg_{i:04d}_{side}"
        crop.save(neg_img_dir / f"{stem}.jpg", quality=92)
        (neg_lbl_dir / f"{stem}.txt").write_text("")  # empty label = background
        n_neg += 1

after = {s: len(list((stage / "images" / s).glob("*.jpg"))) for s in ("train", "val")}
print(f"mined {n_neg} ballast negatives | train {before['train']} -> {after['train']} | val unchanged at {after['val']}")

data_yaml = stage / "data.yaml"
data_yaml.write_text(
    f"path: {stage}\ntrain: images/train\nval: images/val\nnc: 1\nnames: [defect]\n"
)

# ---- train ------------------------------------------------------------------
model = YOLO("yolo11s.pt")
results = model.train(
    data=str(data_yaml),
    epochs=EPOCHS,
    imgsz=IMG_SIZE,
    batch=BATCH,
    seed=SEED,
    project=str(SCRATCH / "runs"),
    name="model_b_v2",
    exist_ok=True,
    patience=30,
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

# ---- wide-frame diagnostic --------------------------------------------------
# The number that motivated this retrain. Held-out Mendeley test-split frames,
# full 1280x720, at the same confidence floor the app uses.
wide = manifest[manifest["split"] == "test"].sample(
    min(N_WIDE_EVAL, (manifest["split"] == "test").sum()), random_state=SEED
)
wide_paths = [str(COND / p) for p in wide["filepath"] if (COND / p).exists()]
best_w = Path(results.save_dir) / "weights" / "best.pt"
tuned = YOLO(str(best_w))
total_boxes, hit_images = 0, 0
for p in wide_paths:
    det = tuned.predict(source=p, conf=0.25, verbose=False)[0]
    n = len(det.boxes)
    total_boxes += n
    hit_images += int(n > 0)
wide_bpi = total_boxes / max(1, len(wide_paths))
print(f"\nwide frames: {len(wide_paths)} | {total_boxes} boxes | {wide_bpi:.2f} per frame | {hit_images} frames with >=1 box")
print("(v1 baseline on wide frames: 2.58 boxes per frame, 12/12 frames firing)")

summary = {
    "model": "yolo11s",
    "variant": "v2_background_negatives",
    "classes": ["defect"],
    "epochs_requested": EPOCHS,
    "train_positives": before["train"],
    "train_negatives": n_neg,
    "val_images": after["val"],
    "map50": float(box.map50),
    "map50_95": float(box.map),
    "precision": float(box.mp),
    "recall": float(box.mr),
    "v1_map50": 0.8278185954312213,
    "wide_frames_evaluated": len(wide_paths),
    "wide_frame_boxes_per_image": round(wide_bpi, 3),
    "wide_frames_with_boxes": hit_images,
    "v1_wide_frame_boxes_per_image": 2.58,
    "save_dir": str(results.save_dir),
}
print(json.dumps(summary, indent=2))
(OUT / "metrics_model_b_v2.json").write_text(json.dumps(summary, indent=2))

if best_w.exists():
    shutil.copy(best_w, OUT / "model_b_v2_best.pt")
    print(f"saved model_b_v2_best.pt ({best_w.stat().st_size / 1e6:.1f} MB)")

for plot in ("results.png", "PR_curve.png", "confusion_matrix.png", "val_batch0_pred.jpg"):
    src = Path(results.save_dir) / plot
    if src.exists():
        shutil.copy(src, OUT / plot)

print("output contents:", sorted(p.name for p in OUT.iterdir()))
