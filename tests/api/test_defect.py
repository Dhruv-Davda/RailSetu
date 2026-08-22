"""M3 defect inspection — the two networks, over HTTP against a running API."""
import os
import pathlib

from harness import bootstrap

bootstrap("defect")
import io, json, sys, time, statistics, concurrent.futures as cf
import urllib.request, urllib.error, ssl, uuid

BASE = os.environ.get("RAILSETU_BASE", "http://127.0.0.1:8000")
CTX = ssl.create_default_context()

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  — ' + str(detail)[:120]) if detail else ''}")


def get(path, timeout=120):
    r = urllib.request.urlopen(BASE + path, timeout=timeout, context=CTX)
    return r.status, json.loads(r.read())


def post_form(path, fields, files=None, timeout=300):
    """multipart/form-data, hand-rolled so there are no extra dependencies."""
    boundary = "----railsetu" + uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in (fields or {}).items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        body.write(f"{v}\r\n".encode())
    for k, (fname, data, ctype) in (files or {}).items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'.encode())
        body.write(f"Content-Type: {ctype}\r\n\r\n".encode())
        body.write(data)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        BASE + path, data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf8", "replace")}


def get_bytes(path, timeout=120):
    r = urllib.request.urlopen(BASE + path, timeout=timeout, context=CTX)
    return r.status, r.read(), r.headers.get("Content-Type")


CLASSES = {"flaking", "shelling", "spalling", "squat"}
GRADES = {"MONITOR", "PLAN", "URGENT", "ROUTINE", "IMMEDIATE"}

