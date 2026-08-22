# RailSetu M3 — Deployment Guide

**For:** whoever maintains the EC2 box behind `https://3.108.70.96.nip.io/`
**What changed:** a fifth module (`M3 · Defects`) was added to the dashboard.
It runs two PyTorch neural networks server-side.

> **Read this first.** M3 is the first part of RailSetu that needs a machine
> learning runtime. On the current `t3.micro` it **will not work** — the
> instance has 1 GB of RAM and PyTorch alone holds ~300 MB resident before a
> single model loads. The process gets OOM-killed on the first inference and
> nginx returns 502. **The instance must be resized.** Everything else in this
> guide is routine.

---

## 1 · What was implemented

A new tab, **Defects · M3**, sitting after Kavach. A user drops in a photograph
of railway track (or clicks one of 36 bundled test photos) and two networks
inspect it:

| | Model A | Model B |
|---|---|---|
| Architecture | EfficientNet-B0 | YOLO11-s |
| Answers | *What* is wrong with the rail surface | *Where* the damage is |
| Output | 4 classes: flaking, squat, spalling, shelling | Bounding boxes, single class `defect` |
| Input | 224×224 RGB, ImageNet normalised | 640×640 letterboxed |
| Parameters | 4.0M | 9.4M |
| Weights file | `model_a_best.pt` (16 MB) | `model_b_v2_best.pt` (18 MB) |

The page also returns a Grad-CAM attention map (showing which pixels drove the
classification), per-stage timings, the full probability vector across all four
classes, and an estimated severity grade.

### New API endpoints

| Route | Method | Purpose |
|---|---|---|
| `/api/m3/status` | GET | Readiness, device, architectures, published metrics |
| `/api/m3/warm` | POST | Force the model load now (used at boot) |
| `/api/m3/samples` | GET | The bundled test photos + ground-truth labels |
| `/api/m3/samples/{id}` | GET | Serve one sample image |
| `/api/m3/analyse` | POST | multipart — run both models over one image |

### Files added

```
backend/app/m3_defect/service.py      inference service
frontend/src/views/M3Defect.jsx       the page
railsetu-m3/predict.py                model loading + Grad-CAM (imported by the service)
railsetu-m3/testpack/                 36 held-out test photographs
railsetu-m3/artifacts/metrics_*.json  published metrics shown in the UI
```

Modified: `backend/app/main.py`, `backend/app/config.py`,
`backend/requirements.txt`, `frontend/src/{App,api,icons}.jsx`,
`frontend/src/styles.css`, `.gitignore`.

### What is deliberately NOT in git

The `.pt` weight files. They are 34 MB of binaries that version badly and can
never be cleanly removed from history once committed. They ship through the S3
deploy bucket. See §6.

### Torch is imported lazily

Nothing in M3 is imported at module load. If PyTorch is missing or the weights
are absent, **the rest of RailSetu is completely unaffected** — M1, M2 and M6
serve normally and the M3 page displays "Inference runtime unavailable" with
the reason. A broken M3 cannot take the API down.

---

## 2 · No URL or link changes are needed

Worth stating explicitly, because it is the usual worry:

* The frontend calls the API at the **relative** path `/api` (`frontend/src/api.js`).
  It does not contain a hostname. Whatever origin serves the page serves the API.
* The existing nginx `/api → 127.0.0.1:8000` proxy rule already covers every new
  endpoint, because they all live under `/api/m3/`.
* The **Elastic IP means resizing does not change the address.** Stop, change
  instance type, start — `3.108.70.96` follows the instance and the certificate
  stays valid.

The only nginx change required is an upload size limit (§8).

---

## 3 · Pre-flight — find your own values

Fill these in before starting; the rest of the guide refers to them.

```bash
# where the project lives
PROJECT=/path/to/RailSetu

# the service that runs uvicorn
systemctl list-units --type=service | grep -iE "railsetu|uvicorn|gunicorn"

# which web server is in front
systemctl status nginx caddy 2>/dev/null | head -20

# free disk — PyTorch needs ~3 GB
df -h /
```

---

## 4 · Resize the instance

**Required.** `t3.micro` (1 GB) cannot run this.

| Instance | RAM | ap-south-1 ≈ | Verdict |
|---|---|---|---|
| `t3.micro` | 1 GB | free tier | **OOM on first inference** |
| `t3.small` | 2 GB | ~$15/mo | Works |
| **`t3.medium`** | **4 GB** | **~$30/mo** | **Recommended** |

Where the memory goes: PyTorch runtime ~300 MB, ultralytics + OpenCV + NumPy
~200 MB, both models ~60 MB, YOLO activations at 640px ~200–400 MB peak, plus
the existing FastAPI app ~150 MB. Peak is 900 MB–1.2 GB.

