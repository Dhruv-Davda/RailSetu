import { useEffect, useMemo, useRef, useState } from 'react'
import { analyseM3, getM3Samples, m3SampleUrl, warmM3 } from '../api.js'

/*
 * M3 — Rail Surface Defect Inspection.
 *
 * Two networks run per image: EfficientNet-B0 names the surface condition,
 * YOLO11-s locates the damage. The page deliberately exposes the intermediate
 * work — per-stage timings, the full probability vector, and the Grad-CAM
 * attention map — rather than reducing two models to a single word. A judge
 * can see *why* the answer is what it is, and check it against a known label.
 */

const CLASS_COLOR = {
  flaking: 'var(--accent)',
  squat: 'var(--bad)',
  spalling: 'var(--elev)',
  shelling: 'var(--good)',
}

// Plain-language gloss for each class, so the page is readable by someone who
// has never heard of a rail squat.
const CLASS_NOTE = {
  flaking: 'Thin layers of steel peeling off the running surface.',
  squat: 'A localised depression with cracking — the most serious of the four.',
  spalling: 'Chunks of metal broken away from the railhead.',
  shelling: 'Sub-surface fatigue lifting a shell of metal off the rail.',
}

// The five stages a request genuinely passes through. Every timing shown is
// measured server-side and returned in the payload — none of it is a
// decorative progress bar.
const STAGES = [
  { key: 'decode', name: 'Decode & normalise', detail: 'Resize 257 · centre-crop 224 · ImageNet statistics' },
  { key: 'classify', name: 'EfficientNet-B0', detail: 'Forward pass · softmax over 4 classes · Grad-CAM backward' },
  { key: 'localize', name: 'YOLO11-s', detail: '640px letterbox · detection head · NMS' },
  { key: 'severity', name: 'Severity rule', detail: 'Type weight × confidence × area coverage' },
  { key: 'render', name: 'Composite', detail: 'Grad-CAM heat blend · JPEG encode' },
]

const fmt = (n) => (n == null ? '—' : n.toLocaleString())
const params = (n) => (n == null ? '—' : `${(n / 1e6).toFixed(1)}M`)

