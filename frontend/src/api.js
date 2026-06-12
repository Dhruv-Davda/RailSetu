const BASE = '/api'

export async function getStation() {
  const r = await fetch(`${BASE}/station`)
  if (!r.ok) throw new Error('station fetch failed')
  return r.json()
}

export async function getScenarios() {
  const r = await fetch(`${BASE}/scenarios`)
  return (await r.json()).scenarios
}

export async function simulate(scenario, mitigations) {
  const r = await fetch(`${BASE}/simulate`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ scenario, mitigations }),
  })
  return r.json()
}

export async function whatif(scenario, mitigations) {
  const r = await fetch(`${BASE}/whatif`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ scenario, mitigations }),
  })
  return r.json()
}
