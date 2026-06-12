import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { densityColor } from './los.js'

// Imperative Leaflet wrapper. Draws the NDLS walk graph as polylines coloured
// by peak crowd density, overlays platform/exit markers, and pulses the crush
// hotspots. Kept framework-light on purpose so the render is predictable.
export default function StationMap({ station, sim }) {
  const elRef = useRef(null)
  const mapRef = useRef(null)
  const baseLayer = useRef(null)
  const overlay = useRef(null)
  const nodeIndex = useRef({})

  // One-time: create map + draw the static station skeleton.
  useEffect(() => {
    if (!station || mapRef.current) return
    const center = [station.meta.center.lat, station.meta.center.lon]
    const map = L.map(elRef.current, { zoomControl: true, attributionControl: false })
      .setView(center, 17)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 20,
    }).addTo(map)
    mapRef.current = map

    const idx = {}
    station.nodes.forEach((n) => { idx[n.id] = n })
    nodeIndex.current = idx

    // Static grey skeleton so the layout reads even before a sim runs.
    baseLayer.current = L.layerGroup().addTo(map)
    station.edges.forEach((e) => {
      const a = idx[e.u], b = idx[e.v]
      if (!a || !b) return
      L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
        color: '#3a4a5a', weight: e.kind === 'steps' ? 3 : 2, opacity: 0.5,
      }).addTo(baseLayer.current)
    })

    // Platform + exit markers.
    station.platforms.forEach((p) => {
      const n = idx[p.node]
      if (!n) return
      L.marker([n.lat, n.lon], { icon: dotIcon('#4fc3f7', 9) })
        .bindTooltip(p.name || `Platform ${p.ref}`, { direction: 'top' })
        .addTo(baseLayer.current)
    })
    station.entrances.forEach((ex) => {
      const n = idx[ex.node]
      if (!n) return
      L.marker([n.lat, n.lon], { icon: dotIcon('#26a69a', 7) })
        .bindTooltip(ex.name || 'Exit', { direction: 'top' })
        .addTo(baseLayer.current)
    })

    const b = L.latLngBounds(station.nodes.map((n) => [n.lat, n.lon]))
    map.fitBounds(b.pad(0.05))
  }, [station])

  // Re-draw the density overlay whenever a new sim result arrives.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !sim) return
    if (overlay.current) overlay.current.remove()
    overlay.current = L.layerGroup().addTo(map)
    const idx = nodeIndex.current

    // Coloured edges (the heatmap).
    sim.edges.forEach((e) => {
      const a = idx[e.u], b = idx[e.v]
      if (!a || !b) return
      const danger = e.los === 'E' || e.los === 'F'
      L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
        color: densityColor(e.density),
        weight: danger ? 6 : e.density > 1 ? 4 : 2.5,
        opacity: e.density > 0.05 ? 0.95 : 0.25,
      }).bindTooltip(
        `${e.kind} — ${e.density.toFixed(1)} p/m² (LOS ${e.los})`,
        { sticky: true },
      ).addTo(overlay.current)
    })

    // Node density blobs + pulsing crush points.
    sim.nodes.forEach((n) => {
      if (n.density < 1.0) return
      const danger = n.los === 'E' || n.los === 'F'
      L.circleMarker([n.lat, n.lon], {
        radius: Math.min(6 + n.density * 1.6, 26),
        color: densityColor(n.density),
        fillColor: densityColor(n.density),
        fillOpacity: 0.35,
        weight: danger ? 2 : 1,
        className: n.los === 'F' ? 'crush-pulse' : '',
      }).bindTooltip(
        `${n.name || n.kind} — ${n.density.toFixed(1)} p/m² (LOS ${n.los}), peak queue ${n.queue}`,
        { sticky: true },
      ).addTo(overlay.current)
    })

    // Label the single worst crush point.
    const top = sim.node_hotspots && sim.node_hotspots[0]
    if (top && (top.los === 'F' || top.los === 'E')) {
      L.marker([top.lat, top.lon], { icon: crushIcon() })
        .bindTooltip(`CRUSH RISK: ${top.density.toFixed(1)} p/m²`, {
          permanent: true, direction: 'right', className: 'crush-label',
        })
        .addTo(overlay.current)
    }
  }, [sim])

  return <div ref={elRef} className="map" />
}

function dotIcon(color, size) {
  return L.divIcon({
    className: '',
    html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:1.5px solid #0b1622;box-shadow:0 0 4px ${color}"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

function crushIcon() {
  return L.divIcon({
    className: '',
    html: `<div class="crush-marker">⚠</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })
}
