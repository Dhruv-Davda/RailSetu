/*
 * Time–distance "string-line" (Marey) diagram with two extra powers:
 *  1) MORPH — it holds BOTH the no-action (FCFS) and the rescheduled (priority)
 *     runs and tweens between them by `progress` (0→1). Toggling the optimizer
 *     animates the lines physically reorganising: the slow train is held back,
 *     the expresses fan ahead and overtake. That is the optimization, made visible.
 *  2) PLAYHEAD — a moving time cursor with a glowing dot per train at its current
 *     position, so you can watch the fleet actually run down the corridor (the
 *     M2.5 "ripple").
 */
const TYPE_COLOR = {
  RAJDHANI: '#ef4444', DURONTO: '#f97316', SHATABDI: '#f59e0b', SUPERFAST: '#eab308',
  MAIL: '#38bdf8', EXPRESS: '#22d3ee', PASSENGER: '#94a3b8', GOODS: '#64748b',
}
const hhmm = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(Math.round(m) % 60).padStart(2, '0')}`
const lerp = (a, b, p) => a + (b - a) * p

function tickStep(span) { for (const s of [15, 30, 60, 90, 120, 180]) if (span / s <= 10) return s; return 240 }

// Aligned (km, tBase, tOpt) points per train so we can interpolate position.
function mergedPoints(baseTL, optTL, stations) {
  const b = Object.fromEntries(baseTL.map((p) => [p.code, p]))
  const o = Object.fromEntries(optTL.map((p) => [p.code, p]))
  const pts = []
  for (const s of stations) {
    const bp = b[s.code], op = o[s.code]
    if (!bp || !op) continue
    pts.push({ km: s.km, tBase: bp.arr, tOpt: op.arr })
    if (bp.dep != null && op.dep != null) pts.push({ km: s.km, tBase: bp.dep, tOpt: op.dep })
  }
  return pts
}

export function timeRange(baseline, optimized) {
  let lo = Infinity, hi = -Infinity
  for (const set of [baseline, optimized]) {
    for (const tr of set || []) for (const p of tr.timeline) {
      if (p.arr != null) { lo = Math.min(lo, p.arr); hi = Math.max(hi, p.arr) }
      if (p.dep != null) hi = Math.max(hi, p.dep)
    }
  }
  if (!isFinite(lo)) return [0, 60]
  return [Math.floor(lo / 15) * 15, Math.ceil((hi + 4) / 15) * 15]
}

export default function StringLineChart({ stations, baseline, optimized, progress = 0, playhead = null, height = 430 }) {
  if (!stations?.length || !baseline?.length) return null
  const opt = optimized?.length ? optimized : baseline
  const W = 1000, H = height
  const padL = 70, padR = 26, padT = 22, padB = 30
  const maxKm = stations[stations.length - 1].km
  const [tMin, tMax] = timeRange(baseline, opt)

  const x = (t) => padL + (t - tMin) / (tMax - tMin) * (W - padL - padR)
  const y = (km) => padT + km / maxKm * (H - padT - padB)
  const step = tickStep(tMax - tMin)
  const ticks = []
  for (let t = Math.ceil(tMin / step) * step; t <= tMax; t += step) ticks.push(t)

  const baseByNo = Object.fromEntries(baseline.map((t) => [t.no, t]))
  const trains = opt.map((tr) => {
    const bt = baseByNo[tr.no] || tr
    const pts = mergedPoints(bt.timeline, tr.timeline, stations)
      .map((p) => ({ km: p.km, t: lerp(p.tBase, p.tOpt, progress) }))
    const delay = lerp(bt.delay_min, tr.delay_min, progress)
    return { no: tr.no, type: tr.type, pts, delay }
  })

  // playhead: position of each train at time = playhead
  const dot = (pts, t) => {
    if (t == null || t < pts[0].t || t > pts[pts.length - 1].t) return null
    for (let i = 1; i < pts.length; i++) {
      if (t <= pts[i].t) {
        const a = pts[i - 1], b = pts[i]
        const f = b.t === a.t ? 0 : (t - a.t) / (b.t - a.t)
        return { x: x(lerp(a.t, b.t, f)), y: y(lerp(a.km, b.km, f)) }
      }
    }
    return null
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {stations.map((s, i) => i < stations.length - 1 && (
        <rect key={'band' + s.code} x={padL} y={y(s.km)} width={W - padL - padR}
          height={y(stations[i + 1].km) - y(s.km)} fill={i % 2 ? '#0d1b2a' : '#0b1726'} opacity="0.6" />
      ))}
      {ticks.map((t) => (
        <g key={'t' + t}>
          <line x1={x(t)} y1={padT} x2={x(t)} y2={H - padB} stroke="#16273a" strokeWidth="1" />
          <text x={x(t)} y={H - padB + 17} fill="#6f879f" fontSize="11" textAnchor="middle">{hhmm(t)}</text>
        </g>
      ))}
      {stations.map((s) => (
        <g key={s.code}>
          <line x1={padL} y1={y(s.km)} x2={W - padR} y2={y(s.km)} stroke="#21344a" strokeWidth="1" />
          <text x={padL - 12} y={y(s.km) + 4} fill="#c2d2e4" fontSize="12" textAnchor="end" fontWeight="800">{s.code}</text>
        </g>
      ))}
      {/* trains */}
      {trains.map((tr) => {
        const d = tr.pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.km).toFixed(1)}`).join(' ')
        const color = TYPE_COLOR[tr.type] || '#38bdf8'
        const delayed = tr.delay > 5
        return <path key={tr.no} d={d} fill="none" stroke={color} strokeWidth={delayed ? 2.4 : 1.8}
          strokeOpacity={delayed ? 0.95 : 0.82} strokeLinejoin="round" strokeLinecap="round" />
      })}
      {/* playhead */}
      {playhead != null && (
        <g>
          <line x1={x(playhead)} y1={padT} x2={x(playhead)} y2={H - padB} stroke="#eaf2fb" strokeWidth="1.5" strokeOpacity="0.55" />
          <rect x={x(playhead) - 22} y={padT - 16} width="44" height="15" rx="3" fill="#eaf2fb" />
          <text x={x(playhead)} y={padT - 5} fill="#06121f" fontSize="10" fontWeight="800" textAnchor="middle">{hhmm(playhead)}</text>
          {trains.map((tr) => {
            const p = dot(tr.pts, playhead)
            if (!p) return null
            const color = TYPE_COLOR[tr.type] || '#38bdf8'
            return <circle key={'d' + tr.no} cx={p.x} cy={p.y} r="5" fill={color} filter="url(#glow)" />
          })}
        </g>
      )}
      <text x={padL} y={13} fill="#5d728b" fontSize="10">distance ↓ · time →</text>
    </svg>
  )
}

export { TYPE_COLOR }
