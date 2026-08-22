"""Build the Model B (defect localization) dataset in YOLO format.

Merges two annotated sources into one single-class detector dataset:

  RSDDs        113 rail-surface images with pixel ground-truth masks
               (Niu et al., IEEE TII 2021). Masks -> connected components -> boxes.
  cracks-coco  164 railway crack images with COCO bounding boxes
               (Roboflow via Kaggle harideepak/railway-cracks-coco).

Both collapse to a single class, `defect`. RSDDs masks mark rail surface defects
generally, not cracks specifically, so labelling the merged set "crack" would be
wrong -- Model B answers *where*, Model A answers *what*.

Split is by source image; neither source has video-frame duplication, so a plain
stratified split is safe here (unlike the Mendeley set -- see build_condition_dataset.py).
"""

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

MIN_BOX_PX = 12  # drop specks: mask noise below this area is not a defect
MIN_SIDE_PX = 3
VAL_FRACTION = 0.2
SEED = 1337


def boxes_from_mask(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Connected components of a binary mask -> integer xyxy boxes."""
    labelled, n = ndimage.label(mask > 127)
    boxes = []
    for sl_y, sl_x in ndimage.find_objects(labelled):
        x0, y0, x1, y1 = sl_x.start, sl_y.start, sl_x.stop, sl_y.stop
        if (x1 - x0) < MIN_SIDE_PX or (y1 - y0) < MIN_SIDE_PX:
            continue
        if (x1 - x0) * (y1 - y0) < MIN_BOX_PX:
            continue
        boxes.append((x0, y0, x1, y1))
    return boxes


def to_yolo(box, w: int, h: int) -> str:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
    bw, bh = (x1 - x0) / w, (y1 - y0) / h
    return f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def collect_rsdds(img_dir: Path, gt_dir: Path) -> list[dict]:
    records = []
    for img_path in sorted(img_dir.glob("*.bmp"), key=lambda p: int(p.stem)):
        gt_path = gt_dir / f"{img_path.stem}.png"
        if not gt_path.exists():
            continue
        img = Image.open(img_path).convert("RGB")
        mask = np.array(Image.open(gt_path).convert("L"))
        if mask.shape[:2] != (img.height, img.width):
            # dims disagree -> resample the mask onto the image grid
            mask = np.array(
                Image.open(gt_path).convert("L").resize((img.width, img.height), Image.NEAREST)
            )
        boxes = boxes_from_mask(mask)
        if not boxes:
            continue
        records.append(
            {
                "stem": f"rsdds_{img_path.stem}",
                "image": img,
                "labels": [to_yolo(b, img.width, img.height) for b in boxes],
                "source": "rsdds",
            }
        )
    return records


def collect_coco(root: Path) -> list[dict]:
    records = []
    for split_dir in sorted(root.iterdir()):
        ann_file = split_dir / "_annotations.coco.json" if split_dir.is_dir() else None
        if ann_file is None or not ann_file.exists():
            continue
        coco = json.loads(ann_file.read_text())
        by_image: dict[int, list] = {}
        for ann in coco["annotations"]:
            by_image.setdefault(ann["image_id"], []).append(ann)
        for meta in coco["images"]:
            anns = by_image.get(meta["id"], [])
            if not anns:
                continue
            img_path = split_dir / meta["file_name"]
            if not img_path.exists():
                continue
            img = Image.open(img_path).convert("RGB")
            w, h = img.width, img.height
            labels = []
            for ann in anns:
                x, y, bw, bh = ann["bbox"]  # COCO: xywh, top-left origin
                if bw < MIN_SIDE_PX or bh < MIN_SIDE_PX:
                    continue
                labels.append(to_yolo((x, y, x + bw, y + bh), w, h))
            if labels:
                records.append(
                    {
                        "stem": f"coco_{img_path.stem[:40]}",
                        "image": img,
                        "labels": labels,
                        "source": "cracks_coco",
                    }
                )
    return records


def write_split(records: list[dict], out_root: Path) -> dict:
    rng = np.random.default_rng(SEED)
    counts = {"train": 0, "val": 0}
    boxes = {"train": 0, "val": 0}
    per_source: dict[str, dict[str, int]] = {}

    # stratify by source so both splits see both imaging setups
    for source in sorted({r["source"] for r in records}):
        subset = [r for r in records if r["source"] == source]
        order = rng.permutation(len(subset))
        n_val = max(1, int(round(len(subset) * VAL_FRACTION)))
        val_idx = set(order[:n_val].tolist())
        for i, rec in enumerate(subset):
            split = "val" if i in val_idx else "train"
            img_dir = out_root / "images" / split
            lbl_dir = out_root / "labels" / split
            img_dir.mkdir(parents=True, exist_ok=True)
            lbl_dir.mkdir(parents=True, exist_ok=True)
            rec["image"].save(img_dir / f"{rec['stem']}.jpg", quality=95)
            (lbl_dir / f"{rec['stem']}.txt").write_text("\n".join(rec["labels"]) + "\n")
            counts[split] += 1
            boxes[split] += len(rec["labels"])
            per_source.setdefault(source, {"train": 0, "val": 0})[split] += 1
    return {"images": counts, "boxes": boxes, "per_source": per_source}


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--rsdds-img", required=True, type=Path)
    ap.add_argument("--rsdds-gt", required=True, type=Path)
    ap.add_argument("--coco-root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    records = collect_rsdds(args.rsdds_img, args.rsdds_gt) + collect_coco(args.coco_root)
    stats = write_split(records, args.out)

    (args.out / "data.yaml").write_text(
        "path: /kaggle/input/railsetu-m3-localization\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 1\n"
        "names: [defect]\n"
    )
    (args.out / "build_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
