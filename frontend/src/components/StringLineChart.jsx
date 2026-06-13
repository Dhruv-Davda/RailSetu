/*
 * Time–distance "string-line" (Marey) diagram — the classic railway running chart.
 * x = time of day, y = distance along the corridor (NDLS at top → CNB at bottom).
 * Each train is a line; its slope is its speed. When a fast train is stuck behind
 * a slow one the lines converge and flatten (the cascade); after rescheduling they
 * fan out cleanly (overtakes). This is the M2.5 "ripple" visualization.
 */
const TYPE_COLOR = {
  RAJDHANI: '#ef4444', DURONTO: '#f97316', SHATABDI: '#f59e0b', SUPERFAST: '#eab308',
  MAIL: '#38bdf8', EXPRESS: '#22d3ee', PASSENGER: '#94a3b8', GOODS: '#64748b',
}

const hhmm = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(Math.round(m) % 60).padStart(2, '0')}`

// pick a tick step (minutes) that yields ~8–10 readable labels across the span
function tickStep(spanMin) {
  for (const s of [15, 30, 60, 90, 120, 180]) if (spanMin / s <= 10) return s
  return 240
}

export default function StringLineChart({ stations, trains, height = 430 }) {
  if (!stations?.length || !trains?.length) return null
  const W = 1000, H = height
  const padL = 70, padR = 26, padT = 22, padB = 30
  const kmByCode = Object.fromEntries(stations.map((s) => [s.code, s.km]))
  const maxKm = stations[stations.length - 1].km

  let tMin = Infinity, tMax = -Infinity
  trains.forEach((tr) => tr.timeline.forEach((p) => {
    if (p.arr != null) { tMin = Math.min(tMin, p.arr); tMax = Math.max(tMax, p.arr) }
    if (p.dep != null) tMax = Math.max(tMax, p.dep)
  }))
  if (!isFinite(tMin)) return null
  tMin = Math.floor(tMin / 15) * 15
  tMax = Math.ceil((tMax + 4) / 15) * 15

  const x = (t) => padL + (t - tMin) / (tMax - tMin) * (W - padL - padR)
  const y = (km) => padT + km / maxKm * (H - padT - padB)

  const step = tickStep(tMax - tMin)
  const ticks = []
  for (let t = Math.ceil(tMin / step) * step; t <= tMax; t += step) ticks.push(t)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
      {/* alternating station bands for readability */}
      {stations.map((s, i) => i < stations.length - 1 && (
        <rect key={'band' + s.code} x={padL} y={y(s.km)} width={W - padL - padR}
          height={y(stations[i + 1].km) - y(s.km)} fill={i % 2 ? '#0d1b2a' : '#0b1726'} opacity="0.6" />
      ))}
      {/* time gridlines */}
      {ticks.map((t) => (
        <g key={'t' + t}>
          <line x1={x(t)} y1={padT} x2={x(t)} y2={H - padB} stroke="#16273a" strokeWidth="1" />
          <text x={x(t)} y={H - padB + 17} fill="#6f879f" fontSize="11" textAnchor="middle">{hhmm(t)}</text>
        </g>
      ))}
      {/* station lines + labels */}
      {stations.map((s) => (
        <g key={s.code}>
          <line x1={padL} y1={y(s.km)} x2={W - padR} y2={y(s.km)} stroke="#21344a" strokeWidth="1" />
          <text x={padL - 12} y={y(s.km) + 4} fill="#c2d2e4" fontSize="12" textAnchor="end" fontWeight="800">{s.code}</text>
        </g>
      ))}
      {/* trains */}
      {trains.map((tr) => {
        const pts = []
        tr.timeline.forEach((p) => {
          const km = kmByCode[p.code]
          if (p.arr != null) pts.push([x(p.arr), y(km)])
          if (p.dep != null && p.dep !== p.arr) pts.push([x(p.dep), y(km)])
        })
        if (!pts.length) return null
        const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
        const color = TYPE_COLOR[tr.type] || '#38bdf8'
        const delayed = tr.delay_min > 5
        return (
          <g key={tr.no}>
            <path d={d} fill="none" stroke={color} strokeWidth={delayed ? 2.4 : 1.8}
              strokeOpacity={delayed ? 0.95 : 0.8} strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={pts[0][0]} cy={pts[0][1]} r="3.2" fill={color} />
          </g>
        )
      })}
      {/* axis caption */}
      <text x={padL} y={13} fill="#5d728b" fontSize="10">distance ↓ · time →</text>
    </svg>
  )
}

export { TYPE_COLOR }
