/*
 * Where the person making a change is.
 *
 * The browser will not hand this over without the author's permission, and it
 * should not — so this never throws and never guesses. It resolves either to a
 * real fix or to a plain statement of why there isn't one, and the register
 * stores whichever it gets. A change made with location refused is a perfectly
 * valid change; one recorded against an invented position is not.
 */

const TIMEOUT_MS = 8000

const REASON = {
  1: 'permission denied',
  2: 'position unavailable',
  3: 'timed out',
}

export function locationSupported() {
  return typeof navigator !== 'undefined'
    && 'geolocation' in navigator
    // Browsers only expose geolocation on a secure origin. localhost counts.
    && (window.isSecureContext ?? window.location.protocol === 'https:')
}

/** Always resolves. Never rejects, never invents a position. */
export function captureLocation() {
  if (!locationSupported()) {
    return Promise.resolve({
      available: false,
      reason: typeof navigator !== 'undefined' && 'geolocation' in navigator
        ? 'needs a secure connection'
        : 'not supported by this browser',
    })
  }
  return new Promise((resolve) => {
    let settled = false
    const done = (v) => { if (!settled) { settled = true; resolve(v) } }
    navigator.geolocation.getCurrentPosition(
      (pos) => done({
        available: true,
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy,
        captured_at: new Date(pos.timestamp).toISOString(),
      }),
      (err) => done({ available: false, reason: REASON[err?.code] || 'unavailable' }),
      { enableHighAccuracy: true, timeout: TIMEOUT_MS, maximumAge: 60_000 },
    )
    // Some browsers never call either callback if the prompt is dismissed.
    setTimeout(() => done({ available: false, reason: 'timed out' }), TIMEOUT_MS + 500)
  })
}

/** "28.64280, 77.21910 · ±18 m" */
export function formatLocation(loc) {
  if (!loc?.available) return null
  const acc = loc.accuracy_m != null ? ` · ±${Math.round(loc.accuracy_m)} m` : ''
  return `${loc.latitude.toFixed(5)}, ${loc.longitude.toFixed(5)}${acc}`
}

export function mapLink(loc) {
  if (!loc?.available) return null
  const { latitude: la, longitude: lo } = loc
  return `https://www.openstreetmap.org/?mlat=${la}&mlon=${lo}#map=16/${la}/${lo}`
}
