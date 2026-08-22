import { useEffect, useState } from 'react'
import { getHealth } from './api.js'
import Overview from './views/Overview.jsx'
import M1Crowd from './views/M1Crowd.jsx'
import M2Delays from './views/M2Delays.jsx'
import M6Kavach from './views/M6Kavach.jsx'
import M3Defect from './views/M3Defect.jsx'
import { IconPanel, IconStation, IconTrain, IconShield, IconScan } from './icons.jsx'

const TABS = [
  { key: 'overview', Ico: IconPanel, label: 'Overview' },
  { key: 'm1', Ico: IconStation, label: 'Crowd-Flow', tag: 'M1' },
  { key: 'm2', Ico: IconTrain, label: 'Delays', tag: 'M2' },
  { key: 'm6', Ico: IconShield, label: 'Kavach', tag: 'M6' },
  { key: 'm3', Ico: IconScan, label: 'Defects', tag: 'M3' },
]

// Indian Standard Time, independent of where the machine running the demo is.
function istNow() {
  return new Date(Date.now() + (330 + new Date().getTimezoneOffset()) * 60000)
}

function Clock() {
  const [t, setT] = useState(istNow)
  useEffect(() => {
    const id = setInterval(() => setT(istNow()), 1000)
    return () => clearInterval(id)
  }, [])
  const p = (n) => String(n).padStart(2, '0')
  return (
    <div className="clock">
      <div className="ctime">{p(t.getHours())}:{p(t.getMinutes())}:{p(t.getSeconds())}</div>
      <div className="czone">IST</div>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('overview')
  const [health, setHealth] = useState(null)

  useEffect(() => { getHealth().then(setHealth).catch(() => setHealth(null)) }, [])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          {/* Station code plate, as on platform signage */}
          <div className="mark">RS</div>
          <div>
            <div className="name">RailSetu</div>
            <div className="by">Railway Intelligence Platform</div>
          </div>
        </div>
        <nav className="nav">
          {TABS.map(({ key, Ico, label, tag }) => (
            <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
              <span className="ico"><Ico width={16} height={16} /></span>
              <span>{label}</span>
              {tag && <span className="tag">{tag}</span>}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <div className="health">
          <span className="pip" style={{ background: health ? 'var(--good)' : 'var(--bad)' }} />
          {health ? `${health.station} · live` : 'backend offline'}
        </div>
        <Clock />
      </header>

      {tab === 'overview' && <Overview onOpen={setTab} />}
      {tab === 'm1' && <M1Crowd />}
      {tab === 'm2' && <M2Delays />}
      {tab === 'm6' && <M6Kavach />}
      {tab === 'm3' && <M3Defect />}
    </div>
  )
}
