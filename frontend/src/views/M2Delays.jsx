import { useEffect, useMemo, useRef, useState } from 'react'
import StringLineChart, { TYPE_COLOR, timeRange } from '../components/StringLineChart.jsx'
import { getCorridor, getM2Scenarios, runM2 } from '../api.js'

const lerp = (a, b, p) => a + (b - a) * p
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

export default function M2Delays() {
  const [network, setNetwork] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [scenario, setScenario] = useState('passenger_ahead')
  const [optimize, setOptimize] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const [morph, setMorph] = useState(0)        // 0 = no action, 1 = rescheduled
  const [playhead, setPlayhead] = useState(null)
  const [playing, setPlaying] = useState(false)
  const raf = useRef(0)
  const playRaf = useRef(0)
  const morphRef = useRef(0)

  useEffect(() => {
    getCorridor().then(setNetwork).catch((e) => setError(e.message))
    getM2Scenarios().then(setScenarios).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    let cancel = false
    setError(null)
    runM2(scenario, true)
      .then((r) => { if (!cancel) { setResult(r); setMorph(0); setOptimize(false) } })
      .catch((e) => { if (!cancel) setError(e.message) })
    return () => { cancel = true }
  }, [scenario])

  // Animate the morph between no-action and rescheduled whenever the toggle flips.
  useEffect(() => {
    cancelAnimationFrame(raf.current)
    const from = morphRef.current, to = optimize ? 1 : 0
    const dur = 1100, t0 = performance.now()
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / dur)
      const v = from + (to - from) * easeInOut(p)
      setMorph(v); morphRef.current = v
      if (p < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimize])
  useEffect(() => { morphRef.current = morph }, [morph])

  const range = useMemo(
    () => (result ? timeRange(result.baseline.trains, result.optimized?.trains) : [0, 60]),
    [result])

  function play() {
    cancelAnimationFrame(playRaf.current)
    setPlaying(true)
    const [t0v, t1v] = range, dur = 7000, start = performance.now()
    const tick = (now) => {
      const p = (now - start) / dur
      if (p >= 1) { setPlayhead(null); setPlaying(false); return }
      setPlayhead(lerp(t0v, t1v, p))
      playRaf.current = requestAnimationFrame(tick)
    }
    playRaf.current = requestAnimationFrame(tick)
  }
  useEffect(() => () => { cancelAnimationFrame(raf.current); cancelAnimationFrame(playRaf.current) }, [])

  const scMeta = scenarios.find((s) => s.key === scenario)
  const b = result?.baseline, o = result?.optimized
  const impact = result?.impact

  // metrics interpolate with the morph for a live count-down feel
  const curDelay = b ? lerp(b.total_delay_min, o?.total_delay_min ?? b.total_delay_min, morph) : 0
  const curAffected = b ? Math.round(lerp(b.affected, o?.affected ?? b.affected, morph)) : 0
  const overtakes = o && morph > 0.5 ? o.actions.length : 0
  const saved = b ? b.total_delay_min - curDelay : 0
  const savedPct = b && b.total_delay_min ? (saved / b.total_delay_min) * 100 : 0
  const reschedeled = morph > 0.5

  const baseByNo = useMemo(() => Object.fromEntries((b?.trains || []).map((t) => [t.no, t])), [b])
  const trainRows = useMemo(() => {
    if (!b) return []
    const src = o?.trains || b.trains
    return [...src].map((t) => ({ ...t, curDelay: lerp(baseByNo[t.no]?.delay_min ?? t.delay_min, t.delay_min, morph) }))
      .sort((x, y) => y.curDelay - x.curDelay)
  }, [b, o, morph, baseByNo])
  const maxDelay = Math.max(60, ...(b?.trains || []).map((t) => t.delay_min))

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
            <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {scenarios.map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
            </select>
            {scMeta && <p className="muted">{scMeta.description}</p>}
          </section>

          <section className="panel">
            <h3>Rescheduling</h3>
            <button className={`btn full ${optimize ? '' : 'primary'}`} onClick={() => setOptimize((v) => !v)}>
              {optimize ? '↺ Revert to no-action' : '⚡ Run rescheduling optimizer'}
            </button>
            <button className="btn ghost full" style={{ marginTop: 8 }} onClick={play} disabled={playing}>
              {playing ? '▶ running…' : '▶ Play trains through corridor'}
            </button>
            {impact && (
              <div className="impact-chip" style={{ marginTop: 12, marginLeft: 0, opacity: morph > 0.05 ? 1 : 0.4, transition: 'opacity .3s' }}>
                <div className="impact-num">−{Math.round(savedPct)}%</div>
                <div className="impact-lbl">
                  delay <b>{Math.round(b?.total_delay_min || 0)}</b> → <b>{Math.round(curDelay)}</b> min<br />
                  <b>{Math.round(saved)}</b> delay-minutes saved · {overtakes} moves
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
            <div className="status-chip" style={{ borderColor: reschedeled ? 'var(--good)' : 'var(--elev)', color: reschedeled ? 'var(--good)' : 'var(--elev)' }}>
              <span className="dot" style={{ background: reschedeled ? 'var(--good)' : 'var(--elev)' }} />
              {reschedeled ? 'RESCHEDULED' : 'NO ACTION (FCFS)'}
            </div>
            <Metric label="Total delay" value={`${Math.round(curDelay)} min`} danger={curDelay > 100} good={curDelay < 20} />
            <Metric label="Trains delayed" value={curAffected} danger={curAffected > 3} good={curAffected <= 1} />
            <Metric label="Overtakes" value={overtakes} />
            {result?.disruption && (
              <div className="src-chip warn" title="Primary disruption injected">
                <span className="src-dot" />DISRUPTION
                <span className="src-sub">{result.disruption.train} · {result.disruption.detail}</span>
              </div>
            )}
            {error && <span className="error-chip" title={error}>⚠ {error}</span>}
          </div>

          <div className="m2wrap">
            <div className="chart-title" style={{ padding: '2px 4px 8px' }}>
              Time–distance running chart
              <span style={{ color: reschedeled ? 'var(--good)' : 'var(--elev)', marginLeft: 8, fontWeight: 700 }}>
                {reschedeled ? '— rescheduled: overtakes fan the lines out' : '— no action: lines bunch behind the slow train (cascade)'}
              </span>
            </div>
            <div className="stringchart">
              {b && network && (
                <StringLineChart stations={network.stations} baseline={b.trains}
                  optimized={o?.trains} progress={morph} playhead={playhead} />
              )}
            </div>

            <div className="grid two" style={{ marginTop: 16 }}>
              <div>
                <div className="chart-title">Per-train delay</div>
                <div className="card" style={{ padding: '6px 4px' }}>
                  {trainRows.map((t) => (
                    <div className="train-row" key={t.no}>
                      <div className="tname">
                        <span className="tbadge" style={{ background: (TYPE_COLOR[t.type] || '#38bdf8') + '33', color: TYPE_COLOR[t.type] || '#38bdf8' }}>{t.type.slice(0, 3)}</span>
                        {t.name}
                      </div>
                      <div className="faint small">{t.no}</div>
                      <div className="tbar">
                        <div className="tfill" style={{ width: `${Math.min(100, t.curDelay / maxDelay * 100)}%`, background: t.curDelay > 5 ? 'var(--bad)' : 'var(--good)', transition: 'width .1s linear' }} />
                      </div>
                      <div className="tdelay" style={{ color: t.curDelay > 5 ? '#ff8a8a' : 'var(--good)' }}>
                        {t.curDelay > 0.5 ? `+${Math.round(t.curDelay)}m` : 'on time'}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div className="chart-title">Rescheduling actions</div>
                <div className="actionsbox">
                  {reschedeled && o?.actions?.length ? dedupeActions(o.actions).map((a, i) => (
                    <div className="action-item" key={i}>
                      <b>Hold</b> {a.held_names.join(', ')} at <b>{a.station_name}</b> — <b>{a.overtaker_name}</b> overtakes
                    </div>
                  )) : (
                    <div className="muted small" style={{ padding: 10 }}>
                      {!o?.actions?.length
                        ? 'No overtakes needed — corridor running clean.'
                        : 'Run the rescheduling optimizer to see the hold-and-overtake moves that recover the delay.'}
                    </div>
                  )}
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
