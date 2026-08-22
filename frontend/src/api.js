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

// M3 — Rail surface defect inspection (EfficientNet-B0 + YOLO11-s)
// Warming is a POST because it has a side effect: it pulls ~35 MB of weights
// into memory. Calling it on page load means no user pays that cost mid-demo.
export const warmM3 = () => getJSON('/m3/warm', { method: 'POST' })
export const getM3Samples = () => getJSON('/m3/samples').then((d) => d.samples)
export const m3SampleUrl = (id) => `/api/m3/samples/${id}`
export function analyseM3({ file, sample, localizer = true, cam = true, conf = null }) {
  // multipart, not JSON: an uploaded photo is binary and base64 would inflate it 33%
  const fd = new FormData()
  if (file) fd.append('file', file)
  if (sample) fd.append('sample', sample)
  fd.append('localizer', String(localizer))
  fd.append('cam', String(cam))
  // omitted -> the server applies its configured floor (RAILSETU_M3_CONF)
  if (conf != null) fd.append('conf', String(conf))
  // no content-type header — the browser must set the multipart boundary itself
  return getJSON('/m3/analyse', { method: 'POST', body: fd })
}

