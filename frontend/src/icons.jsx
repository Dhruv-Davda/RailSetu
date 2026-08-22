/*
 * Inline SVG icon set — no emoji, no icon font, no network.
 *
 * Emoji glyphs render differently on every OS and read as placeholder art;
 * railway control software uses drawn symbols. These are stroked at a common
 * 1.6px weight on a 24-unit grid so they sit together in the nav.
 */

const base = {
  width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.6,
  strokeLinecap: 'round', strokeLinejoin: 'round',
}

/** Overview — a signalling-panel grid. */
export function IconPanel(p) {
  return (
    <svg {...base} {...p}>
      <rect x="3" y="4" width="18" height="16" rx="1" />
      <path d="M3 9h18M9 9v11M15 4v5" />
      <circle cx="6" cy="6.4" r="1" fill="currentColor" stroke="none" />
    </svg>
  )
}

/** M1 — station: platform canopy over a track. */
export function IconStation(p) {
  return (
    <svg {...base} {...p}>
      <path d="M2 8l10-4 10 4" />
      <path d="M5 8v6M19 8v6" />
      <path d="M3 20h18" />
      <path d="M8 20l1-6M16 20l-1-6" />
      <path d="M9.5 17h5" />
    </svg>
  )
}

/** M2 — train on a line. */
export function IconTrain(p) {
  return (
    <svg {...base} {...p}>
      <rect x="5" y="3" width="14" height="13" rx="2" />
      <path d="M5 9h14" />
      <circle cx="8.6" cy="12.6" r="1" fill="currentColor" stroke="none" />
      <circle cx="15.4" cy="12.6" r="1" fill="currentColor" stroke="none" />
      <path d="M7.5 16L5 21M16.5 16L19 21M3 21h18" />
    </svg>
  )
}

/** M6 — protection / shield over a rail. */
export function IconShield(p) {
  return (
    <svg {...base} {...p}>
      <path d="M12 3l7 3v6c0 4-3 6.7-7 9-4-2.3-7-5-7-9V6z" />
      <path d="M9 12h6M12 9.5v5" />
    </svg>
  )
}

/** A colour-light signal head — used for status lamps. */
export function IconSignal(p) {
  return (
    <svg {...base} {...p}>
      <rect x="8" y="2" width="8" height="14" rx="4" />
      <circle cx="12" cy="6" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.4" />
      <path d="M12 16v6M9 22h6" />
    </svg>
  )
}

export function IconArrow(p) {
  return (
    <svg {...base} {...p}>
      <path d="M5 12h13M13 7l5 5-5 5" />
    </svg>
  )
}

/** M3 — inspection: a lens over a rail surface, with corner registration marks. */
export function IconScan(p) {
  return (
    <svg {...base} {...p}>
      <path d="M3 8V4h4M17 4h4v4M21 16v4h-4M7 20H3v-4" />
      <circle cx="12" cy="12" r="3.2" />
      <path d="M14.3 14.3L17 17" />
    </svg>
  )
}

