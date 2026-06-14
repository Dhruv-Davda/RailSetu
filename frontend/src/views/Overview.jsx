import { useEffect, useState } from 'react'
import { simulate, runM2, getKavachCorrelation } from '../api.js'
import { IconStation, IconTrain, IconShield, IconArrow } from '../icons.jsx'

// D2 — Japan vs India benchmark. Cited public figures (representative) kept
// alongside one live figure from our own M2 corridor run.
const BENCHMARKS = (corridorDelay) => [
  { label: 'Punctuality (on-time %)', unit: '%', max: 100,
    bars: [{ who: 'Japan', v: 99, c: 'var(--good)' }, { who: 'India', v: 75, c: 'var(--warn)' }] },
  { label: 'Avg delay / train', unit: ' min', max: Math.max(20, corridorDelay),
    bars: [{ who: 'Shinkansen', v: 1.6, c: 'var(--good)' }, { who: 'This corridor', v: corridorDelay, c: 'var(--bad)' }] },
]

const PROVENANCE = [
  { tier: 'REAL', c: '#2fa84f', def: 'Exact, sourced facts',
    eg: 'NDLS station geometry (OpenStreetMap) · the train list · festival dates' },
  { tier: 'MODELLED', c: '#f0a500', def: 'Computed by our algorithms, against our own baseline — not ground-truth validated',
    eg: 'Crowd densities · delay cascades · delay-minutes saved' },
  { tier: 'INDICATIVE', c: '#e07b00', def: 'Directionally sound on coarse public data; specific numbers are soft',
    eg: 'Kavach coverage % · gap × accident correlation' },
  { tier: 'ESTIMATED', c: '#8a857e', def: 'Derived where the source gives no number',
    eg: 'Passenger load and platform from the live arrivals feed' },
]

const MODULES = [
  { key: 'm1', id: 'M1', Ico: IconStation, title: 'Station Crowd-Flow', desc: 'Predicts dangerous station crowding and prevents stampedes — modelled on Shinjuku crowd-flow engineering.' },
  { key: 'm2', id: 'M2', Ico: IconTrain, title: 'Delay & Rescheduling', desc: 'Propagates a disruption across the corridor and reschedules trains to recover delay — Shinkansen-style control.' },
  { key: 'm6', id: 'M6', Ico: IconShield, title: 'Kavach Gap Analysis', desc: 'Maps where automatic train protection is missing and where the gap is most dangerous.' },
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
          <div className="flag">JPN &rarr; IND</div>
          <div className="lbl">Proven in Japan<br />adapted for India</div>
        </div>
      </div>

      <div className="grid cards">
        {MODULES.map((m) => {
          const s = stats[m.key]
          return (
            <div className="modcard" key={m.key} onClick={() => onOpen(m.key)}>
              <span className="mc-go"><IconArrow width={16} height={16} /></span>
              <div className="mc-top">
                <div className="mc-ico"><m.Ico width={17} height={17} /></div>
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

      <div className="grid three">
        {/* D1 — cross-module incident timeline */}
        <div className="ov-pane">
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
        <div className="ov-pane">
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

        {/* Every figure in the platform carries one of four provenance tiers.
            Kept on screen rather than buried in the README — overclaiming is the
            fastest way to lose a technical audience. */}
        <div className="ov-pane">
          <div className="section-label">Data provenance</div>
          <div className="prov">
            {PROVENANCE.map((p) => (
              <div className="prov-row" key={p.tier}>
                <span className="prov-tier" style={{ color: p.c, borderColor: p.c }}>{p.tier}</span>
                <div>
                  <div className="prov-def">{p.def}</div>
                  <div className="prov-eg">{p.eg}</div>
                </div>
              </div>
            ))}
          </div>
          <p className="muted small">
            Aggregate density only — never identifiable individuals. No live signalling
            integration and no trackside hardware: this is decision support, to be
            calibrated against site data before any real deployment.
          </p>
        </div>
      </div>
    </div>
  )
}

function buildTimeline(m1, m2, m6) {
  const t = []
  const M = {
    M1: { bg: 'rgba(240,165,0,.16)', c: '#f0a500' },
    M2: { bg: 'rgba(47,168,79,.16)', c: '#2fa84f' },
    M6: { bg: 'rgba(229,72,77,.16)', c: '#e5484d' },
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
