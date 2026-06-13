import { useEffect, useMemo, useState } from 'react'
import StringLineChart, { TYPE_COLOR } from '../components/StringLineChart.jsx'
import { getCorridor, getM2Scenarios, runM2 } from '../api.js'

export default function M2Delays() {
  const [network, setNetwork] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [scenario, setScenario] = useState('passenger_ahead')
  const [optimize, setOptimize] = useState(false)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    getCorridor().then(setNetwork).catch((e) => setError(e.message))
    getM2Scenarios().then(setScenarios).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    let cancel = false
    setLoading(true); setError(null)
    runM2(scenario, true)
      .then((r) => { if (!cancel) { setResult(r); setLoading(false) } })
      .catch((e) => { if (!cancel) { setError(e.message); setLoading(false) } })
    return () => { cancel = true }
  }, [scenario])

  const scMeta = scenarios.find((s) => s.key === scenario)
  const active = result ? (optimize && result.optimized ? result.optimized : result.baseline) : null
  const impact = result?.impact

  // trains sorted by delay (worst first) for the table
  const trainRows = useMemo(() => {
    if (!active) return []
    const base = Object.fromEntries((result.baseline.trains || []).map((t) => [t.no, t]))
    return [...active.trains].sort((a, b) => b.delay_min - a.delay_min)
      .map((t) => ({ ...t, baseDelay: base[t.no]?.delay_min ?? 0 }))
  }, [active, result])

  const maxDelay = Math.max(60, ...(result?.baseline.trains || []).map((t) => t.delay_min))

  return (
    <div className="view">
      <div className="body">
        <aside className="sidebar">
          <section className="panel">
            <h3>Corridor</h3>
            <div className="card" style={{ padding: '12px 14px' }}>
              <div style={{ fontWeight: 800, color: 'var(--t0)', fontSize: 14 }}>{network?.corridor.name || 'New Delhi → Kanpur'}</div>
              <div className="muted small" style={{ marginTop: 4 }}>
                {network?.corridor.length_km} km · {network?.corridor.n_stations} stations · {network?.corridor.n_trains} trains
              </div>
            </div>
          </section>

          <section className="panel">
            <h3>Disruption scenario</h3>
            <select value={scenario} onChange={(e) => { setScenario(e.target.value); setOptimize(false) }}>
              {scenarios.map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
            </select>
            {scMeta && <p className="muted">{scMeta.description}</p>}
          </section>

          <section className="panel">
            <h3>Rescheduling</h3>
            <label className={`toggle ${optimize ? 'on' : ''}`}>
              <input type="checkbox" checked={optimize} onChange={(e) => setOptimize(e.target.checked)} />
              <div>
                <div className="tlabel">Run rescheduling optimizer</div>
                <div className="thint">Hold-and-overtake at loop stations to minimise total delay</div>
              </div>
            </label>
            {impact && optimize && (
              <div className="impact-chip" style={{ marginTop: 12, marginLeft: 0 }}>
                <div className="impact-num">−{Math.round(impact.saved_pct)}%</div>
                <div className="impact-lbl">
                  delay <b>{Math.round(impact.delay_before_min)}</b> → <b>{Math.round(impact.delay_after_min)}</b> min<br />
                  <b>{Math.round(impact.saved_min)}</b> delay-minutes saved · {impact.actions_count} moves
                </div>
              </div>
            )}
          </section>

          <section className="panel legend">
            <h3>Train type</h3>
            {Object.entries(TYPE_COLOR).slice(0, 7).map(([k, c]) => (
              <div className="legrow" key={k}><span className="swatch" style={{ background: c }} />{k.charAt(0) + k.slice(1).toLowerCase()}</div>
            ))}
          </section>
        </aside>

        <main className="stage">
          <div className="statusbar">
            <div className="status-chip" style={{ borderColor: optimize ? 'var(--good)' : 'var(--elev)', color: optimize ? 'var(--good)' : 'var(--elev)' }}>
              <span className="dot" style={{ background: optimize ? 'var(--good)' : 'var(--elev)' }} />
              {optimize ? 'RESCHEDULED' : 'NO ACTION (FCFS)'}
            </div>
            <Metric label="Total delay" value={active ? `${Math.round(active.total_delay_min)} min` : '—'} danger={active && active.total_delay_min > 100} good={active && active.total_delay_min < 20} />
            <Metric label="Trains delayed" value={active ? active.affected : '—'} danger={active && active.affected > 3} />
            <Metric label="Overtakes" value={optimize && active ? active.actions.length : '0'} />
            {result?.disruption && (
              <div className="src-chip warn" title="Primary disruption injected">
                <span className="src-dot" />DISRUPTION
                <span className="src-sub">{result.disruption.train} · {result.disruption.detail}</span>
              </div>
            )}
            {loading && <span className="loading">simulating…</span>}
            {error && <span className="error-chip" title={error}>⚠ {error}</span>}
          </div>

          <div className="m2wrap">
            {/* string-line diagram */}
            <div className="chart-title" style={{ padding: '2px 4px 8px' }}>
              Time–distance running chart
              <span style={{ color: optimize ? 'var(--good)' : 'var(--elev)', marginLeft: 8, fontWeight: 700 }}>
                {optimize ? '— rescheduled: overtakes fan the lines out' : '— no action: lines bunch behind the slow train (cascade)'}
              </span>
            </div>
            <div className="stringchart">
              {active && network && <StringLineChart stations={network.stations} trains={active.trains} />}
            </div>

            {/* train delay table */}
            <div className="grid two" style={{ marginTop: 16 }}>
              <div>
                <div className="chart-title">Per-train delay ({optimize ? 'rescheduled' : 'no action'})</div>
                <div className="card" style={{ padding: '6px 4px' }}>
                  {trainRows.map((t) => (
                    <div className="train-row" key={t.no}>
                      <div className="tname">
                        <span className="tbadge" style={{ background: (TYPE_COLOR[t.type] || '#38bdf8') + '33', color: TYPE_COLOR[t.type] || '#38bdf8' }}>{t.type.slice(0, 3)}</span>
                        {t.name}
                      </div>
                      <div className="faint small">{t.no}</div>
                      <div className="tbar">
                        <div className="tfill" style={{ width: `${Math.min(100, t.delay_min / maxDelay * 100)}%`, background: t.delay_min > 5 ? 'var(--bad)' : 'var(--good)' }} />
                      </div>
                      <div className="tdelay" style={{ color: t.delay_min > 5 ? '#ff8a8a' : 'var(--good)' }}>
                        {t.delay_min > 0.5 ? `+${Math.round(t.delay_min)}m` : 'on time'}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div className="chart-title">Rescheduling actions {optimize ? '' : '(enable optimizer)'}</div>
                <div className="actionsbox">
                  {optimize && active?.actions?.length ? dedupeActions(active.actions).map((a, i) => (
                    <div className="action-item" key={i}>
                      <b>Hold</b> {a.held_names.join(', ')} at <b>{a.station_name}</b> — <b>{a.overtaker_name}</b> overtakes
                    </div>
                  )) : <div className="muted small" style={{ padding: 10 }}>
                    {optimize ? 'No overtakes needed — corridor running clean.' : 'Enable the rescheduling optimizer to see hold-and-overtake moves that recover the delay.'}
                  </div>}
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

function dedupeActions(actions) {
  // collapse the per-section duplicates into a readable list (max ~8)
  const seen = new Set(); const out = []
  for (const a of actions) {
    const key = a.overtaker + '|' + a.held.join(',')
    if (seen.has(key)) continue
    seen.add(key); out.push(a)
    if (out.length >= 8) break
  }
  return out
}

function Metric({ label, value, danger, good }) {
  return (
    <div className={`metric ${danger ? 'danger' : ''} ${good ? 'good' : ''}`}>
      <div className="metric-val">{value}</div>
      <div className="metric-lbl">{label}</div>
    </div>
  )
}
