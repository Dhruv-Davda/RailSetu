import { useEffect, useMemo, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, ReferenceLine, Tooltip } from 'recharts'
import StationMap from './StationMap.jsx'
import { getStation, getScenarios, simulate } from './api.js'
import { statusFor, LOS } from './los.js'

const MITIGATIONS = [
  { key: 'metered_holding', label: 'Metered holding', hint: 'Hold passengers in safe areas; release onto the FOB at a safe rate' },
  { key: 'open_fob', label: 'One-way / extra FOB lanes', hint: 'Double effective foot-over-bridge egress' },
  { key: 'stagger_release', label: 'Staggered release', hint: 'Spread the platform release over more time' },
  { key: 'extra_exits', label: 'Open extra exit gates', hint: 'Add dispersal capacity at more gates' },
]

export default function App() {
  const [station, setStation] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [scenario, setScenario] = useState('kumbh_surge')
  const [mit, setMit] = useState({})
  const [sim, setSim] = useState(null)
  const [baseline, setBaseline] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getStation().then(setStation)
    getScenarios().then(setScenarios)
  }, [])

  // Run baseline (no mitigations) + current sim whenever scenario/mitigations change.
  useEffect(() => {
    if (!station) return
    let cancel = false
    setLoading(true)
    const anyMit = Object.values(mit).some(Boolean)
    Promise.all([
      simulate(scenario, {}),
      anyMit ? simulate(scenario, mit) : null,
    ]).then(([base, mitigated]) => {
      if (cancel) return
      setBaseline(base)
      setSim(mitigated || base)
      setLoading(false)
    })
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

  const timeline = useMemo(() => {
    if (!sim) return []
    return sim.timeline.map((d, i) => ({ t: i * 2, density: d }))
  }, [sim])

  const scenarioMeta = scenarios.find((s) => s.key === scenario)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">🚉 RailSetu</span>
          <span className="tag">M1 · Station Crowd-Flow &amp; Stampede Prevention</span>
        </div>
        <div className="station-name">New Delhi · NDLS Control Room</div>
      </header>

      <div className="body">
        <aside className="sidebar">
          <section className="panel">
            <h3>Scenario</h3>
            <select value={scenario} onChange={(e) => { setScenario(e.target.value); setMit({}) }}>
              {scenarios.map((s) => (
                <option key={s.key} value={s.key}>{s.title}</option>
              ))}
            </select>
            {scenarioMeta && <p className="muted">{scenarioMeta.description}</p>}
            {scenarioMeta && <p className="muted small">Crowd in scenario: <b>{scenarioMeta.total_people.toLocaleString()}</b> people</p>}
          </section>

          <section className="panel">
            <h3>What-if mitigations</h3>
            {MITIGATIONS.map((m) => (
              <label key={m.key} className="toggle" title={m.hint}>
                <input
                  type="checkbox"
                  checked={!!mit[m.key]}
                  onChange={(e) => setMit({ ...mit, [m.key]: e.target.checked })}
                />
                <span>{m.label}</span>
              </label>
            ))}
            {anyMit && (
              <button className="reset" onClick={() => setMit({})}>Reset to baseline</button>
            )}
          </section>

          <section className="panel legend">
            <h3>Density (Fruin LOS)</h3>
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
                <span className="dot" style={{ background: status.color }} />
                {status.label}
              </div>
            )}
            <Metric label="Peak density" value={cur ? `${cur.peak_density} p/m²` : '—'}
              sub={cur ? `LOS ${cur.peak_los}` : ''} danger={cur && cur.peak_density >= 5} />
            <Metric label="Crush points" value={cur ? cur.crush_count : '—'}
              danger={cur && cur.crush_count > 0} />
            <Metric label="People in scenario" value={cur ? cur.total_injected.toLocaleString() : '—'} />
            {anyMit && reduction != null && (
              <div className="impact-chip">
                <div className="impact-num">{reduction > 0 ? `−${reduction}%` : `${reduction}%`}</div>
                <div className="impact-lbl">peak density vs. no action<br />
                  <b>{baseSummary?.peak_density}</b> → <b>{cur?.peak_density}</b> p/m² ·
                  crush <b>{baseSummary?.crush_count}</b> → <b>{cur?.crush_count}</b>
                </div>
              </div>
            )}
            {loading && <span className="loading">simulating…</span>}
          </div>

          <StationMap station={station} sim={sim} />

          <div className="bottom">
            <div className="chart">
              <div className="chart-title">Peak density over time {anyMit ? '(mitigated)' : '(no action)'}</div>
              <ResponsiveContainer width="100%" height={120}>
                <LineChart data={timeline} margin={{ top: 6, right: 12, left: -18, bottom: 0 }}>
                  <XAxis dataKey="t" tick={{ fontSize: 10, fill: '#8aa' }} unit="s" />
                  <YAxis tick={{ fontSize: 10, fill: '#8aa' }} domain={[0, 'auto']} />
                  <Tooltip contentStyle={{ background: '#0e1c2b', border: '1px solid #234', fontSize: 12 }} />
                  <ReferenceLine y={5} stroke="#e53935" strokeDasharray="4 3" label={{ value: 'crush', fill: '#e53935', fontSize: 10 }} />
                  <ReferenceLine y={3.5} stroke="#fb8c00" strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="density" stroke="#4fc3f7" dot={false} strokeWidth={2} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="alerts">
              <div className="chart-title">Control-room alerts</div>
              <div className="alert-list">
                {sim?.node_hotspots?.length ? sim.node_hotspots.slice(0, 5).map((h, i) => (
                  <div key={i} className={`alert ${h.los === 'F' ? 'crit' : 'warn'}`}>
                    <b>{h.los === 'F' ? 'CRUSH' : 'DANGER'}</b> {h.name || h.kind} ·
                    {' '}{h.density.toFixed(1)} p/m² · queue {h.queue}
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

function Metric({ label, value, sub, danger }) {
  return (
    <div className={`metric ${danger ? 'danger' : ''}`}>
      <div className="metric-val">{value}</div>
      <div className="metric-lbl">{label}{sub ? ` · ${sub}` : ''}</div>
    </div>
  )
}

function actionFor(h) {
  if (h.los === 'F') return '→ Hold gate, meter onto FOB, deploy RPF + medical to hotspot'
  return '→ Slow platform release, open additional exit, station staff to monitor'
}