```bash
aws ec2 stop-instances  --instance-ids i-05e1b212b4907bb17
aws ec2 wait instance-stopped --instance-ids i-05e1b212b4907bb17
aws ec2 modify-instance-attribute \
  --instance-id i-05e1b212b4907bb17 --instance-type t3.medium
aws ec2 start-instances --instance-ids i-05e1b212b4907bb17
```

Or via the console: **Instance state → Stop → Actions → Instance settings →
Change instance type → Start.**

The Elastic IP reattaches automatically. Nothing else changes.

---

## 5 · Add swap

Insurance against the inference spike. Costs nothing.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h        # confirm swap appears
```

---

## 6 · Pull code and install dependencies

```bash
cd $PROJECT
git pull origin 3js          # or whichever branch was merged

source .venv/bin/activate    # the venv the app already uses

# CPU wheels specifically. The default index assumes an NVIDIA GPU and pulls
# ~5x more data for zero benefit on a box without one.
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
pip install ultralytics python-multipart

python -c "import torch, ultralytics; print(torch.__version__, ultralytics.__version__)"
```

Expect ~3 GB of disk use. The 16 GB gp3 volume is fine.

---

## 7 · Install the model weights

Two files, **not** in git.

```bash
# upload once, from a machine that has them
aws s3 cp railsetu-m3/deploy/model_a_best.pt     s3://railsetu-deploy-043848616679/
aws s3 cp railsetu-m3/deploy/model_b_v2_best.pt  s3://railsetu-deploy-043848616679/

# on the server
cd $PROJECT
mkdir -p railsetu-m3/artifacts
aws s3 cp s3://railsetu-deploy-043848616679/model_a_best.pt     railsetu-m3/artifacts/
aws s3 cp s3://railsetu-deploy-043848616679/model_b_v2_best.pt  railsetu-m3/artifacts/

