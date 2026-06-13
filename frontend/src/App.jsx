import { useEffect, useState } from 'react'
import { getHealth } from './api.js'
import Overview from './views/Overview.jsx'
import M1Crowd from './views/M1Crowd.jsx'
import M2Delays from './views/M2Delays.jsx'
import M6Kavach from './views/M6Kavach.jsx'

const TABS = [
  { key: 'overview', ico: '◎', label: 'Overview' },
  { key: 'm1', ico: '🚉', label: 'Crowd-Flow', tag: 'M1' },
  { key: 'm2', ico: '🚆', label: 'Delays', tag: 'M2' },
  { key: 'm6', ico: '🛡', label: 'Kavach', tag: 'M6' },
]

export default function App() {
  const [tab, setTab] = useState('overview')
  const [health, setHealth] = useState(null)

  useEffect(() => { getHealth().then(setHealth).catch(() => setHealth(null)) }, [])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="mark">🚉</div>
          <div>
            <div className="name">RailSetu</div>
            <div className="by">Indian Railway Intelligence Platform</div>
          </div>
        </div>
        <nav className="nav">
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? 'active' : ''} onClick={() => setTab(t.key)}>
              <span className="ico">{t.ico}</span>
              <span>{t.label}</span>
              {t.tag && <span className="tag">{t.tag}</span>}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <div className="health">
          <span className="pip" style={{ background: health ? 'var(--good)' : 'var(--bad)' }} />
          {health ? `${health.station} · backend live` : 'backend offline'}
        </div>
      </header>

      {tab === 'overview' && <Overview onOpen={setTab} />}
      {tab === 'm1' && <M1Crowd />}
      {tab === 'm2' && <M2Delays />}
      {tab === 'm6' && <M6Kavach />}
    </div>
  )
}
