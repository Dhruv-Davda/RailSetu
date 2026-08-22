/*
 * The identity control in the top bar.
 *
 * Signed out it is an address field and a Sign in button. Signed in it becomes
 * the person: their initials, their address, and a way out. That address is
 * what every policy change is recorded against, so it is kept visible rather
 * than tucked behind a menu — you should always be able to see who the
 * platform currently thinks you are before you change a rule.
 */
import { useState } from 'react'

function initials(name = '', email = '') {
  const src = (name || email || '').trim()
  const parts = src.split(/[\s._@-]+/).filter(Boolean)
  if (!parts.length) return '??'
  return ((parts[0][0] || '') + (parts.length > 1 ? parts[1][0] : '')).toUpperCase()
}

export default function SignIn({ account, onSignIn, onSignOut, busy, error }) {
  const [email, setEmail] = useState('')
  const valid = /\S+@\S+\.\S+/.test(email.trim())

  function submit(e) {
    e?.preventDefault()
    if (valid && !busy) onSignIn(email.trim())
  }

  if (account) {
    return (
      <div className="si signed">
        <span className="si-av" title={account.email}>
          {initials(account.display_name, account.email)}
        </span>
        <span className="si-who">
          <span className="si-name">{account.display_name}</span>
          <span className="si-mail">{account.email}</span>
        </span>
        <button className="si-out" onClick={onSignOut} disabled={busy} title="Sign out">
          {busy ? '…' : 'Sign out'}
        </button>
      </div>
    )
  }

  return (
    <form className={`si ${error ? 'err' : ''}`} onSubmit={submit}>
      <input
        className="si-input"
        type="email"
        value={email}
        placeholder="you@railsetu.in"
        aria-label="Email address"
        autoComplete="email"
        onChange={(e) => setEmail(e.target.value)}
      />
      <button className="si-in" type="submit" disabled={!valid || busy}>
        {busy ? 'Signing in…' : 'Sign in'}
      </button>
      {error && <span className="si-err" title={error}>{error}</span>}
    </form>
  )
}
