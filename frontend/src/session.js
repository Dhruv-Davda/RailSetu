/*
 * Who is using the platform, from the browser's point of view.
 *
 * The signed-in address is kept here and sent on every request that needs an
 * identity. The server is the authority — it decides whether an address is
 * known and refuses the policy surface otherwise — so this module only
 * remembers a choice, it never grants access.
 */
const KEY = 'railsetu.session.email'

export function currentEmail() {
  try { return localStorage.getItem(KEY) || null } catch { return null }
}

export function rememberEmail(email) {
  try { localStorage.setItem(KEY, email) } catch { /* private mode */ }
}

export function forgetEmail() {
  try { localStorage.removeItem(KEY) } catch { /* ignore */ }
}

/** Identity header for requests that must be attributable. */
export function authHeaders() {
  const e = currentEmail()
  return e ? { 'X-RailSetu-User': e } : {}
}
