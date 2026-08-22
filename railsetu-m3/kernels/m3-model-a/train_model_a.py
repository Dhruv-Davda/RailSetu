"""RailSetu M3 · Model A — rail surface condition classifier.

Four classes: flaking, squat, spalling, shelling.

There is deliberately NO `healthy` class. The only healthy-rail imagery available
(salmaneunus/railwayfaultmulticlassdataset, 405 images) is full-scene phone
photography of track with ballast and sleepers in frame, whereas every Mendeley
image is a 1280x720 close-up of the railhead from a vehicle-mounted EKEN camera.
A model given both would separate them on camera signature, not rail condition,
and would score ~100% on `healthy` while learning nothing. A healthy class needs
same-camera negatives; that is a data-collection task, not a modelling one.

Splits come from manifest.csv, which assigns whole *runs* (contiguous frame spans
= one physical defect) to a single split. Frames within a run are near-duplicates,
so any split finer than a run leaks.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from PIL import Image
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

INPUT_ROOT = Path("/kaggle/input")
OUT = Path("/kaggle/working")


def resolve_data_root(marker: str = "manifest.csv") -> Path:
    """Locate the attached dataset, failing loudly with what *is* mounted.

    A dataset that is still processing when the kernel starts silently does not
    mount, and the first file access then dies with a bare FileNotFoundError
    that says nothing about the real cause.

    Kaggle also does not mount at a fixed depth -- the same dataset has appeared
    at both /kaggle/input/<slug>/ and /kaggle/input/datasets/<owner>/<slug>/ --
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
CLASSES = ["flaking", "shelling", "spalling", "squat"]
IMG_SIZE = 224
BATCH = 64
EPOCHS = 14
LR = 3e-4
SEED = 1337

torch.manual_seed(SEED)
np.random.seed(SEED)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"device={device} | {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no gpu'}")


class RailDataset(Dataset):
    def __init__(self, df: pd.DataFrame, tf):
        self.paths = df["filepath"].tolist()
        self.labels = [CLASSES.index(x) for x in df["label"]]
        self.tf = tf

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        img = Image.open(DATA / self.paths[i]).convert("RGB")
        return self.tf(img), self.labels[i]


NORM = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])

train_tf = transforms.Compose([
    transforms.RandomResizedCrop(IMG_SIZE, scale=(0.55, 1.0), ratio=(0.75, 1.33)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    # rail imagery varies mostly in illumination and glare, not colour
    transforms.ColorJitter(brightness=0.35, contrast=0.35, saturation=0.15),
    transforms.ToTensor(),
    NORM,
])
eval_tf = transforms.Compose([
    transforms.Resize(int(IMG_SIZE * 1.15)),
    transforms.CenterCrop(IMG_SIZE),
    transforms.ToTensor(),
    NORM,
])

manifest = pd.read_csv(DATA / "manifest.csv")
splits = {s: manifest[manifest["split"] == s].reset_index(drop=True) for s in ("train", "val", "test")}
for name, df in splits.items():
    print(f"{name:6} {len(df):5} images | {df['label'].value_counts().to_dict()}")

loaders = {
    name: DataLoader(
        RailDataset(df, train_tf if name == "train" else eval_tf),
        batch_size=BATCH,
        shuffle=(name == "train"),
        num_workers=2,
        pin_memory=True,
        drop_last=(name == "train"),
    )
    for name, df in splits.items()
}

model = efficientnet_b0(weights=EfficientNet_B0_Weights.IMAGENET1K_V1)
model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(CLASSES))
model = model.to(device)

# inverse-frequency weighting: flaking outnumbers shelling ~21:1
counts = splits["train"]["label"].value_counts()
weights = torch.tensor(
    [len(splits["train"]) / (len(CLASSES) * counts[c]) for c in CLASSES],
    dtype=torch.float32,
    device=device,
)
print("class weights:", dict(zip(CLASSES, weights.tolist())))

criterion = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.05)
optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")


def evaluate(loader):
    model.eval()
    preds, trues = [], []
    with torch.no_grad():
        for x, y in loader:
            x = x.to(device, non_blocking=True)
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                out = model(x)
            preds.append(out.argmax(1).cpu().numpy())
            trues.append(y.numpy())
    return np.concatenate(trues), np.concatenate(preds)


history = []
best_f1 = -1.0
for epoch in range(1, EPOCHS + 1):
    model.train()
    total = 0.0
    for x, y in loaders["train"]:
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
            loss = criterion(model(x), y)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        total += loss.item() * x.size(0)
    scheduler.step()

    y_true, y_pred = evaluate(loaders["val"])
    macro_f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)
    train_loss = total / max(1, len(loaders["train"].dataset))
    history.append({"epoch": epoch, "train_loss": train_loss, "val_macro_f1": macro_f1})
    print(f"epoch {epoch:2}/{EPOCHS}  loss {train_loss:.4f}  val_macro_f1 {macro_f1:.4f}")

    if macro_f1 > best_f1:
        best_f1 = macro_f1
        torch.save(
            {"state_dict": model.state_dict(), "classes": CLASSES, "img_size": IMG_SIZE},
            OUT / "model_a_best.pt",
        )

# ---- final test-set evaluation on the best checkpoint ----
model.load_state_dict(torch.load(OUT / "model_a_best.pt")["state_dict"])
y_true, y_pred = evaluate(loaders["test"])

report = classification_report(
    y_true, y_pred, target_names=CLASSES, output_dict=True, zero_division=0
)
print("\n=== TEST (run-level split, no temporal leakage) ===")
print(classification_report(y_true, y_pred, target_names=CLASSES, zero_division=0))
print("confusion matrix (rows=true, cols=pred):")
print(confusion_matrix(y_true, y_pred))

metrics = {
    "model": "efficientnet_b0",
    "classes": CLASSES,
    "best_val_macro_f1": best_f1,
    "test_macro_f1": f1_score(y_true, y_pred, average="macro", zero_division=0),
    "test_accuracy": float((y_true == y_pred).mean()),
    "test_report": report,
    "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
    "history": history,
    "split_sizes": {k: len(v) for k, v in splits.items()},
}
(OUT / "metrics_model_a.json").write_text(json.dumps(metrics, indent=2))
print("\nsaved model_a_best.pt + metrics_model_a.json")
