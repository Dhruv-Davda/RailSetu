const BASE = '/api'

// Single fetch wrapper: always checks response.ok and surfaces a useful error,
// so a backend outage/500 becomes a caught rejection (handled by callers) rather
// than a half-parsed error body that crashes the UI downstream.
async function getJSON(path, opts) {
  let r
  try {
    r = await fetch(`${BASE}${path}`, opts)
  } catch (e) {
    throw new Error(`Network error reaching ${path} — is the backend running?`)
  }
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).detail || '' } catch { /* non-JSON body */ }
    throw new Error(`API ${r.status} on ${path}${detail ? ` — ${detail}` : ''}`)
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

// M2 — Delay propagation & rescheduling
export const getCorridor = () => getJSON('/m2/network')
export const getM2Scenarios = () => getJSON('/m2/scenarios').then((d) => d.scenarios)
export const runM2 = (scenario, optimize) => postJSON('/m2/simulate', { scenario, optimize })

// M6 — Kavach gap analysis
export const getKavach = () => getJSON('/m6/coverage')
export const getKavachCorrelation = () => getJSON('/m6/correlation')
