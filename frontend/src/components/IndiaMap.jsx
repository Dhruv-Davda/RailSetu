import { useEffect, useRef } from 'react'
import L from 'leaflet'

const STATUS_COLOR = { equipped: '#2ecc71', partial: '#ffc02e', none: '#ef4444' }

// Imperative Leaflet map of India with rail corridors coloured by Kavach status
// and weighted by traffic. Red = busy + unprotected = where the risk concentrates.
export default function IndiaMap({ coverage, onHover }) {
  const elRef = useRef(null)
  const mapRef = useRef(null)
  const layerRef = useRef(null)

  useEffect(() => {
    if (mapRef.current) return
    const map = L.map(elRef.current, { zoomControl: true, attributionControl: false, scrollWheelZoom: true })
      .setView([22.6, 80.5], 5)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 12 }).addTo(map)
    mapRef.current = map
    return () => { map.remove(); mapRef.current = null }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !coverage) return
    if (layerRef.current) layerRef.current.remove()
    const grp = L.layerGroup().addTo(map)
    layerRef.current = grp

    const cities = new Set()
    coverage.corridors.forEach((c) => {
      const color = STATUS_COLOR[c.status]
      const weight = 2 + (c.daily_trains / 320) * 7
      const line = L.polyline([c.from_ll, c.to_ll], {
        color, weight, opacity: 0.85, lineCap: 'round',
      }).addTo(grp)
      line.bindTooltip(
        `<b>${c.name}</b><br/>${c.daily_trains} trains/day · Kavach ${c.kavach_pct}%<br/>risk exposure ${c.risk_exposure}`,
        { sticky: true })
      if (onHover) line.on('mouseover', () => onHover(c)).on('mouseout', () => onHover(null))
      cities.add(JSON.stringify({ ll: c.from_ll, n: c.from }))
      cities.add(JSON.stringify({ ll: c.to_ll, n: c.to }))
    })
    cities.forEach((s) => {
      const { ll, n } = JSON.parse(s)
      L.circleMarker(ll, { radius: 3.5, color: '#cde', fillColor: '#cde', fillOpacity: 0.9, weight: 0 })
        .bindTooltip(n, { direction: 'top' }).addTo(grp)
    })
  }, [coverage, onHover])

  return <div ref={elRef} className="m6map" />
}

export { STATUS_COLOR }