export default function M3Defect() {
  const [status, setStatus] = useState(null)
  const [samples, setSamples] = useState([])
  const [active, setActive] = useState(null)     // the sample being viewed, if any
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [stage, setStage] = useState(-1)
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null)   // local object URL while uploading

  const [showCam, setShowCam] = useState(true)
  const [showBoxes, setShowBoxes] = useState(true)
  const [useLocalizer, setUseLocalizer] = useState(true)
  const [hover, setHover] = useState(-1)
  const fileRef = useRef(null)

  // Warming triggers the actual model load. It is deliberately the first thing
  // the page does: loading takes seconds, and paying that cost on arrival is far
  // better than paying it on the first click.
  useEffect(() => {
    warmM3().then(setStatus).catch((e) => setError(e.message))
    getM3Samples().then(setSamples).catch(() => {})
  }, [])

  // Walk the stage lamps forward while the request is in flight. The real
  // timings replace this the moment the response lands.
  useEffect(() => {
    if (!running) return
    setStage(0)
    const id = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 380)
    return () => clearInterval(id)
  }, [running])

  async function run({ file, sample }) {
    setRunning(true); setError(null); setResult(null); setHover(-1)
    try {
      const r = await analyseM3({ file, sample, localizer: useLocalizer, cam: true })
      setResult(r)
      setStage(STAGES.length)
    } catch (e) {
      setError(e.message)
      setStage(-1)
    } finally {
      setRunning(false)
    }
  }

  function pickSample(s) {
    setActive(s); setPreview(null)
    run({ sample: s.id })
  }

  function pickFile(f) {
    if (!f) return
    setActive(null)
    setPreview(URL.createObjectURL(f))
    run({ file: f })
  }

  const cond = result?.condition
  const probs = useMemo(() => {
    if (!cond) return []
    return Object.entries(cond.probabilities).sort((a, b) => b[1] - a[1])
  }, [cond])

  const correct = active?.truth && cond ? active.truth === cond.label : null
  const shown = result ? (showCam && result.overlay ? result.overlay : result.image) : preview
  const ready = status?.loaded
  const metrics = status?.metrics || {}

  return (
    <div className="view">
      <div className="body">
        <aside className="sidebar">
          <section className="panel">
            <h3>What this is</h3>
            <p className="muted">
              Two neural networks inspect a photograph of railway track. <b>Model A</b> names
              the surface defect; <b>Model B</b> draws a box around it. Together they turn a
              photo into an inspection record a maintenance crew could act on.
            </p>
          </section>

          <section className="panel">
            <h3>Model stack</h3>
            {(status?.models || []).map((m) => (
              <div className="m3-spec" key={m.key}>
                <div className="m3-spec-top">
                  <span className="m3-spec-arch">{m.arch}</span>
                  <span className="m3-spec-params">{params(m.params)} params</span>
                </div>
                <div className="m3-spec-q">{m.question}</div>
                <div className="m3-spec-io">
                  <span>{m.input}</span>
                  <span>{m.classes.length} class{m.classes.length > 1 ? 'es' : ''}</span>
                </div>
                {m.key === 'a' && metrics.a && (
                  <div className="m3-spec-metric">
                    <b>{metrics.a.accuracy}</b> accuracy · <b>{metrics.a.macro_f1}</b> macro-F1
                    <span className="faint"> · {fmt(metrics.a.split_sizes?.test)} held-out images</span>
                  </div>
                )}
                {m.key === 'b' && metrics.b && (
                  <div className="m3-spec-metric">
                    <b>{metrics.b.map50}</b> mAP@50 · <b>{metrics.b.recall}</b> recall
                    <span className="faint"> · {metrics.b.variant}</span>
                  </div>
                )}
              </div>
            ))}
          </section>

          <section className="panel">
            <h3>Controls</h3>
            <label className={`toggle ${useLocalizer ? 'on' : ''}`}>
              <input type="checkbox" checked={useLocalizer} onChange={(e) => setUseLocalizer(e.target.checked)} />
              <div>
                <div className="tlabel">Run localizer (Model B)</div>
                <div className="thint">Draw boxes around the damage</div>
              </div>
            </label>
            <label className={`toggle ${showCam ? 'on' : ''} ${!result?.overlay ? 'off' : ''}`}>
              <input type="checkbox" checked={showCam} disabled={!result?.overlay} onChange={(e) => setShowCam(e.target.checked)} />
              <div>
                <div className="tlabel">Grad-CAM attention</div>
                <div className="thint">Where the classifier actually looked</div>
              </div>
            </label>
            <label className={`toggle ${showBoxes ? 'on' : ''} ${!result?.defect_count ? 'off' : ''}`}>
              <input type="checkbox" checked={showBoxes} disabled={!result?.defect_count} onChange={(e) => setShowBoxes(e.target.checked)} />
              <div>
                <div className="tlabel">Detection boxes</div>
                <div className="thint">Overlay Model B's output</div>
              </div>
            </label>
            <p className="muted small" style={{ marginTop: 10 }}>
              Model B v1 boxed ballast on wide track photos — it had only ever been trained
              on tight railhead close-ups and had no concept of "nothing here". v2 was
              retrained with 216 gravel crops as background negatives: false boxes on wide
              frames fell from <b>2.29</b> to <b>0.18</b> per image, with detection on
              close-ups intact.
            </p>
          </section>

          <section className="panel">
            <h3>Provenance</h3>
            <div className="m3-prov"><span className="m3-prov-tag mod">MODELLED</span>Defect type and box position are network outputs.</div>
            <div className="m3-prov"><span className="m3-prov-tag est">ESTIMATED</span>Severity is a rule — the training data carries no severity labels, so nothing could have learned it.</div>
          </section>
        </aside>

        <main className="stage">
          <div className="statusbar">
            <div className="status-chip" style={{ borderColor: ready ? 'var(--good)' : 'var(--warn)', color: ready ? 'var(--good)' : 'var(--warn)' }}>
              <span className="dot" style={{ background: ready ? 'var(--good)' : 'var(--warn)' }} />
              SURFACE DEFECT INSPECTION
            </div>
            <div className="src-chip" title="Network output, not measured ground truth"><span className="src-dot" />MODELLED</div>
            <Metric label="Runtime" value={status?.device ? status.device.toUpperCase() : '—'} />
            <Metric label="Inference" value={result ? `${Math.round(result.timings_ms.total)} ms` : '—'} />
            <Metric label="Defects boxed" value={result ? result.defect_count : '—'} />
            {error && <span className="error-chip" title={error}>⚠ {error}</span>}
          </div>

          {!ready && !error && (
            <div className="m3-boot">
              <div className="m3-boot-bar"><i /></div>
              Loading model weights into memory…
              <span className="faint"> first visit only</span>
            </div>
          )}
          {status && !status.loaded && status.error && (
            <div className="m3-unavailable">
              <b>Inference runtime unavailable.</b>
              <div className="m3-err-detail">{status.error}</div>
              <div className="muted small">
                The rest of RailSetu is unaffected — M3 loads PyTorch lazily so a host without
                the ML extras still serves every other module. Install with:
                <code>pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision &amp;&amp; pip install ultralytics</code>
              </div>
            </div>
          )}

          <div className="m3-main">
            <div
              className={`m3-canvas ${!shown ? 'empty' : ''}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); pickFile(e.dataTransfer.files?.[0]) }}
            >
              {!shown && (
                <div className="m3-drop" onClick={() => fileRef.current?.click()}>
                  <div className="m3-drop-ico">
                    <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
                      <rect x="3" y="4" width="18" height="16" rx="1" />
                      <path d="M3 16l5-4 4 3 3-3 6 5" /><circle cx="9" cy="9" r="1.4" />
                    </svg>
                  </div>
                  <b>Drop a rail photograph</b>
                  <span className="muted small">or click to browse — JPEG or PNG, up to 20 MB</span>
                  <span className="muted small">no photo handy? pick one from the strip below</span>
                </div>
              )}
              {shown && (
                <div className="m3-frame">
                  <img src={shown} alt={result?.frame_id || 'input'} />
                  {showBoxes && result?.defects?.map((d, i) => (
                    <div
                      key={i}
                      className={`m3-box ${hover === i ? 'hot' : ''}`}
                      style={{ left: `${d.bbox_pct[0]}%`, top: `${d.bbox_pct[1]}%`, width: `${d.bbox_pct[2]}%`, height: `${d.bbox_pct[3]}%` }}
                      onMouseEnter={() => setHover(i)}
                      onMouseLeave={() => setHover(-1)}
                    >
                      <span className="m3-box-tag">defect {d.confidence.toFixed(2)}</span>
                    </div>
                  ))}
                  {running && <div className="m3-scan" />}
                </div>
              )}
              {shown && (
                <div className="m3-canvas-foot">
                  <span className="m3-fid">{result?.frame_id || 'uploaded image'}</span>
                  {result && <span className="faint">{result.width}×{result.height}px</span>}
                  <span className="spacer" style={{ flex: 1 }} />
                  <button className="btn ghost" onClick={() => fileRef.current?.click()}>New image</button>
                </div>
              )}
            </div>

            <div className="m3-right">
              <div className="chart-title">Pipeline</div>
              <div className="m3-pipe">
                {STAGES.map((s, i) => {
                  const done = result && (stage >= STAGES.length || i < stage)
                  const live = running && i === stage
                  const ms = result?.timings_ms?.[s.key]
                  const skipped = result && s.key === 'localize' && !result.localizer_ran
                  return (
                    <div key={s.key} className={`m3-step ${done ? 'done' : ''} ${live ? 'live' : ''} ${skipped ? 'skip' : ''}`}>
                      <span className="m3-lamp" />
                      <div className="m3-step-body">
                        <div className="m3-step-name">
                          {s.name}
                          {skipped && <em> — off</em>}
                        </div>
                        <div className="m3-step-detail">{s.detail}</div>
                      </div>
                      <span className="m3-step-ms">{ms != null ? `${ms.toFixed(0)}ms` : live ? '···' : ''}</span>
                    </div>
                  )
                })}
              </div>

              {cond && (
                <>
                  <div className="chart-title" style={{ marginTop: 18 }}>Verdict</div>
                  <div className="m3-verdict" style={{ borderLeftColor: CLASS_COLOR[cond.label] }}>
                    <div className="m3-verdict-top">
                      <span className="m3-label" style={{ color: CLASS_COLOR[cond.label] }}>{cond.label}</span>
                      <span className="m3-conf">{(cond.confidence * 100).toFixed(1)}%</span>
                    </div>
                    <div className="m3-verdict-note">{CLASS_NOTE[cond.label]}</div>
                    <div className="m3-chips">
                      {cond.low_confidence && <span className="m3-chip warn">LOW CONFIDENCE</span>}
                      {correct === true && <span className="m3-chip ok">MATCHES KNOWN LABEL · {active.truth}</span>}
                      {correct === false && <span className="m3-chip bad">KNOWN LABEL WAS {active.truth}</span>}
                      <span className={`m3-chip sev-${result.severity.grade.toLowerCase()}`}>
                        {result.severity.grade} · {result.severity.score}
                      </span>
                    </div>
                  </div>

                  <div className="chart-title" style={{ marginTop: 16 }}>Class probabilities</div>
                  {probs.map(([k, v]) => (
                    <div className="m3-prob" key={k}>
                      <span className="m3-prob-name">{k}</span>
                      <span className="m3-prob-bar">
                        <i style={{ width: `${Math.max(v * 100, 0.6)}%`, background: CLASS_COLOR[k] }} />
                      </span>
                      <span className="m3-prob-val">{(v * 100).toFixed(1)}</span>
                    </div>
                  ))}

                  <div className="chart-title" style={{ marginTop: 16 }}>
                    Detections {result.localizer_ran ? `(${result.defect_count})` : ''}
                  </div>
                  {!result.localizer_ran && <p className="muted small">Localizer off for this image.</p>}
                  {result.localizer_ran && result.defect_count === 0 && (
                    <p className="muted small">No defect region above the confidence floor.</p>
                  )}
                  {result.defects.map((d, i) => (
                    <div
                      key={i}
                      className={`m3-det ${hover === i ? 'hot' : ''}`}
                      onMouseEnter={() => setHover(i)}
                      onMouseLeave={() => setHover(-1)}
                    >
                      <span className="m3-det-n">{i + 1}</span>
                      <span className="m3-det-box">{d.bbox_xyxy.map((v) => Math.round(v)).join(', ')}</span>
                      <span className="m3-det-conf">{(d.confidence * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                  <p className="disclaimer">
                    Severity is Estimated: defect-type weight × confidence × area coverage. The
                    source dataset carries no severity annotations.
                  </p>
                </>
              )}
            </div>
          </div>

          <div className="m3-strip">
            <div className="m3-strip-head">
              <span className="section-label">Held-out test photographs</span>
              <span className="faint small">
                never seen during training · file name carries the true label
              </span>
            </div>
            <div className="m3-thumbs">
              {samples.map((s) => (
                <button
                  key={s.id}
                  className={`m3-thumb ${active?.id === s.id ? 'on' : ''}`}
                  onClick={() => pickSample(s)}
                  title={`${s.kind} — ${s.truth || 'unlabelled'}`}
                  disabled={running}
                >
                  <img src={m3SampleUrl(s.id)} alt={s.name} loading="lazy" />
                  <span className="m3-thumb-tag" style={{ color: CLASS_COLOR[s.truth] || 'var(--t1)' }}>
                    {s.truth || 'crack'}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={(e) => pickFile(e.target.files?.[0])}
          />
        </main>
      </div>
    </div>
  )
}

function Metric({ label, value }) {
  return <div className="metric"><div className="metric-val">{value}</div><div className="metric-lbl">{label}</div></div>
}
