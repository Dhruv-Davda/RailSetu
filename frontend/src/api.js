import { authHeaders } from './session.js'

const BASE = '/api'

// Single fetch wrapper: always checks response.ok and surfaces a useful error,
// so a backend outage/500 becomes a caught rejection (handled by callers) rather
// than a half-parsed error body that crashes the UI downstream.
async function getJSON(path, opts = {}) {
  let r
  try {
    // The identity header rides on every call; endpoints that do not need one
    // simply ignore it, and the policy surface refuses the request without it.
    r = await fetch(`${BASE}${path}`, {
      ...opts,
      headers: { ...(opts.headers || {}), ...authHeaders() },
    })
  } catch (e) {
    throw new Error(`Network error reaching ${path} — is the backend running?`)
  }
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).detail ?? '' } catch { /* non-JSON body */ }
    // A conflict comes back as a structured object, not a sentence. Attach it
    // so the caller can render the clashing blocks instead of "[object Object]".
    const text = typeof detail === 'string' ? detail : (detail?.message || '')
    const err = new Error(`API ${r.status} on ${path}${text ? ` — ${text}` : ''}`)
    err.status = r.status
    err.detail = detail
    throw err
  }
  return r.json()
}

function postJSON(path, body) {
  return getJSON(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const getHealth = () => getJSON('/health')
export const getStation = () => getJSON('/station')
export const getScenarios = () => getJSON('/scenarios').then((d) => d.scenarios)
export const simulate = (scenario, mitigations) => postJSON('/simulate', { scenario, mitigations })
export const whatif = (scenario, mitigations) => postJSON('/whatif', { scenario, mitigations })
// M1.4 — exhaustive mitigation search + AI-written operator brief
export const optimizeCrowd = (scenario, explain = true) =>
  postJSON('/optimize', { scenario, explain })

// M2 — Delay propagation & rescheduling
export const getCorridor = () => getJSON('/m2/network')
export const getM2Scenarios = () => getJSON('/m2/scenarios').then((d) => d.scenarios)
export const runM2 = (scenario, optimize) => postJSON('/m2/simulate', { scenario, optimize })

// M6 — Kavach gap analysis
export const getKavach = () => getJSON('/m6/coverage')
export const getKavachCorrelation = () => getJSON('/m6/correlation')

// Policy register — preview a rule change, activate it, inspect the history
// Session
export const signIn = (email) => postJSON('/session', { email })
export const getSession = () => getJSON('/session').then((d) => d.account)
export const signOut = () => getJSON('/session', { method: 'DELETE' })
export const getAccounts = () => getJSON('/accounts')

// The policy library — several documents, each with its own version history
const doc = (key) => `/policy/documents/${encodeURIComponent(key)}`
export const getPolicyLibrary = () => getJSON('/policy/library')
export const createPolicyDoc = (body) => postJSON('/policy/documents', body)
export const getPolicyDoc = (key) => getJSON(doc(key))
export const getPolicyDocDefault = (key) => getJSON(`${doc(key)}/default`).then((d) => d.text)
export const validatePolicyDoc = (key, text) => postJSON(`${doc(key)}/validate`, { text })
export const previewPolicyDoc = (key, text) => postJSON(`${doc(key)}/preview`, { text })
export const activatePolicyDoc = (key, body) => postJSON(`${doc(key)}/activate`, body)
export const getPolicyDocHistory = (key) => getJSON(`${doc(key)}/history`)
export const getPolicyDocVersion = (key, id) => getJSON(`${doc(key)}/versions/${id}`)
export const rollbackPolicyDoc = (key, body) => postJSON(`${doc(key)}/rollback`, body)
export const revertPolicyChange = (key, body) => postJSON(`${doc(key)}/revert`, body)
