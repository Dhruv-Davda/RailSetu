import { useCallback, useEffect, useState } from 'react'
import { getHealth, getSession, signIn as apiSignIn, signOut as apiSignOut } from './api.js'
import SignIn from './components/SignIn.jsx'
import { currentEmail, forgetEmail, rememberEmail } from './session.js'
import Overview from './views/Overview.jsx'
import M1Crowd from './views/M1Crowd.jsx'
import M2Delays from './views/M2Delays.jsx'
import M6Kavach from './views/M6Kavach.jsx'
import Policy from './views/Policy.jsx'
import M3Defect from './views/M3Defect.jsx'
import {
  IconPanel, IconStation, IconTrain, IconShield, IconScan, IconPolicy,
} from './icons.jsx'

// No module-number chips: those labels belong to the project's own paperwork,
// not to the people using the platform. A duty officer opens "Defects", not M3.
const TABS = [
  { key: 'overview', Ico: IconPanel, label: 'Overview' },
  { key: 'm1', Ico: IconStation, label: 'Crowd-Flow' },
  { key: 'm2', Ico: IconTrain, label: 'Delays' },
  { key: 'm6', Ico: IconShield, label: 'Kavach' },
  { key: 'm3', Ico: IconScan, label: 'Defects' },
  { key: 'policy', Ico: IconPolicy, label: 'Policy', needsUser: true },
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

/* Shown in place of the policy register when nobody is signed in. */
function SignInRequired({ onSignIn, busy, error }) {
  const [email, setEmail] = useState('')
  const valid = /\S+@\S+\.\S+/.test(email.trim())
  return (
    <div className="gate">
      <div className="gate-card">
        <div className="gate-ico"><IconPolicy width={26} height={26} /></div>
        <h2>Sign in to open the operating policy</h2>
        <p>
          The policy register records who changed which rule, and when. That only
          works if the platform knows who you are, so this section is closed until
          you sign in.
        </p>
        <form className="gate-form" onSubmit={(e) => { e.preventDefault(); if (valid && !busy) onSignIn(email.trim()) }}>
          <input type="email" value={email} autoFocus placeholder="you@railsetu.in"
            aria-label="Email address" onChange={(e) => setEmail(e.target.value)} />
          <button className="gh-btn primary" type="submit" disabled={!valid || busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        {error && <p className="gate-err">{error}</p>}
        <p className="gate-note">
          Your address becomes your identity on every change you make. Anyone
          reading the history later will see it against your edits.
        </p>
      </div>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('overview')
  const [health, setHealth] = useState(null)
  const [account, setAccount] = useState(null)
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState(null)

  useEffect(() => { getHealth().then(setHealth).catch(() => setHealth(null)) }, [])

  // Restore a session on load. The address is remembered locally, but the
  // server decides whether it is still a known account.
  //
  // A FAILED check is not a signed-out user. Treating a transient error as a
  // sign-out silently dropped people mid-session — their next policy request
  // then went out with no identity and came back 401. Only an explicit "no
  // such account" clears the stored address; a network blip leaves it alone,
  // and the server still refuses anything it should refuse.
  useEffect(() => {
    if (!currentEmail()) return
    getSession()
      .then((a) => { if (a) setAccount(a); else forgetEmail() })
      .catch(() => { /* transient — keep the session, the server still gates each call */ })
  }, [])

  const onSignIn = useCallback(async (email) => {
    setAuthBusy(true); setAuthError(null)
    try {
      rememberEmail(email)              // set first: the call itself is attributed
      const { account: a } = await apiSignIn(email)
      setAccount(a)
    } catch (e) {
      forgetEmail()
      setAuthError(e.message.replace(/^API \d+ on \/session — /, ''))
    } finally { setAuthBusy(false) }
  }, [])

  const onSignOut = useCallback(async () => {
    setAuthBusy(true)
    try { await apiSignOut() } catch { /* the local session goes either way */ }
    forgetEmail(); setAccount(null); setAuthError(null); setAuthBusy(false)
    setTab((t) => (TABS.find((x) => x.key === t)?.needsUser ? 'overview' : t))
  }, [])

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
          {TABS.map(({ key, Ico, label }) => (
            <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
              <span className="ico"><Ico width={16} height={16} /></span>
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <div className="health">
          <span className="pip" style={{ background: health ? 'var(--good)' : 'var(--bad)' }} />
          {health ? `${health.station} · live` : 'backend offline'}
        </div>
        <SignIn account={account} onSignIn={onSignIn} onSignOut={onSignOut}
          busy={authBusy} error={authError} />
        <Clock />
      </header>

      {tab === 'overview' && <Overview onOpen={setTab} />}
      {tab === 'm1' && <M1Crowd />}
      {tab === 'm2' && <M2Delays />}
      {tab === 'm6' && <M6Kavach />}
      {tab === 'm3' && <M3Defect />}
      {tab === 'policy' && (account
        ? <Policy account={account} />
        : <SignInRequired onSignIn={onSignIn} busy={authBusy} error={authError} />)}
    </div>
  )
}
