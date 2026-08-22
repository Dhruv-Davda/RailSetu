"""Build the Model A (surface condition classification) split manifest.

The Mendeley "Railway Track Surface Faults Dataset" is video-derived: filenames
look like `1.MOV_20201221091849_5158.JPEG`, i.e. <video>_<capture-ts>_<frame>.
Frames were sampled from 120 FPS footage, so consecutive frame indices are
near-duplicate views of the same piece of rail.

A random train/test split therefore leaks: frame 5158 lands in train and 5159 in
test, and the model scores ~99% by recognising images it has effectively seen.

There are only 6 source videos (1,3,4,5,6.MOV and 7.MOV), so a strict
split-by-video would leave some classes with no validation data at all.

The right unit is the **run**: a maximally contiguous span of frame indices
within one video, which corresponds to one physical defect swept by the camera.
Measured run structure:

    class       images   runs
    Flakings      2829     88
    Squats        1842    284
    Spallings      291     31
    Shellings      130     23
    Cracks          40      1   <- all 40 crack frames are ONE defect

Whole runs are assigned to a single split, so no physical defect appears on both
sides of the split. Image counts, not run counts, are balanced toward 70/15/15,
because runs vary in length from 4 to 239 frames.

Emits a manifest CSV; no image data is copied or modified.
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

# Model A classes. Cracks (40) go to Model B, which localizes rather than classifies.
# Joints (11) and Grooves (8) are excluded: a rail joint is a normal structural
# feature, not a fault, and training on it teaches the model to flag healthy track.
CONDITION_CLASSES = ["Flakings", "Squats", "Spallings", "Shellings"]

RUN_GAP = 2  # frame-index gap above which a new run (= new physical defect) starts
TRAIN_FRAC, VAL_FRAC = 0.70, 0.15  # remainder -> test
SEED = 1337

NAME_RE = re.compile(r"^(?P<video>[^_]+)_(?P<ts>\d+)_(?P<frame>\d+)\.(?P<ext>\w+)$", re.I)


def parse_name(name: str):
    m = NAME_RE.match(name)
    if not m:
        return None
    return m.group("video"), int(m.group("frame"))


def find_runs(items: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """Group (frame, filename) pairs into maximally contiguous runs."""
    runs: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    prev = None
    for frame, name in sorted(items):
        if prev is not None and frame - prev > RUN_GAP:
            runs.append(current)
            current = []
        current.append((frame, name))
        prev = frame
    if current:
        runs.append(current)
    return runs


def assign_runs(runs: list[list], rng) -> list[str]:
    """Assign whole runs to train/val/test, balancing by image count.

    Runs are shuffled then placed greedily into whichever split is furthest
    below its target share. Longest-first would concentrate the big runs in
    train; shuffling keeps run-length distribution comparable across splits.
    """
    total = sum(len(r) for r in runs)
    targets = {
        "train": TRAIN_FRAC * total,
        "val": VAL_FRAC * total,
        "test": (1.0 - TRAIN_FRAC - VAL_FRAC) * total,
    }
    filled = {"train": 0, "val": 0, "test": 0}
    order = rng.permutation(len(runs))

    # guarantee val and test are non-empty even when runs are few
    assignment = [None] * len(runs)
    if len(runs) >= 3:
        for split, idx in zip(("val", "test"), order[:2]):
            assignment[idx] = split
            filled[split] += len(runs[idx])

    for idx in order:
        if assignment[idx] is not None:
            continue
        deficit = {s: targets[s] - filled[s] for s in targets}
        split = max(deficit, key=deficit.get)
        assignment[idx] = split
        filled[split] += len(runs[idx])
    return assignment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path, help="extracted Mendeley dataset dir")
    ap.add_argument("--out", required=True, type=Path, help="manifest CSV path")
    args = ap.parse_args()

    groups: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    unparsed = []

    for cls in CONDITION_CLASSES:
        cls_dir = args.root / cls
        if not cls_dir.is_dir():
            raise SystemExit(f"missing class directory: {cls_dir}")
        for img in cls_dir.iterdir():
            if img.suffix.lower() not in {".jpeg", ".jpg", ".png"}:
                continue
            parsed = parse_name(img.name)
            if parsed is None:
                unparsed.append(img.name)
                continue
            video, frame = parsed
            groups[(cls, video)].append((frame, img.name))

    rng = np.random.default_rng(SEED)
    rows = []
    run_stats: dict[str, dict[str, int]] = {}

    for cls in CONDITION_CLASSES:
        # runs are found per video, then pooled per class for assignment
        cls_runs: list[list] = []
        run_videos: list[str] = []
        for (c, video), items in groups.items():
            if c != cls:
                continue
            for run in find_runs(items):
                cls_runs.append(run)
                run_videos.append(video)

        assignment = assign_runs(cls_runs, rng)
        label = cls.rstrip("s").lower()  # Flakings -> flaking
        run_stats[label] = {"runs": len(cls_runs)}
        for split in ("train", "val", "test"):
            run_stats[label][f"{split}_runs"] = assignment.count(split)

        for run, video, split in zip(cls_runs, run_videos, assignment):
            for frame, fname in run:
                rows.append(
                    {
                        "filepath": f"{cls}/{fname}",
                        "label": label,
                        "video": video,
                        "frame": frame,
                        "split": split,
                    }
                )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["filepath", "label", "video", "frame", "split"])
        writer.writeheader()
        writer.writerows(rows)

    stats: dict = defaultdict(lambda: defaultdict(int))
    for r in rows:
        stats[r["label"]][r["split"]] += 1
    summary = {
        "kept": len(rows),
        "unparsed_filenames": len(unparsed),
        "per_class_images": {k: dict(v) for k, v in sorted(stats.items())},
        "per_class_runs": run_stats,
        "videos": sorted({r["video"] for r in rows}),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
