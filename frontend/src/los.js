// Fruin Level-of-Service colour scale for crowd density (persons / m^2).
export const LOS = {
  A: { color: '#2ecc71', label: 'Free flow', max: 1.0 },
  C: { color: '#cddc39', label: 'Restricted', max: 2.0 },
  D: { color: '#ffb300', label: 'Constrained', max: 3.5 },
  E: { color: '#fb8c00', label: 'Dangerous', max: 5.0 },
  F: { color: '#e53935', label: 'Crush risk', max: 99 },
}

export function losColor(grade) {
  return (LOS[grade] || LOS.A).color
}

export function densityColor(density) {
  if (density < 1.0) return LOS.A.color
  if (density < 2.0) return LOS.C.color
  if (density < 3.5) return LOS.D.color
  if (density < 5.0) return LOS.E.color
  return LOS.F.color
}

export function statusFor(peak, crush) {
  if (crush > 0 || peak >= 5) return { label: 'CRITICAL', color: '#e53935' }
  if (peak >= 3.5) return { label: 'ELEVATED', color: '#fb8c00' }
  if (peak >= 2.0) return { label: 'MANAGED', color: '#ffb300' }
  return { label: 'SAFE', color: '#2ecc71' }
}
