import { useEffect, useState } from 'react'
import { simulate, runM2, getKavachCorrelation } from '../api.js'

// D2 — Japan vs India benchmark. Cited public figures (representative) kept
// alongside one live figure from our own M2 corridor run.
const BENCHMARKS = (corridorDelay) => [
  { label: 'Punctuality (on-time %)', unit: '%', max: 100,
    bars: [{ who: 'Japan', v: 99, c: 'var(--good)' }, { who: 'India', v: 75, c: 'var(--warn)' }] },
  { label: 'Avg delay / train', unit: ' min', max: Math.max(20, corridorDelay),
    bars: [{ who: 'Shinkansen', v: 1.6, c: 'var(--good)' }, { who: 'This corridor', v: corridorDelay, c: 'var(--bad)' }] },
]

const MODULES = [
  { key: 'm1', id: 'M1', ico: '🚉', title: 'Station Crowd-Flow', desc: 'Predicts dangerous station crowding and prevents stampedes — modelled on Shinjuku crowd-flow engineering.' },
  { key: 'm2', id: 'M2', ico: '🚆', title: 'Delay & Rescheduling', desc: 'Propagates a disruption across the corridor and reschedules trains to recover delay — Shinkansen-style control.' },
  { key: 'm6', id: 'M6', ico: '🛡', title: 'Kavach Gap Analysis', desc: 'Maps where automatic train protection is missing and where the gap is most dangerous.' },
]

export default function Overview({ onOpen }) {
  const [m1, setM1] = useState(null)
  const [m2, setM2] = useState(null)
  const [m6, setM6] = useState(null)

  useEffect(() => {
    simulate('kumbh_surge', {}).then(setM1).catch(() => {})
    runM2('passenger_ahead', true).then(setM2).catch(() => {})
    getKavachCorrelation().then(setM6).catch(() => {})
  }, [])

  const corridorDelay = m2 ? Math.round(m2.baseline.total_delay_min / m2.baseline.trains.length) : 12

  const stats = {
    m1: m1 ? { v: m1.summary.peak_density, k: 'p/m² peak · ' + m1.summary.crush_count + ' crush pts', crit: m1.summary.crush_count > 0 } : null,
    m2: m2 ? { v: Math.round(m2.impact.saved_min), k: 'delay-min saved (' + Math.round(m2.impact.saved_pct) + '%)', crit: false } : null,
    m6: m6 ? { v: m6.headline.risk_share_pct + '%', k: 'of risk on ' + m6.headline.n_corridors + ' unequipped corridors', crit: true } : null,
  }

  const timeline = buildTimeline(m1, m2, m6)

  return (
    <div className="overview">
      <div className="hero">
        <div className="htext">
          <h1>One platform. Indian problems, Japanese solutions.</h1>
          <p>RailSetu transplants the methods that made Japan the global benchmark for rail safety and punctuality — crowd-flow engineering, systematic rescheduling, automatic train protection — and adapts each for India's scale. Two real algorithm cores and a policy layer, on one shared backbone.</p>
        </div>
        <div className="hjapan">
          <div className="flag">🇯🇵 → 🇮🇳</div>
          <div className="lbl">Proven in Japan, adapted for India</div>
        </div>
      </div>

      <div className="grid cards" style={{ marginBottom: 22 }}>
        {MODULES.map((m) => {
          const s = stats[m.key]
          return (
            <div className="modcard" key={m.key} onClick={() => onOpen(m.key)}>
              <span className="mc-go">→</span>
              <div className="mc-top">
                <div className="mc-ico">{m.ico}</div>
                <div>
                  <div className="mc-id">{m.id}</div>
                  <h3>{m.title}</h3>
                </div>
              </div>
              <p>{m.desc}</p>
              {s ? (
                <div className="mc-stat">
                  <span className="v" style={{ color: s.crit ? '#ff8a8a' : 'var(--good)' }}>{s.v}</span>
                  <span className="k">{s.k}</span>
                </div>
              ) : <div className="mc-stat"><span className="k">loading…</span></div>}
            </div>
          )
        })}
      </div>

      <div className="grid two">
        {/* D1 — cross-module incident timeline */}
        <div className="card">
          <div className="section-label">Cross-module incident timeline</div>
          <div className="timeline">
            {timeline.map((e, i) => (
              <div className="tl-item" key={i}>
                <div className="tl-time">{e.time}</div>
                <div className="tl-dot" style={{ background: e.color, boxShadow: `0 0 8px ${e.color}` }} />
                <div className="tl-body">
                  <span className="tl-mod" style={{ background: e.modBg, color: e.modColor }}>{e.mod}</span>
                  {e.text}
                </div>
              </div>
            ))}
          </div>
          <p className="muted small">Events stream from M1, M2 and M6 into one feed — the shared backbone, made visible.</p>
        </div>

        {/* D2 — Japan vs India benchmark */}
        <div className="card">
          <div className="section-label">Japan vs. India benchmark</div>
          {BENCHMARKS(corridorDelay).map((b, i) => (
            <div className="bench-row" key={i}>
              <div className="blbl">{b.label}</div>
              <div className="bench-bars">
                {b.bars.map((bar, j) => (
                  <div className="bench-bar" key={j}>
                    <div className="who">{bar.who}</div>
                    <div className="track"><div className="fill" style={{ width: `${Math.min(100, bar.v / b.max * 100)}%`, background: bar.c }} /></div>
                    <div className="val">{bar.v}{b.unit}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          <p className="muted small">Japan figures are cited public benchmarks; "this corridor" is from the live M2 model. Keeps the Japan framing on-screen, not just in slides.</p>
        </div>
      </div>
    </div>
  )
}

function buildTimeline(m1, m2, m6) {
  const t = []
  const M = {
    M1: { bg: 'rgba(56,189,248,.18)', c: '#38bdf8' },
    M2: { bg: 'rgba(34,211,238,.18)', c: '#22d3ee' },
    M6: { bg: 'rgba(255,192,46,.18)', c: '#ffc02e' },
  }
  if (m1) {
    t.push({ time: '18:42', color: 'var(--bad)', mod: 'M1', modBg: M.M1.bg, modColor: M.M1.c,
      text: `CRITICAL — crowd crush forming at the Platform 14/15 foot-over-bridge (${m1.summary.peak_density} p/m², ${m1.summary.crush_count} crush points).` })
    t.push({ time: '18:43', color: 'var(--good)', mod: 'M1', modBg: M.M1.bg, modColor: M.M1.c,
      text: 'Recommended metered holding — projected to clear the crush to a safe density.' })
  }
  if (m2) {
    t.push({ time: '18:55', color: 'var(--elev)', mod: 'M2', modBg: M.M2.bg, modColor: M.M2.c,
      text: `Slow passenger train pathed ahead of the express fleet — cascade building (${Math.round(m2.baseline.total_delay_min)} delay-min, ${m2.baseline.affected} trains).` })
    t.push({ time: '18:57', color: 'var(--good)', mod: 'M2', modBg: M.M2.bg, modColor: M.M2.c,
      text: `Rescheduling applied — ${m2.impact.actions_count} hold-and-overtake moves recover ${Math.round(m2.impact.saved_min)} delay-minutes (${Math.round(m2.impact.saved_pct)}%).` })
  }
  if (m6) {
    t.push({ time: '19:10', color: 'var(--warn)', mod: 'M6', modBg: M.M6.bg, modColor: M.M6.c,
      text: m6.headline.text })
  }
  return t
}