# ---------------------------------------------------------------- 1. readiness
print("\n=== 1. READINESS ===")
def _corridor():
    req = urllib.request.Request(BASE + "/api/m2/simulate", method="POST",
                                 data=json.dumps({"scenario": "passenger_ahead",
                                                  "optimize": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=120, context=CTX).read())
    return (r["baseline"]["total_delay_min"], r["optimized"]["total_delay_min"])


# Read the corridor BEFORE torch is imported, so the check at the end measures the
# thing it claims to: that loading two networks into this process leaves the rest
# of the platform's answers untouched.
CORRIDOR_BEFORE = _corridor()

code, st = get("/api/m3/status")
check("status returns 200", code == 200)
check("both weight files present", st["weights_present"] == {"model_a": True, "model_b": True},
      st["weights_present"])
# The point is that the service resolves a real artifacts directory holding both
# checkpoints — not that it sits at any particular absolute path, which differs
# between a developer's checkout and the deployed box.
_art = pathlib.Path(st["artifacts_dir"])
check("artifacts dir resolves to a real directory", _art.is_dir(), st["artifacts_dir"])
check("...and it is the directory the weights were loaded from",
      any(_art.glob("model_a*.pt")) and any(_art.glob("model_b*.pt")),
      sorted(x.name for x in _art.glob("*.pt")))
check("12 samples bundled", st["n_samples"] == 12, st["n_samples"])
check("published metrics are exposed", "a" in st["metrics"] and "b" in st["metrics"])
check("model A metrics look sane",
      0 < st["metrics"]["a"]["macro_f1"] <= 1 and 0 < st["metrics"]["a"]["accuracy"] <= 1,
      st["metrics"]["a"])
code, warm = get("/api/m3/warm") if False else post_form("/api/m3/warm", {})
check("warm returns loaded", warm.get("loaded") is True, warm)
check("warm reports the device", warm.get("device") == "cpu", warm.get("device"))
check("warm is idempotent", post_form("/api/m3/warm", {})[1].get("loaded") is True)

# ---------------------------------------------------------------- 2. samples
print("\n=== 2. SAMPLES ===")
code, s = get("/api/m3/samples")
samples = s["samples"]
check("samples list returns 200", code == 200)
check("12 samples listed", len(samples) == 12, len(samples))
check("every sample has an id", all(x.get("id") for x in samples))
check("ids are unique", len({x["id"] for x in samples}) == len(samples))
code, blob, ctype = get_bytes("/api/m3/samples/" + samples[0]["id"])
check("a sample image can be fetched", code == 200 and len(blob) > 5000, f"{len(blob)} bytes")
check("it is served as a jpeg", "image" in (ctype or ""), ctype)
check("JPEG magic bytes", blob[:2] == b"\xff\xd8", blob[:4].hex())
try:
    urllib.request.urlopen(BASE + "/api/m3/samples/does-not-exist.jpg", timeout=30, context=CTX)
    check("unknown sample id -> 404", False, "no error raised")
except urllib.error.HTTPError as e:
    check("unknown sample id -> 404", e.code == 404, e.code)
# urllib normalises "../" before sending, so a raw literal path is used here —
# otherwise the request never reaches the route and the test proves nothing.
# What matters is whether anything ESCAPES, not the status code. nginx answers
# some of these with the SPA index.html via try_files, which is a 200 but leaks
# nothing — so the assertion is on the body, not the code.
import subprocess
def raw_get(path):
    out = subprocess.run(["curl", "-s", "--path-as-is", BASE + path],
                         capture_output=True)
    return out.stdout
LEAKS = [b"root:x:0:0", b"AWS_SECRET", b"aws_secret_access_key",
         b"RAILSETU_GEMINI_API_KEY", b"BEGIN RSA PRIVATE KEY", b"\x80\x02"]
for probe in ["/api/m3/samples/../../../../etc/passwd",
              "/api/m3/samples/..%2F..%2F..%2Fetc%2Fpasswd",
              "/api/m3/samples/..%2F..%2Fbackend%2F.env",
              "/api/m3/samples/..%2F..%2Fartifacts%2Fmodel_a_best.pt",
              "/api/m3/samples/railhead_crops%2F..%2F..%2F..%2Fbackend%2F.env"]:
    body = raw_get(probe)
    leaked = [m for m in LEAKS if m in body]
    is_spa = b"<title>RailSetu" in body
    check(f"nothing escapes via {probe.split('/samples/')[1][:38]}",
          not leaked, f"LEAKED {leaked}" if leaked else
          ("spa fallback" if is_spa else f"{len(body)}b"))

# ------------------------------------------------------- 3. every sample runs
print("\n=== 3. EVERY BUNDLED SAMPLE ANALYSES ===")
results, times = {}, []
for x in samples:
    t0 = time.time()
    code, d = post_form("/api/m3/analyse", {"sample": x["id"]})
    dt = (time.time() - t0) * 1000
    times.append(dt)
    results[x["id"]] = (code, d)
ok = [i for i, (c, _) in results.items() if c == 200]
check("all 12 samples return 200", len(ok) == 12, f"{len(ok)}/12")
bad = [(i, d) for i, (c, d) in results.items() if c != 200]
if bad:
    print("     failures:", bad[:2])
labels = [d["condition"]["label"] for _, d in results.values() if _ == 200] if False else \
         [d["condition"]["label"] for (c, d) in results.values() if c == 200]
check("every label is one of the four classes", set(labels) <= CLASSES, set(labels))
check("more than one class is predicted across the set", len(set(labels)) > 1, sorted(set(labels)))
# Two populations with opposite expectations: close-ups should be boxed, wide
# track frames should NOT be — v2 was retrained with gravel background negatives
# precisely so it stops boxing ballast on a wide frame.
crops = [d for x in samples if x["id"].startswith("railhead_crops")
         for c, d in [results[x["id"]]] if c == 200]
frames = [d for x in samples if x["id"].startswith("rail_frames")
          for c, d in [results[x["id"]]] if c == 200]
check("every railhead close-up is boxed",
      all(d["defect_count"] > 0 for d in crops), f"{sum(1 for d in crops if d['defect_count'])}/{len(crops)}")
check("no wide track frame gets a false box",
      all(d["defect_count"] == 0 for d in frames),
      f"{sum(1 for d in frames if d['defect_count'])}/{len(frames)} falsely boxed")

# The wide frames carry ground truth in their filename (e.g. flaking_1849_6978).
truth = [(x["id"].split("/")[-1].split("_")[0], results[x["id"]][1]["condition"]["label"])
         for x in samples if x["id"].startswith("rail_frames") and results[x["id"]][0] == 200]
hits = sum(1 for t, p in truth if t == p)
print(f"     classifier vs filename truth: {hits}/{len(truth)} correct "
      f"{[(t, p) for t, p in truth if t != p] or ''}")
check("classifier beats chance on the labelled frames (4 classes)",
      hits / max(1, len(truth)) > 0.25, f"{hits}/{len(truth)}")
print(f"     latency: median {statistics.median(times):.0f} ms, "
      f"min {min(times):.0f}, max {max(times):.0f}")
check("median latency under 3 s", statistics.median(times) < 3000, f"{statistics.median(times):.0f} ms")

# ------------------------------------------------------- 4. response contract
print("\n=== 4. RESPONSE CONTRACT ===")
_, d = results[samples[0]["id"]]
for k in ("frame_id", "width", "height", "image", "overlay", "condition",
          "defects", "defect_count", "severity", "localizer_ran", "timings_ms", "device"):
    check(f"field '{k}' present", k in d)
c = d["condition"]
check("condition has label + confidence + probabilities",
      {"label", "confidence", "probabilities"} <= set(c))
check("confidence is a probability", 0 <= c["confidence"] <= 1, c["confidence"])
check("probabilities cover all four classes", set(c["probabilities"]) == CLASSES)
check("probabilities sum to ~1", abs(sum(c["probabilities"].values()) - 1) < 0.01,
      sum(c["probabilities"].values()))
check("the reported label is the argmax",
      max(c["probabilities"], key=c["probabilities"].get) == c["label"],
      f"{c['label']} vs {max(c['probabilities'], key=c['probabilities'].get)}")
sev = d["severity"]
check("severity has score/grade/provenance", {"score", "grade", "provenance"} <= set(sev))
check("severity score in range", 0 <= sev["score"] <= 1, sev["score"])
check("severity grade is a known grade", sev["grade"] in GRADES, sev["grade"])
check("severity is labelled Estimated (no ground truth exists)",
      sev["provenance"].lower().startswith("estimat"), sev["provenance"])
if d["defects"]:
    b = d["defects"][0]
    check("a box carries xyxy + confidence", {"bbox_xyxy", "confidence"} <= set(b))
    x1, y1, x2, y2 = b["bbox_xyxy"]
    check("box is inside the frame",
          0 <= x1 < x2 <= d["width"] and 0 <= y1 < y2 <= d["height"],
          f"{b['bbox_xyxy']} in {d['width']}x{d['height']}")
    check("box confidence is a probability", 0 <= b["confidence"] <= 1, b["confidence"])
check("defect_count matches the list", d["defect_count"] == len(d["defects"]))
check("image and overlay are base64 payloads", len(d["image"]) > 1000 and len(d["overlay"]) > 1000)
check("overlay differs from the source image", d["image"] != d["overlay"])
t = d["timings_ms"]
check("timings add up to the total",
      abs(sum(v for k, v in t.items() if k != "total") - t["total"]) < 60, t)

# --------------------------------------------------------------- 5. options
print("\n=== 5. OPTIONS ===")
sid = samples[0]["id"]
_, off = post_form("/api/m3/analyse", {"sample": sid, "localizer": "false"})
check("localizer=false skips detection", off["localizer_ran"] is False and off["defect_count"] == 0,
      f"ran={off['localizer_ran']} n={off['defect_count']}")
check("...and is faster than with it", off["timings_ms"]["localize"] == 0, off["timings_ms"])
check("classification still runs without the localizer", off["condition"]["label"] in CLASSES)
_, nocam = post_form("/api/m3/analyse", {"sample": sid, "cam": "false"})
check("cam=false still returns an overlay", "overlay" in nocam)
_, hi = post_form("/api/m3/analyse", {"sample": sid, "conf": "0.99"})
_, lo = post_form("/api/m3/analyse", {"sample": sid, "conf": "0.05"})
check("a high confidence floor yields no more boxes than a low one",
      hi["defect_count"] <= lo["defect_count"], f"{hi['defect_count']} vs {lo['defect_count']}")
check("conf=0.99 suppresses boxes", hi["defect_count"] == 0, hi["defect_count"])

# ---------------------------------------------------------------- 6. uploads
print("\n=== 6. UPLOADS ===")
_, img, _ = get_bytes("/api/m3/samples/" + sid)
code, up = post_form("/api/m3/analyse", {}, {"file": ("rail.jpg", img, "image/jpeg")})
check("an uploaded photo analyses", code == 200 and up["condition"]["label"] in CLASSES,
      up.get("condition", up))
check("upload and sample agree on the same bytes",
      up["condition"]["label"] == results[sid][1]["condition"]["label"],
      f"{up['condition']['label']} vs {results[sid][1]['condition']['label']}")
check("frame_id comes from the filename", up["frame_id"] == "rail", up["frame_id"])

# ----------------------------------------------------------------- 7. guards
print("\n=== 7. GUARDS ===")
code, _ = post_form("/api/m3/analyse", {})
check("neither file nor sample -> 400", code == 400, code)
code, _ = post_form("/api/m3/analyse", {"sample": "nope/missing.jpg"})
check("unknown sample -> 404", code == 404, code)
code, body = post_form("/api/m3/analyse", {}, {"file": ("x.jpg", b"not an image at all", "image/jpeg")})
check("a corrupt image -> 400, not 500", code == 400, f"{code} {str(body)[:70]}")
code, _ = post_form("/api/m3/analyse", {}, {"file": ("x.txt", b"hello", "text/plain")})
check("a non-image -> 400", code == 400, code)
big = b"\xff\xd8" + b"\x00" * (21 * 1024 * 1024)
code, _ = post_form("/api/m3/analyse", {}, {"file": ("big.jpg", big, "image/jpeg")}, timeout=300)
check("an oversized upload -> 413", code == 413, code)
code, _ = post_form("/api/m3/analyse", {"sample": sid, "conf": "abc"})
check("a non-numeric conf is rejected", code == 422, code)

# ------------------------------------------------------------ 8. determinism
print("\n=== 8. DETERMINISM ===")
runs = [post_form("/api/m3/analyse", {"sample": sid})[1] for _ in range(3)]
check("the same image gives the same label",
      len({r["condition"]["label"] for r in runs}) == 1)
check("...and the same confidence",
      len({round(r["condition"]["confidence"], 6) for r in runs}) == 1,
      [round(r["condition"]["confidence"], 4) for r in runs])
check("...and the same box count", len({r["defect_count"] for r in runs}) == 1)

# ------------------------------------------------------------ 9. concurrency
print("\n=== 9. CONCURRENCY (2 vCPU — modest, deliberately) ===")
t0 = time.time()
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    futs = [ex.submit(post_form, "/api/m3/analyse", {"sample": x["id"]}) for x in samples[:4]]
    conc = [f.result() for f in futs]
check("4 parallel requests all return 200", all(c == 200 for c, _ in conc),
      [c for c, _ in conc])
check("results are not cross-contaminated",
      len({d["frame_id"] for _, d in conc}) == 4, [d["frame_id"] for _, d in conc])
print(f"     4 concurrent in {(time.time()-t0):.1f}s")

# ------------------------------------------------------- 10. no regressions
print("\n=== 10. THE REST OF THE PLATFORM IS UNAFFECTED ===")
code, h = get("/api/health")
check("health still ok", h["status"] == "ok")
code, sim = post_form("/api/simulate", {}) if False else (0, None)
req = urllib.request.Request(BASE + "/api/simulate", method="POST",
                             data=json.dumps({"scenario": "kumbh_surge"}).encode(),
                             headers={"Content-Type": "application/json"})
sim = json.loads(urllib.request.urlopen(req, timeout=120, context=CTX).read())["summary"]
check("crowd baseline unchanged",
      (sim["peak_density"], sim["crush_count"], sim["danger_count"]) == (17.39, 4, 5),
      (sim["peak_density"], sim["crush_count"], sim["danger_count"]))
check("corridor answer unchanged by loading the networks",
      _corridor() == CORRIDOR_BEFORE, (CORRIDOR_BEFORE, _corridor()))
try:
    urllib.request.urlopen(BASE + "/api/policy/library", timeout=30, context=CTX)
    check("policy is still gated", False, "served without sign-in")
except urllib.error.HTTPError as e:
    check("policy is still gated", e.code == 401, e.code)

print(f"\n{'='*62}\nM3: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILURES:")
    for f in FAIL: print("   -", f)
sys.exit(1 if FAIL else 0)
