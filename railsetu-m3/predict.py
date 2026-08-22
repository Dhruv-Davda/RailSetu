"""RailSetu M3 — run both models over images and emit the M3 prediction payload.

Model A (EfficientNet-B0) classifies rail surface condition: what is wrong.
Model B (YOLO11-s)        localizes surface defects:        where it is.

Usage:
    python predict.py --images path/to/img.jpg
    python predict.py --images path/to/folder --out artifacts/predictions --save-viz

Runs on CPU or Apple MPS; no GPU required. Inference only.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw
from torchvision import transforms
from torchvision.models import efficientnet_b0

HERE = Path(__file__).resolve().parent
DEFAULT_A = HERE / "artifacts" / "model_a_best.pt"
DEFAULT_B = HERE / "artifacts" / "model_b_best.pt"

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
NORM = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])

# Model A was trained without a `healthy` class (no same-camera negatives exist),
# so it always names a defect type. Confidence below this means "the model is not
# committing", which is the closest honest signal we have to "nothing found".
LOW_CONFIDENCE = 0.50

# Severity is a RULE, not a learned output: the dataset carries no severity
# annotations, so under RailSetu's provenance policy this is `Estimated`.
SEVERITY_WEIGHT = {"flaking": 0.35, "shelling": 0.55, "spalling": 0.65, "squat": 0.80}


def pick_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class ConditionModel:
    """Model A + Grad-CAM over its final conv block."""

    def __init__(self, weights: Path, device: torch.device):
        ckpt = torch.load(weights, map_location="cpu", weights_only=False)
        self.classes = ckpt["classes"]
        self.img_size = ckpt.get("img_size", 224)
        model = efficientnet_b0(weights=None)
        model.classifier[1] = torch.nn.Linear(
            model.classifier[1].in_features, len(self.classes)
        )
        model.load_state_dict(ckpt["state_dict"])
        self.model = model.to(device).eval()
        self.device = device
        self.tf = transforms.Compose([
            transforms.Resize(int(self.img_size * 1.15)),
            transforms.CenterCrop(self.img_size),
            transforms.ToTensor(),
            NORM,
        ])

    def predict(self, img: Image.Image, want_cam: bool = False):
        x = self.tf(img).unsqueeze(0).to(self.device)

        features = {}

        def hook(_m, _inp, out):
            features["maps"] = out

        handle = self.model.features.register_forward_hook(hook)
        if want_cam:
            logits = self.model(x)
            maps = features["maps"]
            maps.retain_grad()
            idx = int(logits.argmax(1))
            self.model.zero_grad(set_to_none=True)
            logits[0, idx].backward()
            # Grad-CAM: channel importance = spatial mean of dScore/dActivation
            weights = maps.grad.mean(dim=(2, 3), keepdim=True)
            cam = F.relu((weights * maps).sum(1, keepdim=True))
            cam = F.interpolate(cam, size=(img.height, img.width), mode="bilinear", align_corners=False)
            cam = cam[0, 0].detach().cpu().numpy()
            if cam.max() > cam.min():
                cam = (cam - cam.min()) / (cam.max() - cam.min())
            probs = torch.softmax(logits, 1)[0].detach().cpu().numpy()
        else:
            with torch.no_grad():
                logits = self.model(x)
            probs = torch.softmax(logits, 1)[0].cpu().numpy()
            cam = None
        handle.remove()

        order = int(np.argmax(probs))
        return {
            "label": self.classes[order],
            "confidence": float(probs[order]),
            "probabilities": {c: float(p) for c, p in zip(self.classes, probs)},
            "low_confidence": bool(probs[order] < LOW_CONFIDENCE),
            "provenance": "Modelled",
        }, cam


def severity(condition: dict, boxes: list, img: Image.Image) -> dict:
    """Estimated severity: defect type weight x confidence x area coverage."""
    weight = SEVERITY_WEIGHT.get(condition["label"], 0.4)
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes)
    coverage = min(1.0, area / float(img.width * img.height)) if boxes else 0.0
    score = weight * condition["confidence"] * (0.5 + 0.5 * min(1.0, coverage * 4))
    grade = "CRITICAL" if score >= 0.6 else "WATCH" if score >= 0.3 else "MONITOR"
    return {
        "score": round(float(score), 3),
        "grade": grade,
        "coverage": round(float(coverage), 4),
        "provenance": "Estimated",
    }


def overlay(img: Image.Image, boxes, scores, cam, out_path: Path):
    canvas = img.convert("RGB")
    if cam is not None:
        heat = np.zeros((img.height, img.width, 3), dtype=np.float32)
        heat[..., 0] = cam  # red channel carries attention
        base = np.asarray(canvas, dtype=np.float32) / 255.0
        blended = np.clip(base * 0.72 + heat * 0.28, 0, 1)
        canvas = Image.fromarray((blended * 255).astype(np.uint8))
    draw = ImageDraw.Draw(canvas)
    for (x0, y0, x1, y1), s in zip(boxes, scores):
        draw.rectangle([x0, y0, x1, y1], outline=(0, 255, 90), width=3)
        draw.text((x0 + 4, max(0, y0 - 12)), f"defect {s:.2f}", fill=(0, 255, 90))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, type=Path, help="image file or directory")
    ap.add_argument("--model-a", type=Path, default=DEFAULT_A)
    ap.add_argument("--model-b", type=Path, default=DEFAULT_B)
    ap.add_argument("--out", type=Path, default=HERE / "artifacts" / "predictions")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--conf", type=float, default=0.25, help="Model B box confidence floor")
    ap.add_argument("--save-viz", action="store_true", help="write annotated images")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    device = pick_device(args.device)
    print(f"device: {device}")

    paths = (
        [args.images]
        if args.images.is_file()
        else sorted(p for p in args.images.rglob("*") if p.suffix.lower() in IMG_EXTS)
    )
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        raise SystemExit(f"no images found under {args.images}")

    cond = ConditionModel(args.model_a, device)
    print(f"Model A: {cond.classes}")

    detector = None
    if args.model_b.exists():
        from ultralytics import YOLO

        detector = YOLO(str(args.model_b))
        print("Model B: loaded")
    else:
        print(f"Model B: NOT FOUND at {args.model_b} — running condition only")

    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, path in enumerate(paths, 1):
        img = Image.open(path).convert("RGB")
        condition, cam = cond.predict(img, want_cam=args.save_viz)

        boxes, scores = [], []
        if detector is not None:
            det = detector.predict(
                source=str(path), conf=args.conf, device=str(device), verbose=False
            )[0]
            for b in det.boxes:
                boxes.append([round(float(v), 1) for v in b.xyxy[0].tolist()])
                scores.append(float(b.conf[0]))

        record = {
            "frame_id": path.stem,
            "source": str(path),
            "condition": condition,
            "defects": [
                {"bbox_xyxy": b, "confidence": round(s, 3), "provenance": "Modelled"}
                for b, s in zip(boxes, scores)
            ],
            "defect_count": len(boxes),
            "severity": severity(condition, boxes, img),
        }
        results.append(record)

        if args.save_viz:
            overlay(img, boxes, scores, cam, args.out / f"{path.stem}_viz.jpg")

        flag = " [LOW CONF]" if condition["low_confidence"] else ""
        print(
            f"[{i}/{len(paths)}] {path.name:44} -> {condition['label']:9} "
            f"{condition['confidence']:.2f}{flag} | {len(boxes)} box(es) | "
            f"{record['severity']['grade']}"
        )

    (args.out / "predictions.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {len(results)} predictions -> {args.out / 'predictions.json'}")
    if args.save_viz:
        print(f"annotated images -> {args.out}")


if __name__ == "__main__":
    main()
