import { useEffect, useMemo, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, ReferenceLine, Tooltip } from 'recharts'
import StationMap from '../components/StationMap.jsx'
import { getStation, getScenarios, simulate } from '../api.js'
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

  const timeline = useMemo(() => (sim ? sim.timeline.map((d, i) => ({ t: i * 2, density: d })) : []), [sim])
  const scenarioMeta = scenarios.find((s) => s.key === scenario)

  return (
    <div className="view">
      <div className="body">
        <aside className="sidebar">
          <section className="panel">
            <h3>Scenario</h3>
            <select value={scenario} onChange={(e) => { setScenario(e.target.value); setMit({}) }}>
              {scenarios.map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
            </select>
            {scenarioMeta && <p className="muted">{scenarioMeta.description}</p>}
            {scenarioMeta?.total_people > 0 && (
              <p className="muted small">Crowd in scenario: <b>{scenarioMeta.total_people.toLocaleString()}</b> people</p>
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
            {anyMit && <button className="btn ghost full" style={{ marginTop: 8 }} onClick={() => setMit({})}>Reset to baseline</button>}
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
          </div>

          <StationMap station={station} sim={sim} />

          <div className="bottom">
            <div className="chart">
              <div className="chart-title">Peak density over time {anyMit ? '(mitigated)' : '(no action)'}</div>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={timeline} margin={{ top: 6, right: 12, left: -18, bottom: 0 }}>
                  <XAxis dataKey="t" tick={{ fontSize: 10, fill: '#8499b0' }} unit="s" />
                  <YAxis tick={{ fontSize: 10, fill: '#8499b0' }} domain={[0, 'auto']} />
                  <Tooltip contentStyle={{ background: '#0e1c2b', border: '1px solid #25384e', borderRadius: 8, fontSize: 12 }} />
                  <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="4 3" label={{ value: 'crush', fill: '#ef4444', fontSize: 10 }} />
                  <ReferenceLine y={3.5} stroke="#fb8c00" strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="density" stroke="#38bdf8" dot={false} strokeWidth={2.2} isAnimationActive={false} />
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
