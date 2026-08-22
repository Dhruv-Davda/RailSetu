# RailSetu M3 — model weights

Two files. They are NOT in git: 34 MB of binaries that change rarely and
version badly. They ship through the S3 deploy bucket instead.

| file | size | what it is |
|---|---|---|
| `model_a_best.pt` | 16 MB | EfficientNet-B0, 4-class rail surface condition |
| `model_b_v2_best.pt` | 18 MB | YOLO11-s, single-class defect localizer |

## Install on the server

Both files go in `railsetu-m3/artifacts/` inside the project directory:

    aws s3 cp s3://railsetu-deploy-043848616679/model_a_best.pt      railsetu-m3/artifacts/
    aws s3 cp s3://railsetu-deploy-043848616679/model_b_v2_best.pt   railsetu-m3/artifacts/
    shasum -a 256 -c railsetu-m3/deploy/SHA256SUMS

The loader prefers `model_b_v2_best.pt` and falls back to `model_b_best.pt`,
so dropping in a newer localizer needs no code change.

Override the location with `RAILSETU_M3_ARTIFACTS_DIR` if they live elsewhere.

## Runtime requirements

    pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
    pip install ultralytics python-multipart

CPU wheels specifically — the default build assumes an NVIDIA GPU and is ~5x
larger for no benefit on a box without one.

**RAM: 2 GB minimum, 4 GB comfortable.** t3.micro (1 GB) will be OOM-killed on
the first inference. Torch alone holds ~300 MB resident before any model loads.

**Run ONE uvicorn worker.** Every worker loads its own copy of both models.

**nginx needs `client_max_body_size 20M;`** or phone photos fail with 413
against the 1 MB default.

**Warm the models after restart** so the first visitor does not wait ~3s:

    curl -sX POST http://127.0.0.1:8000/api/m3/warm > /dev/null

## Measured performance

Model A — 761 held-out images, run-level split, no temporal leakage:
accuracy 0.804, macro-F1 0.605. Per class F1: flaking 0.87, squat 0.83,
shelling 0.45, spalling 0.26.

Model B v2 — 56 held-out images: mAP@50 0.819, mAP@50-95 0.519,
precision 0.887, recall 0.733.

v2 was retrained with 216 ballast crops as background negatives. False boxes
on wide track frames fell from 2.29 to 0.18 per image; detection on railhead
close-ups was unaffected (12/12 images still detected).

## Attribution — required

Mendeley Railway Track Surface Faults Dataset, CC BY 4.0
  doi:10.17632/8hxtgyyxrw.2
RSDDs rail surface defect dataset — Niu et al., IEEE TII 2021 / TIM 2021
Railway cracks COCO — Roboflow, via Kaggle harideepak/railway-cracks-coco
