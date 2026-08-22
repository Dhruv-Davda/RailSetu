# RailSetu M3 — Running It Locally

How to get the **Defects · M3** page working on your own machine.

You need two things: the repository, and two model weight files that are sent
separately (they are 34 MB of binaries). The rest of RailSetu — Crowd-Flow,
Delays, Kavach — works without any of this; only the M3 tab needs a machine
learning runtime.

---

## What you need first

| | |
|---|---|
| **Python 3.10 or newer** | 3.12 recommended. **3.9 will not work** — see Troubleshooting. |
| **Node.js 18+** | for the frontend |
| **~4 GB free disk** | PyTorch is about 3 GB installed |
| **~2 GB free RAM** | while running |

No GPU required. Everything runs on CPU.

---

## 1 · Get the code

```bash
git clone https://github.com/Dhruv-Davda/RailSetu.git
cd RailSetu
git checkout 3js
```

---

## 2 · Put the weights in place

The two files you were sent go in `railsetu-m3/artifacts/`. That folder already
exists after cloning — it contains three JSON files. Drop the weights alongside
them:

```
RailSetu/
└── railsetu-m3/
    └── artifacts/
        ├── model_a_best.pt          ← 16 MB, sent to you
        ├── model_b_v2_best.pt       ← 18 MB, sent to you
        ├── metrics_model_a.json     (already there)
        ├── metrics_model_b.json     (already there)
        └── metrics_model_b_v2.json  (already there)
```

**Filenames must be exact.** Browsers, AirDrop and Slack all like appending
things — `model_b_v2_best (1).pt` will not be found. Check with:

```bash
ls -la railsetu-m3/artifacts/*.pt
```

---

## 3 · Set up the backend

**Check your Python version before creating the venv.** This is the step that
goes wrong most often.

```bash
cd backend
python3 --version        # must be 3.10 or higher
```

If it prints 3.9.x, jump to Troubleshooting before continuing.

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

### Then the ML runtime

**macOS:**

```bash
./.venv/bin/pip install torch torchvision ultralytics
```

**Windows / Linux** — use the CPU wheels. The default index assumes an NVIDIA
GPU and downloads roughly 5× more for no benefit on a machine without one:

```bash
./.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
./.venv/bin/pip install ultralytics
```

This takes a few minutes.

---

## 4 · Set up the frontend

```bash
cd ../frontend
npm install
```

---

## 5 · Run it

Two terminals, both left running.

**Terminal 1 — backend:**

```bash
cd RailSetu/backend
./.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — frontend:**

```bash
cd RailSetu/frontend
npm run dev
```

Open **http://localhost:5173** and click **Defects · M3**, the last tab.

> On Windows the venv layout differs: use `.venv\Scripts\python` instead of
> `./.venv/bin/python`.

---

## 6 · Check it works

You should see a loading bar for about 3 seconds — that is 34 MB of weights
being read into memory, and it only happens once — then a strip of 36
photographs along the bottom.

Click any thumbnail. You should get:

* a defect name and confidence in the right-hand panel
* a red heat overlay on the image, showing where the network actually looked
* five pipeline stages lighting up with real millisecond timings
* green boxes around the damage on the close-up photos

Expect roughly 0.5–1.5 seconds per image on CPU.

If you would rather check from the command line:

```bash
curl -s http://127.0.0.1:8000/api/m3/status
```

`"loaded": true` means both models are in memory. If not, `error` says why and
`artifacts_dir` shows the exact folder it searched.

---

## What you are looking at

Two neural networks run on every photograph:

| | Model A | Model B |
|---|---|---|
| Architecture | EfficientNet-B0 | YOLO11-s |
| Answers | *What* is wrong | *Where* it is |
| Output | flaking / squat / spalling / shelling | boxes around the damage |
| Parameters | 4.0M | 9.4M |

The 36 photographs are **held out** — neither model saw any of them during
training. For the wide track photos the filename carries the true label, so the
page can tell you whether the prediction was right. Click through a few and
mark it yourself.

**Accuracy: 80.4%** overall on 761 held-out images. It is strong on flaking and
squat (F1 0.87 and 0.83) and weak on shelling and spalling (0.45 and 0.26) —
there were 21 flaking images in the training data for every shelling one. It
will get things wrong, and the page shows you when.

Severity grades are a rule, not a prediction — defect type × confidence × area.
The training data had no severity labels, so nothing could have learned it. The
UI marks it `Estimated` for that reason.

---

## Troubleshooting

### `Could not find a version that satisfies the requirement fastapi==0.136.3`

**You are on Python 3.9.** That version of FastAPI exists but is not published
for 3.9, so pip reports it as missing and the error looks like a bad pin.

On macOS `python3` frequently resolves to the system 3.9, or to Anaconda's
Python. Point at a newer interpreter explicitly:

```bash
cd backend
rm -rf .venv
python3.12 -m venv .venv          # or /opt/homebrew/bin/python3.12
./.venv/bin/python -V             # confirm before continuing
```

Then redo step 3.

### The page says "Inference runtime unavailable"

The page prints the real reason underneath. Usually one of:

* **weights not found** — check `ls railsetu-m3/artifacts/*.pt`, and check the
  names have no ` (1)` suffix
* **`No module named 'torch'`** — the ML install in step 3 did not run, or ran
  in a different venv than the one serving the app

### `No module named uvicorn`

You are running a different Python than the one you installed into. Use the
explicit `./.venv/bin/python` path rather than a bare `python`.

### Do not use `./run.sh`

It builds the venv from whatever `python3` happens to be and installs no
PyTorch. M1, M2 and M6 will work; M3 will not.

### Port already in use

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN     # find it
pkill -f "uvicorn app.main:app"      # stop it
```

### First image is slow, the rest are fast

Normal. The first request loads the weights. Everything after is warm.

---

## Attribution

The training data is licensed and requires credit if you share this on:

* **Mendeley Railway Track Surface Faults Dataset** — CC BY 4.0, doi:10.17632/8hxtgyyxrw.2
* **RSDDs rail surface defect dataset** — Niu et al., IEEE TII 2021 / TIM 2021
* **Railway cracks COCO** — Roboflow, via Kaggle `harideepak/railway-cracks-coco`
