import { useEffect, useState } from 'react'
import IndiaMap, { STATUS_COLOR } from '../components/IndiaMap.jsx'
import { getKavach, getKavachCorrelation } from '../api.js'

export default function M6Kavach() {
  const [coverage, setCoverage] = useState(null)
  const [corr, setCorr] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getKavach().then(setCoverage).catch((e) => setError(e.message))
    getKavachCorrelation().then(setCorr).catch((e) => setError(e.message))
  }, [])

  const sum = coverage?.summary

  return (
    <div className="view">
      <div className="body">
        <aside className="sidebar">
          <section className="panel">
            <h3>What this is</h3>
            <p className="muted">
              A planning tool that maps where <b>Kavach</b> (India's automatic train-collision
              system) is missing and where that gap is most dangerous. It does <b>not</b> control
              trains — it tells planners where to install Kavach first.
            </p>
          </section>

          <section className="panel">
            <h3>National coverage</h3>
            <div className="card">
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <div style={{ fontSize: 30, fontWeight: 900, color: 'var(--warn)' }}>{sum?.traffic_weighted_coverage_pct ?? '—'}%</div>
                <div className="muted small">traffic-weighted<br />coverage</div>
              </div>
              <div style={{ display: 'flex', gap: 14, marginTop: 12 }}>
                <Stat n={sum?.status_counts.equipped} c="var(--good)" l="equipped" />
                <Stat n={sum?.status_counts.partial} c="var(--warn)" l="partial" />
                <Stat n={sum?.status_counts.none} c="var(--bad)" l="none" />
              </div>
            </div>
          </section>

          <section className="panel legend">
            <h3>Kavach status</h3>
            {Object.entries(STATUS_COLOR).map(([k, c]) => (
              <div className="legrow" key={k}><span className="swatch" style={{ background: c }} />{k} ({k === 'equipped' ? '≥75%' : k === 'partial' ? '25–75%' : '<25%'})</div>
            ))}
            <p className="muted small">Line thickness = daily train traffic.</p>
          </section>
        </aside>

        <main className="stage">
          <div className="statusbar">
            <div className="status-chip" style={{ borderColor: 'var(--warn)', color: 'var(--warn)' }}>
              <span className="dot" style={{ background: 'var(--warn)' }} />KAVACH GAP ANALYSIS
            </div>
            <div className="src-chip" title="Indicative — representative public data"><span className="src-dot" />INDICATIVE</div>
            <Metric label="Corridors mapped" value={sum?.n_corridors ?? '—'} />
            <Metric label="Daily trains" value={sum?.total_daily_trains?.toLocaleString() ?? '—'} />
            {error && <span className="error-chip" title={error}>⚠ {error}</span>}
          </div>

          <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
            <IndiaMap coverage={coverage} />
            <div style={{ width: 380, flexShrink: 0, padding: 16, overflowY: 'auto', borderLeft: '1px solid var(--border)', background: 'var(--bg-2)' }}>
              {corr && (
                <>
                  <div className="policy-headline">
                    <div className="ph-num">{corr.headline.risk_share_pct}%</div>
                    <div className="ph-txt">{corr.headline.text}</div>
                  </div>

                  <div className="chart-title">Coverage ↔ incidents (indicative)</div>
                  <div className="card" style={{ marginBottom: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-around', textAlign: 'center' }}>
                      <div>
                        <div style={{ fontSize: 24, fontWeight: 900, color: 'var(--bad)' }}>{corr.incident_comparison.low_coverage_avg_incidents}</div>
                        <div className="muted small">avg incidents<br />low coverage</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 24, fontWeight: 900, color: 'var(--good)' }}>{corr.incident_comparison.high_coverage_avg_incidents}</div>
                        <div className="muted small">avg incidents<br />high coverage</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 24, fontWeight: 900, color: 'var(--accent)' }}>{corr.incident_comparison.pearson_kavach_vs_incidents}</div>
                        <div className="muted small">correlation<br />(coverage·incidents)</div>
                      </div>
                    </div>
                  </div>

                  <div className="chart-title">Highest-risk unequipped corridors</div>
                  {corr.top_unequipped.map((c) => (
                    <div className="kv-row" key={c.id}>
                      <div className="kvname">{c.name}</div>
                      <div className="kvbar"><div className="f" style={{ width: `${c.kavach_pct}%`, background: c.kavach_pct < 25 ? 'var(--bad)' : 'var(--warn)' }} /></div>
                      <div className="kvpct" style={{ color: c.kavach_pct < 25 ? '#ff8a8a' : 'var(--warn)' }}>{c.kavach_pct}%</div>
                    </div>
                  ))}
                  <p className="disclaimer">{corr.disclaimer}</p>
                </>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

function Stat({ n, c, l }) {
  return <div style={{ textAlign: 'center' }}>
    <div style={{ fontSize: 20, fontWeight: 900, color: c }}>{n ?? '—'}</div>
    <div className="muted small">{l}</div>
  </div>
}
function Metric({ label, value }) {
  return <div className="metric"><div className="metric-val">{value}</div><div className="metric-lbl">{label}</div></div>
}