# verify — a truncated download loads with a cryptic error much later
shasum -a 256 -c railsetu-m3/deploy/SHA256SUMS
```

Expected:

```
667237c3c2da05a4984032200362f2ad998d84e680de899144e2ce1b2ad1f5ef  model_a_best.pt
e1c321b88a18f8d0ca1bad91f27809296d1faefb3c8f822a85ba3648f635c440  model_b_v2_best.pt
```

The loader prefers `model_b_v2_best.pt` and falls back to `model_b_best.pt`, so
dropping in a newer localizer later needs no code change. If the weights must
live elsewhere, set `RAILSETU_M3_ARTIFACTS_DIR=/abs/path`.

---

## 8 · Configuration

### One uvicorn worker — important

**Every worker process loads its own complete copy of PyTorch and both models.**
Two workers doubles the memory and puts a 4 GB box back into OOM territory.

Check the service file (`sudo systemctl cat <service>`) and ensure there is
**no** `--workers 2+` / `-w 2+` flag. Serialised inference is correct anyway:
two simultaneous inferences on 2 vCPUs would only fight each other.

### nginx upload limit

The default `client_max_body_size` is **1 MB**. The bundled test photos are
~200 KB and pass, but a photo taken on a phone is 3–8 MB and fails with a bare
`413` and no explanation.

```nginx
server {
    ...
    client_max_body_size 20M;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_read_timeout 120s;      # first request loads ~35 MB of weights
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

*(Caddy has no such default limit — nothing to change there.)*

### Optional environment variables

| Variable | Default | Effect |
|---|---|---|
| `RAILSETU_M3_DEVICE` | `cpu` | `cpu` / `cuda` / `mps` / `auto` |
| `RAILSETU_M3_CONF` | `0.40` | Model B box confidence floor |
| `RAILSETU_M3_ARTIFACTS_DIR` | *(repo path)* | Where the `.pt` files live |

---

## 9 · Build the frontend

The page is new JS and CSS — the old `dist/` does not contain it.

```bash
cd $PROJECT/frontend
npm ci          # or: npm install
npm run build
```

Serve `frontend/dist/` exactly as before; the output path has not changed.

---

## 10 · Restart and warm

```bash
sudo systemctl restart <your-railsetu-service>

# Load the weights BEFORE any real visitor arrives. Without this the first
# request pays ~3 s of model loading and looks broken.
curl -sX POST http://127.0.0.1:8000/api/m3/warm | head -c 300
```

Consider adding the warm call to the service unit so it survives every restart:

```ini
ExecStartPost=/bin/sh -c 'sleep 5; curl -sX POST http://127.0.0.1:8000/api/m3/warm >/dev/null || true'
```

---

## 11 · Verify

```bash
# 1. models loaded?
curl -s https://3.108.70.96.nip.io/api/m3/status | python3 -m json.tool | head -20
#    expect: "loaded": true, "error": null, "device": "cpu"

# 2. real inference end to end
curl -s -X POST https://3.108.70.96.nip.io/api/m3/analyse \
     -F "sample=rail_frames/squat_4152_3967.jpg" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); \
    print(d['condition']['label'], round(d['condition']['confidence'],2), \
          '|', d['defect_count'], 'boxes |', d['timings_ms']['total'], 'ms')"
#    expect: squat 0.79 | ... | ~1000-1500 ms

# 3. nothing else regressed
for p in health station m6/coverage m2/network; do
  printf "%-16s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' https://3.108.70.96.nip.io/api/$p)"
done

# 4. memory headroom under load
free -h
```

Then open the site, click **Defects · M3**, and click a thumbnail. You should
see a class name, a confidence, a red Grad-CAM heat overlay, and per-stage
timings counting up.

---

## 12 · Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 502 on first image; `Killed` in `journalctl` | OOM | Resize instance (§4); confirm swap (§5); one worker (§8) |
| Page shows "Inference runtime unavailable" | torch missing or weights absent | Read the reason shown on the page; §6 / §7 |
| `413 Request Entity Too Large` | nginx 1 MB default | `client_max_body_size 20M` (§8) |
| First request times out, later ones fine | Cold model load | Warm it (§10); raise `proxy_read_timeout` |
| Weights fail to load with a checksum-ish error | Truncated S3 download | Re-download, verify SHA256 (§7) |
| Memory climbs with traffic | Multiple workers | One worker only (§8) |
| Page loads but tab missing | Stale frontend build | `npm run build` (§9) |

Logs: `sudo journalctl -u <service> -n 100 --no-pager`

---

## 13 · Rollback

M3 is additive and isolated. To disable it without reverting code, remove the
weights:

```bash
mv railsetu-m3/artifacts/model_a_best.pt /tmp/
sudo systemctl restart <service>
```

The M3 page then reports itself unavailable; **M1, M2 and M6 are unaffected.**
To go back further, `git revert` the M3 commit and rebuild the frontend.

---

## 14 · Performance and known limitations

**Expected latency:** ~1–1.5 s per image on `t3.medium` (CPU). Two networks plus
a gradient backward pass for the heatmap.

**Note on `t3` burst credits:** sustained inference will exhaust CPU credits and
throttle to baseline. Fine for a demo; watch it under real traffic.

### Measured accuracy

**Model A** — 761 held-out images, run-level split (no temporal leakage):
accuracy **0.804**, macro-F1 **0.605**.
Per-class F1: flaking 0.87, squat 0.83, shelling 0.45, spalling 0.26.

The gap between accuracy and macro-F1 is class imbalance — roughly 21 flaking
images for every shelling one. Strong on the two common defects, weak on the
two rare ones. This is stated in the UI rather than hidden.

**Model B v2** — 56 held-out images: mAP@50 **0.819**, mAP@50-95 **0.519**,
precision **0.887**, recall **0.733**.

### The ballast issue, and what was done about it

Model B v1 had only ever been trained on tight railhead close-ups and had no
concept of "this image contains nothing". On wide track photos it boxed gravel:
**2.29 false boxes per image, firing on 27 of 28 photographs.**

v2 was retrained with 216 ballast crops mined from the shoulders of Mendeley
frames as background negatives. Crucially, whole frames could **not** be used —
every Mendeley frame contains a real defect, so labelling one empty would have
taught the model that rail damage is nothing. Only the gravel shoulders were
taken.

Result: **0.18 false boxes per image**, and detection on railhead close-ups was
unaffected (12/12 images still detected). The confidence floor was then raised
from 0.25 to 0.40, measured to keep all 12 close-up detections while cutting
false boxes further.

**One photograph in the test set still boxes grass.** That is real and was left
visible rather than tuned away — raising the threshold far enough to remove it
also loses genuine detections, and for an inspection tool a missed defect is
worse than a box on gravel.

### Severity is a rule, not a prediction

Severity grade = defect-type weight × confidence × area coverage. The source
datasets carry **no severity annotations**, so nothing could have learned it.
It is labelled `Estimated` in the UI under RailSetu's existing provenance
policy. Do not present it as a model output.

---

## 15 · Attribution — required

These licences apply to the training data and must accompany any redistribution:

* **Mendeley Railway Track Surface Faults Dataset** — CC BY 4.0, doi:10.17632/8hxtgyyxrw.2
* **RSDDs rail surface defect dataset** — Niu et al., IEEE TII 2021 / TIM 2021
* **Railway cracks COCO** — Roboflow, via Kaggle `harideepak/railway-cracks-coco`
