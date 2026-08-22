import { useEffect, useMemo, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, ReferenceLine, Tooltip } from 'recharts'
import StationMap from '../components/StationMap.jsx'
import StationScene3D from '../three/StationScene3D.jsx'
import { getStation, getScenarios, simulate, optimizeCrowd } from '../api.js'
import { statusFor, LOS } from '../los.js'

const MITIGATIONS = [
  { key: 'metered_holding', label: 'Metered holding', hint: 'Hold passengers in safe areas; release onto the FOB at a safe rate' },
  { key: 'open_fob', label: 'One-way / extra FOB lanes', hint: 'Double effective foot-over-bridge egress' },
  { key: 'stagger_release', label: 'Staggered release', hint: 'Spread the platform release over more time' },
  { key: 'extra_exits', label: 'Open extra exit gates', hint: 'Add dispersal capacity at more gates' },
]

export default function M1Crowd() {
  const [station, setStation] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [scenario, setScenario] = useState('kumbh_surge')
  const [mit, setMit] = useState({})
  const [sim, setSim] = useState(null)
  const [baseline, setBaseline] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('3d')
  const [opt, setOpt] = useState(null)
  const [optRunning, setOptRunning] = useState(false)

  useEffect(() => {
    getStation().then(setStation).catch((e) => setError(e.message))
    getScenarios().then(setScenarios).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!station) return
    let cancel = false
    setLoading(true); setError(null)
    const anyMit = Object.values(mit).some(Boolean)
    Promise.all([simulate(scenario, {}), anyMit ? simulate(scenario, mit) : null])
      .then(([base, mitigated]) => {
        if (cancel) return
        setBaseline(base); setSim(mitigated || base); setLoading(false)
      })
      .catch((e) => { if (!cancel) { setError(e.message); setLoading(false) } })
    return () => { cancel = true }
  }, [station, scenario, mit])

  const anyMit = Object.values(mit).some(Boolean)
  const cur = sim?.summary
  const status = cur ? statusFor(cur.peak_density, cur.crush_count) : null
  const baseSummary = baseline?.summary

  const reduction = useMemo(() => {
    if (!anyMit || !baseSummary || !cur) return null
    const b = baseSummary.peak_density, m = cur.peak_density
    return b ? Math.round(((b - m) / b) * 100) : 0
  }, [anyMit, baseSummary, cur])

  // Carry BOTH series so the mitigated curve is drawn against the no-action one.
  async function runOptimizer() {
    setOptRunning(true); setError(null)
    try {
      const r = await optimizeCrowd(scenario)
      setOpt(r)
      // Apply the winning plan to the toggles so the map, the 3D ghosts and
      // the before/after badge all reflect what the optimizer chose.
      setMit(r.recommended.mitigations)
    } catch (e) {
      setError(e.message)
    } finally {
      setOptRunning(false)
    }
  }

  const timeline = useMemo(() => {
    if (!sim) return []
    const b = baseline?.timeline || []
    return sim.timeline.map((d, i) => ({ t: i * 2, density: d, noaction: b[i] ?? null }))
  }, [sim, baseline])

  // Lock the Y scale across both runs. With domain=[0,'auto'] the mitigated run
  // rescaled to its own peak (~3.4), which pushed the 5.0 CRUSH line off-chart
  // and made a solved scenario look identical to the crisis it solved.
  const yMax = useMemo(
    () => Math.ceil(Math.max(baseSummary?.peak_density || 0, cur?.peak_density || 0, 6)),
    [baseSummary, cur],
  )
  const scenarioMeta = scenarios.find((s) => s.key === scenario)

  return (
    <div className="view">
      <div className="body">
        <aside className="sidebar">
          <section className="panel">
            <h3>Scenario</h3>
            <select value={scenario} onChange={(e) => { setScenario(e.target.value); setMit({}); setOpt(null) }}>
              {scenarios.map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
            </select>
            {scenarioMeta && <p className="muted">{scenarioMeta.description}</p>}
            {scenarioMeta?.total_people > 0 && (
              <p className="muted small">Crowd in scenario: <b>{scenarioMeta.total_people.toLocaleString()}</b> people</p>
            )}
          </section>

          <section className="panel">
            <h3>AI optimizer</h3>
            <button className="btn primary full" disabled={optRunning} onClick={runOptimizer}>
              {optRunning ? 'Evaluating 16 plans…' : 'Run Nova Optimizer'}
            </button>
            <p className="muted small" style={{ marginTop: 8 }}>
              Runs the flow model on every combination of the four measures, ranks
              them by crush points then peak density, and applies the winner.
            </p>
            {optRunning && (
              <div className="ai-working">
                <span className="dots"><i /><i /><i /></span>
                Running the flow model on all 16 plans, then writing the brief…
              </div>
            )}
            {opt && !optRunning && (
              <div className="ai-result">
                <div className="ai-head">
                  <span className={`ai-src ${opt.brief.source}`}>
                    {opt.brief.source === 'gemini' ? 'GEMINI BRIEF' : 'COMPUTED BRIEF'}
                  </span>
                  <span className="ai-meta">{opt.evaluated} plans evaluated</span>
                </div>
                <div className="ai-plan">
                  {opt.recommended.labels.length
                    ? opt.recommended.labels.map((l) => <span key={l} className="ai-chip">{l}</span>)
                    : <span className="ai-chip none">No intervention needed</span>}
                </div>
                <p className="ai-brief">{opt.brief.text}</p>
                {opt.brief.error && (
                  <p className="ai-err" title={opt.brief.error}>
                    Gemini unavailable — showing the computed summary.
                  </p>
                )}
              </div>
            )}
          </section>

          <section className="panel">
            <h3>What-if mitigations</h3>
            {MITIGATIONS.map((m) => (
              <label key={m.key} className={`toggle ${mit[m.key] ? 'on' : ''}`}>
                <input type="checkbox" checked={!!mit[m.key]}
                  onChange={(e) => setMit({ ...mit, [m.key]: e.target.checked })} />
                <div>
                  <div className="tlabel">{m.label}</div>
                  <div className="thint">{m.hint}</div>
                </div>
              </label>
            ))}
            {anyMit && <button className="btn ghost full" style={{ marginTop: 8 }} onClick={() => { setMit({}); setOpt(null) }}>Reset to baseline</button>}
          </section>

          <section className="panel legend">
            <h3>Density · Fruin LOS</h3>
            {Object.entries(LOS).map(([g, v]) => (
              <div className="legrow" key={g}>
                <span className="swatch" style={{ background: v.color }} />
                <span>{g} · {v.label}</span>
              </div>
            ))}
            <p className="muted small">persons / m². ≥ 5 = crush regime.</p>
          </section>
        </aside>

        <main className="stage">
          <div className="statusbar">
            {status && (
              <div className="status-chip" style={{ borderColor: status.color, color: status.color }}>
                <span className="dot" style={{ background: status.color }} />{status.label}
              </div>
            )}
            {sim && <SourceBadge sim={sim} />}
            <Metric label="Peak density" value={cur ? `${cur.peak_density} p/m²` : '—'}
              sub={cur ? `LOS ${cur.peak_los}` : ''} danger={cur && cur.peak_density >= 5} />
            <Metric label="Crush points" value={cur ? cur.crush_count : '—'} danger={cur && cur.crush_count > 0} />
            <Metric label="People" value={cur ? Math.round(cur.total_injected).toLocaleString() : '—'} />
            {anyMit && reduction != null && (
              <div className="impact-chip">
                <div className="impact-num">{reduction > 0 ? `−${reduction}%` : `${reduction}%`}</div>
                <div className="impact-lbl">peak density vs. no action<br />
                  <b>{baseSummary?.peak_density}</b> → <b>{cur?.peak_density}</b> p/m² · crush <b>{baseSummary?.crush_count}</b> → <b>{cur?.crush_count}</b>
                </div>
              </div>
            )}
            {loading && <span className="loading">simulating…</span>}
            {error && <span className="error-chip" title={error}>⚠ {error}</span>}
            <div className="viewtoggle">
              <button className={mode === '2d' ? 'on' : ''} onClick={() => setMode('2d')}>2D MAP</button>
              <button className={mode === '3d' ? 'on' : ''} onClick={() => setMode('3d')}>3D</button>
            </div>
          </div>

          {mode === '3d'
            ? <StationScene3D station={station} sim={sim} baseline={anyMit ? baseline : null} analyzing={optRunning} />
            : <StationMap station={station} sim={sim} />}

          <div className="bottom">
            <div className="chart">
              <div className="chart-title">
                Peak density over time {anyMit ? '— mitigated vs. no action' : '(no action)'}
              </div>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={timeline} margin={{ top: 6, right: 12, left: -18, bottom: 0 }}>
                  <XAxis dataKey="t" tick={{ fontSize: 10, fill: '#8a857e' }} unit="s" />
                  <YAxis tick={{ fontSize: 10, fill: '#8a857e' }} domain={[0, yMax]} allowDataOverflow />
                  <Tooltip contentStyle={{ background: '#15181b', border: '1px solid #333a41', borderRadius: 2, fontSize: 11, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }} />
                  <ReferenceLine y={5} stroke="#e5484d" strokeDasharray="4 3" label={{ value: 'CRUSH', fill: '#e5484d', fontSize: 9 }} />
                  <ReferenceLine y={3.5} stroke="#e07b00" strokeDasharray="3 3" />
                  {anyMit && (
                    <Line type="monotone" dataKey="noaction" name="no action" stroke="#e5484d"
                      dot={false} strokeWidth={1.6} strokeDasharray="4 3" strokeOpacity={0.6}
                      isAnimationActive={false} />
                  )}
                  <Line type="monotone" dataKey="density" name={anyMit ? 'mitigated' : 'no action'}
                    stroke="#f0a500" dot={false} strokeWidth={2} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="alerts">
              <div className="chart-title">Control-room alerts</div>
              <div className="alert-list">
                {sim?.node_hotspots?.length ? sim.node_hotspots.slice(0, 6).map((h, i) => (
                  <div key={i} className={`alert ${h.los === 'F' ? 'crit' : 'warn'}`}>
                    <b>{h.los === 'F' ? 'CRUSH' : 'DANGER'}</b> {h.name || h.kind} · {h.density.toFixed(1)} p/m² · queue {h.queue}
                    <div className="action">{actionFor(h)}</div>
                  </div>
                )) : <div className="alert ok">No danger zones — flow within safe limits ✓</div>}
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

function SourceBadge({ sim }) {
  const m = sim.demand_meta || {}
  if (sim.source === 'live') {
    const when = sim.generated_at ? new Date(sim.generated_at).toLocaleTimeString() : ''
    return (
      <div className="src-chip live" title={`Live ${m.endpoint || ''} · platform & crowd load ESTIMATED (API provides neither)`}>
        <span className="src-dot" /><span>LIVE SCHEDULE</span>
        <span className="src-sub">{m.used ?? 0} trains · est.{when ? ` · ${when}` : ''}</span>
      </div>
    )
  }
  if (sim.source === 'live_snapshot') {
    const cap = m.captured_at ? new Date(m.captured_at).toLocaleString() : 'recently'
    return (
      <div className="src-chip live" title={`Real arrivals captured ${cap}; served because the live API is rate-limited / unavailable`}>
        <span className="src-dot" /><span>LIVE SNAPSHOT</span>
        <span className="src-sub">{m.used ?? 0} real trains · API rate-limited</span>
      </div>
    )
  }
  if (sim.source === 'fixture_fallback') {
    return <div className="src-chip warn" title={m.live_error || 'Live feed unavailable'}>
      <span className="src-dot" /><span>FIXTURE</span><span className="src-sub">live feed unavailable</span></div>
  }
  return <div className="src-chip" title="Hand-authored demand scenario (not live data)">
    <span className="src-dot" /><span>FIXTURE</span><span className="src-sub">authored scenario</span></div>
}

function Metric({ label, value, sub, danger, good }) {
  return (
    <div className={`metric ${danger ? 'danger' : ''} ${good ? 'good' : ''}`}>
      <div className="metric-val">{value}</div>
      <div className="metric-lbl">{label}{sub ? ` · ${sub}` : ''}</div>
    </div>
  )
}

function actionFor(h) {
  if (h.los === 'F') return '→ Hold gate, meter onto FOB, deploy RPF + medical to hotspot'
  return '→ Slow platform release, open additional exit, station staff to monitor'
}
