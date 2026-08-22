/*
 * M1 — New Delhi station in 3D.
 *
 * Everything drawn here comes from /api/station and /api/simulate:
 *   · node lat/lon              -> local metre positions
 *   · edge kind + `steps`       -> inferred two-level station (ground + FOB deck)
 *   · platform node PCA         -> track direction (platforms lie across the tracks)
 *   · per-edge / per-node density -> colour (Fruin LOS) and column height
 *   · dist-to-nearest-exit      -> the direction crowd particles travel
 *
 * SCHEMATIC, and the UI says so: the vertical dimension is inferred, not
 * surveyed, and the particles represent aggregate modelled flow — the model is
 * macroscopic and does not track individual passengers.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Grid, Html } from '@react-three/drei'
import * as THREE from 'three'
import {
  projectNodes, projectLL, assignLevels, distanceToExits, principalAxis, centroid, losRgb, levelY, LEVEL_HEIGHT,
} from './geo.js'

const PLATFORM_LEN = 340
const PLATFORM_W = 15
const TRACK_OFFSET = 13.5
const DECK_Y = LEVEL_HEIGHT

/* ---------------------------------------------------------------- derived data */

function useStationGeometry(station) {
  return useMemo(() => {
    if (!station) return null
    const platformIds = station.platforms.map((p) => p.node)
    const exitIds = station.entrances.map((e) => e.node)
    const pos = projectNodes(station.nodes, station.meta.center)
    const level = assignLevels(station.nodes, station.edges, platformIds)
    const dExit = distanceToExits(station.nodes, station.edges, exitIds)

    // Track bearing. Preferred source: the REAL rail alignments — the
    // length-weighted dominant axis over every OSM rail segment (angle-doubled
    // so opposite directions reinforce instead of cancelling). Fallback when
    // the rails fixture is absent: the old platform-PCA inference, which at
    // NDLS turned out to be ~90° off — visible the moment real rails landed
    // in the scene beside the schematic beds.
    let trackAngle
    if (station.rails?.length) {
      let sx = 0, sz = 0
      for (const w of station.rails) {
        let prev = null
        for (const [lat, lon] of w.pts) {
          const p = projectLL(lat, lon, station.meta.center)
          if (prev) {
            const dx = p.x - prev.x, dz = p.z - prev.z
            const L = Math.hypot(dx, dz)
            if (L > 0.5) {
              const a2 = 2 * Math.atan2(dz, dx)
              sx += L * Math.cos(a2)
              sz += L * Math.sin(a2)
            }
          }
          prev = p
        }
      }
      trackAngle = 0.5 * Math.atan2(sz, sx)
    } else {
      trackAngle = principalAxis(platformIds.map((id) => pos[id])) + Math.PI / 2
    }
    const acrossAngle = trackAngle + Math.PI / 2
    const trackDir = new THREE.Vector3(Math.cos(trackAngle), 0, Math.sin(trackAngle))
    const acrossDir = new THREE.Vector3(Math.cos(acrossAngle), 0, Math.sin(acrossAngle))

    const mid = centroid(station.nodes.map((n) => pos[n.id]))
    const p3 = (id, lift = 0) => {
      const p = pos[id]
      if (!p) return null
      return new THREE.Vector3(p.x - mid.x, levelY(level[id]) + lift, p.z - mid.z)
    }

    let radius = 0
    for (const n of station.nodes) {
      const d = Math.hypot(pos[n.id].x - mid.x, pos[n.id].z - mid.z)
      if (d > radius) radius = d
    }

    return {
      pos, level, dExit, trackAngle, trackDir, acrossDir, mid, p3, radius,
      platformIds, exitIds,
      platforms: station.platforms.map((p) => ({ ...p, v: p3(p.node) })).filter((p) => p.v),
      entrances: station.entrances.map((e) => ({ ...e, v: p3(e.node) })).filter((e) => e.v),
    }
  }, [station])
}

/* -------------------------------------------------------------------- lighting */

function Lights() {
  return (
    <>
      <ambientLight intensity={0.32} color="#9fc4e8" />
      <hemisphereLight args={['#4a7ba8', '#08121d', 0.42]} />
      <directionalLight position={[260, 420, 180]} intensity={0.75} color="#dceaff" />
      <directionalLight position={[-300, 200, -260]} intensity={0.22} color="#3d6b96" />
    </>
  )
}

/* ------------------------------------------------------------ real rail yard */

/**
 * The real NDLS trackage, from OpenStreetMap (`/api/station` -> `rails`;
 * fetched by scripts/fetch_rail_lines.py). ~160 ways / ~54 km: every platform
 * road, yard siding and both approach throats. This is why the 2D basemap looks
 * dense — the tiles draw the true yard — and the schematic 3D used to look
 * empty. Alignments are REAL; widths are exaggerated so a track reads from
 * aerial distance (the scene is schematic and says so).
 *
 * Everything is merged into four triangle-soup BufferGeometries (ballast,
 * sleepers, yard rails, mainline rails) => 4 draw calls for the entire yard.
 */
const TIE_SPACING = 7.5
function RailNetwork({ geo, station }) {
  const geos = useMemo(() => {
    const ways = station?.rails
    if (!ways?.length) return null
    const c = station.meta.center
    const ballast = [], ties = [], railMain = [], railYard = []

    // Flat ribbon (two triangles) from a->b, half-width hw, at height y.
    const quad = (arr, ax, az, bx, bz, hw, y) => {
      let dx = bx - ax, dz = bz - az
      const L = Math.hypot(dx, dz) || 1
      dx /= L; dz /= L
      const px = -dz * hw, pz = dx * hw
      arr.push(
        ax + px, y, az + pz, bx + px, y, bz + pz, bx - px, y, bz - pz,
        ax + px, y, az + pz, bx - px, y, bz - pz, ax - px, y, az - pz,
      )
    }

    for (const w of ways) {
      const pts = w.pts.map(([lat, lon]) => {
        const p = projectLL(lat, lon, c)
        return [p.x - geo.mid.x, p.z - geo.mid.z]
      })
      const rails = w.t === 'rail' ? railMain : railYard
      for (let i = 1; i < pts.length; i++) {
        const [ax, az] = pts[i - 1]
        const [bx, bz] = pts[i]
        let dx = bx - ax, dz = bz - az
        const L = Math.hypot(dx, dz)
        if (L < 0.3) continue
        dx /= L; dz /= L
        const px = -dz, pz = dx
        quad(ballast, ax, az, bx, bz, 1.8, 0.04)
        for (const off of [-0.75, 0.75]) {
          quad(rails, ax + px * off, az + pz * off, bx + px * off, bz + pz * off, 0.2, 0.1)
        }
        for (let d = 3; d < L; d += TIE_SPACING) {
          const cx = ax + dx * d, cz = az + dz * d
          quad(ties, cx - px * 1.3, cz - pz * 1.3, cx + px * 1.3, cz + pz * 1.3, 0.3, 0.07)
        }
      }
    }
    const mk = (a) => {
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(a), 3))
      return g
    }
    return { ballast: mk(ballast), ties: mk(ties), railMain: mk(railMain), railYard: mk(railYard) }
  }, [station, geo])

  if (!geos) return null
  return (
    <group>
      <mesh geometry={geos.ballast}><meshBasicMaterial color="#1a2432" /></mesh>
      <mesh geometry={geos.ties}><meshBasicMaterial color="#263449" /></mesh>
      <mesh geometry={geos.railYard}><meshBasicMaterial color="#55677c" toneMapped={false} /></mesh>
      <mesh geometry={geos.railMain}><meshBasicMaterial color="#8ba3bd" toneMapped={false} /></mesh>
    </group>
  )
}

/* ------------------------------------------------------------ track + platform */

function TrackBeds({ geo }) {
  const { platforms, trackAngle, acrossDir } = geo
  const items = useMemo(() => {
    const out = []
    for (const p of platforms) {
      for (const side of [-1, 1]) {
        const c = p.v.clone().addScaledVector(acrossDir, side * TRACK_OFFSET)
        out.push({ key: `${p.node}${side}`, pos: [c.x, 0.06, c.z] })
      }
    }
    return out
  }, [platforms, acrossDir])

  return (
    <group>
      {items.map((it) => (
        <group key={it.key} position={it.pos} rotation={[0, -trackAngle, 0]}>
          {/* ballast */}
          <mesh receiveShadow position={[0, -0.02, 0]}>
            <boxGeometry args={[PLATFORM_LEN + 20, 0.35, 9]} />
            <meshStandardMaterial color="#1a2330" roughness={0.95} />
          </mesh>
          {/* rail pair */}
          {[-0.75, 0.75].map((o) => (
            <mesh key={o} position={[0, 0.26, o]}>
              <boxGeometry args={[PLATFORM_LEN + 20, 0.22, 0.16]} />
              <meshStandardMaterial color="#8fa4bb" metalness={0.85} roughness={0.3} />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  )
}

// OSM `ref` is sometimes already "Platform 16" and sometimes just "6;7".
const platLabel = (ref) => `P${String(ref).replace(/^platform\s*/i, '')}`

function Platforms({ geo, showLabels }) {
  const { platforms, trackAngle } = geo
  return (
    <group>
      {platforms.map((p) => (
        <group key={p.node} position={[p.v.x, 0, p.v.z]} rotation={[0, -trackAngle, 0]}>
          {/* deck */}
          <mesh position={[0, 0.55, 0]} receiveShadow>
            <boxGeometry args={[PLATFORM_LEN, 1.1, PLATFORM_W]} />
            <meshStandardMaterial color="#28455f" roughness={0.8} />
          </mesh>
          {/* yellow safety lines */}
          {[-1, 1].map((s) => (
            <mesh key={s} position={[0, 1.11, s * (PLATFORM_W / 2 - 1.1)]}>
              <boxGeometry args={[PLATFORM_LEN, 0.03, 0.5]} />
              <meshStandardMaterial color="#f5c542" emissive="#6b4c00" emissiveIntensity={0.4} />
            </mesh>
          ))}
          {/* canopy on pillars */}
          <mesh position={[0, 7.2, 0]}>
            <boxGeometry args={[PLATFORM_LEN * 0.82, 0.35, PLATFORM_W + 3]} />
            <meshStandardMaterial color="#16324a" roughness={0.7} transparent opacity={0.5} />
          </mesh>
          {Array.from({ length: 6 }, (_, i) => {
            const x = (i / 5 - 0.5) * PLATFORM_LEN * 0.78
            return [-1, 1].map((s) => (
              <mesh key={`${i}${s}`} position={[x, 3.9, s * (PLATFORM_W / 2 - 1.6)]}>
                <cylinderGeometry args={[0.22, 0.22, 6.6, 6]} />
                <meshStandardMaterial color="#20384f" />
              </mesh>
            ))
          })}
          {showLabels && (
            <Html position={[0, 11, 0]} center distanceFactor={210} zIndexRange={[10, 0]}>
              <div className="v3-plat">{platLabel(p.ref)}</div>
            </Html>
          )}
        </group>
      ))}
    </group>
  )
}

/* ---------------------------------------------------------------------- trains */

function TrainBody({ length = 260, cars = 12, color = '#c94f4f', accent = '#ffd166' }) {
  const carLen = length / cars
  return (
    <group>
      {Array.from({ length: cars }, (_, i) => {
        const x = (i - (cars - 1) / 2) * carLen
        const isLoco = i === 0
        return (
          <group key={i} position={[x, 2.55, 0]}>
            <mesh>
              <boxGeometry args={[carLen * 0.93, 3.5, 3.2]} />
              <meshStandardMaterial
                color={isLoco ? '#4a6d8c' : color}
                emissive={isLoco ? '#1a2c3d' : color}
                emissiveIntensity={0.35}
                metalness={0.25}
                roughness={0.5}
              />
            </mesh>
            {/* window band */}
            <mesh position={[0, 0.75, 0]}>
              <boxGeometry args={[carLen * 0.82, 0.85, 3.28]} />
              <meshBasicMaterial color={accent} toneMapped={false} />
            </mesh>
            {/* skirt */}
            <mesh position={[0, -2.1, 0]}>
              <boxGeometry args={[carLen * 0.85, 0.8, 2.6]} />
              <meshStandardMaterial color="#14202d" roughness={0.9} />
            </mesh>
          </group>
        )
      })}
    </group>
  )
}

// Trains standing at (and pulling into) the platform tracks. Purely illustrative
// of the arrivals that generate the modelled demand.
function StationTrains({ geo, intensity }) {
  const { platforms, trackAngle, acrossDir } = geo
  const movingRef = useRef()

  const berths = useMemo(() => {
    const picks = platforms.slice(0, 6)
    return picks.map((p, i) => {
      const side = i % 2 ? 1 : -1
      const c = p.v.clone().addScaledVector(acrossDir, side * TRACK_OFFSET)
      return {
        key: p.node,
        pos: [c.x, 0, c.z],
        color: ['#c94f4f', '#3f6fa8', '#b5763c', '#4a8f6b', '#8f4a7a', '#5a6b8f'][i % 6],
        cars: 10 + (i % 4),
      }
    })
  }, [platforms, acrossDir])

  // One train slides in along the track to give the scene motion.
  const arriving = berths[berths.length - 1]
  useFrame(({ clock }) => {
    if (!movingRef.current || !arriving) return
    const cycle = (clock.elapsedTime * 0.06) % 1
    const eased = 1 - Math.pow(1 - Math.min(cycle * 1.6, 1), 3)
    const offset = (1 - eased) * 620
    movingRef.current.position.set(
      arriving.pos[0] + Math.cos(trackAngle) * offset,
      0,
      arriving.pos[2] + Math.sin(trackAngle) * offset,
    )
  })

  return (
    <group>
      {berths.slice(0, -1).map((b) => (
        <group key={b.key} position={b.pos} rotation={[0, -trackAngle, 0]}>
          <TrainBody cars={b.cars} color={b.color} />
        </group>
      ))}
      {arriving && (
        <group ref={movingRef} rotation={[0, -trackAngle, 0]}>
          <TrainBody cars={arriving.cars} color={arriving.color} accent="#9fe8ff" />
          <pointLight position={[-135, 3, 0]} distance={90} intensity={2 + intensity * 3} color="#cfe9ff" />
        </group>
      )}
    </group>
  )
}

/* -------------------------------------------------------------- walk network */

const _o = new THREE.Object3D()
const _c = new THREE.Color()

function WalkNetwork({ geo, station, sim }) {
  const ref = useRef()
  const densityByEdge = useMemo(() => {
    const m = {}
    for (const e of sim?.edges || []) m[`${e.u}|${e.v}`] = e
    return m
  }, [sim])

  const edges = useMemo(
    () => station.edges.filter((e) => geo.p3(e.u) && geo.p3(e.v)),
    [station, geo],
  )

  useEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    edges.forEach((e, i) => {
      const a = geo.p3(e.u, 0.35), b = geo.p3(e.v, 0.35)
      const d = densityByEdge[`${e.u}|${e.v}`] || densityByEdge[`${e.v}|${e.u}`]
      const dens = d?.density ?? 0
      const len = a.distanceTo(b)
      const mp = a.clone().add(b).multiplyScalar(0.5)

      _o.position.copy(mp)
      _o.lookAt(b)
      const w = e.kind === 'steps' ? 3.6 : Math.max(2.4, Math.min(e.width_m || 2.5, 9))
      const active = dens > 0.05
      const thick = active ? 0.7 + Math.min(dens, 8) * 0.2 : 0.4
      _o.scale.set(w, thick, len)
      _o.updateMatrix()
      mesh.setMatrixAt(i, _o.matrix)

      // Unlit data layer: carrying traffic -> exact Fruin LOS colour; idle
      // corridors -> the same muted slate the 2D map uses, so the eye reads
      // "where the crowd is" instead of "where the walkways are".
      if (active) {
        const [r, g, bl] = losRgb(dens)
        _c.setRGB(r, g, bl)
      } else if ((geo.level[e.u] || 0) < 0 && (geo.level[e.v] || 0) < 0) {
        _c.setRGB(0.15, 0.20, 0.28)   // subway passage: dimmer than surface paths
      } else {
        _c.setRGB(0.26, 0.35, 0.46)
      }
      mesh.setColorAt(i, _c)
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [edges, densityByEdge, geo])

  return (
    <instancedMesh ref={ref} args={[undefined, undefined, edges.length]}>
      <boxGeometry args={[1, 1, 1]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  )
}

/* ------------------------------------------------------------ density columns */

function DensityColumns({ geo, sim, intensity }) {
  const ref = useRef()
  const rows = useMemo(
    () => (sim?.nodes || []).filter((n) => n.density >= 0.6 && geo.p3(n.node)),
    [sim, geo],
  )

  useFrame(({ clock }) => {
    const mesh = ref.current
    if (!mesh) return
    const t = clock.elapsedTime
    rows.forEach((n, i) => {
      const base = geo.p3(n.node)
      const pulse = n.los === 'F' ? 1 + Math.sin(t * 3.4 + i) * 0.09 : 1
      const h = Math.min(n.density, 20) * 2.6 * intensity * pulse + 0.4
      _o.position.set(base.x, base.y + h / 2, base.z)
      _o.rotation.set(0, 0, 0)
      const r = 2.2 + Math.min(n.density, 12) * 0.34
      _o.scale.set(r, h, r)
      _o.updateMatrix()
      mesh.setMatrixAt(i, _o.matrix)
      const [cr, cg, cb] = losRgb(n.density)
      _c.setRGB(cr, cg, cb)
      mesh.setColorAt(i, _c)
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  if (!rows.length) return null
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, rows.length]}>
      <cylinderGeometry args={[1, 1, 1, 12, 1, true]} />
      <meshBasicMaterial
        transparent opacity={0.5} side={THREE.DoubleSide}
        toneMapped={false} depthWrite={false} blending={THREE.AdditiveBlending}
      />
    </instancedMesh>
  )
}

/* ------------------------------------------------------------ crowd particles */

const MAX_PARTICLES = 4200

function CrowdParticles({ geo, station, sim, intensity }) {
  const ref = useRef()

  const data = useMemo(() => {
    const byKey = {}
    for (const e of sim?.edges || []) byKey[`${e.u}|${e.v}`] = e

    // Direction of travel = downhill in distance-to-nearest-exit, i.e. the same
    // "head for your closest exit" rule the simulation routes on.
    const segs = []
    let totalPeople = 0
    for (const e of station.edges) {
      const d = byKey[`${e.u}|${e.v}`] || byKey[`${e.v}|${e.u}`]
      if (!d || d.people < 0.5) continue
      const du = geo.dExit[e.u] ?? Infinity, dv = geo.dExit[e.v] ?? Infinity
      const [from, to] = du >= dv ? [e.u, e.v] : [e.v, e.u]
      const a = geo.p3(from, 0.9), b = geo.p3(to, 0.9)
      if (!a || !b) continue
      segs.push({ a, b, people: d.people, dens: d.density, len: a.distanceTo(b) })
      totalPeople += d.people
    }
    if (!segs.length) return null

    const pos = new Float32Array(MAX_PARTICLES * 3)
    const col = new Float32Array(MAX_PARTICLES * 3)
    const meta = []
    let k = 0
    for (const s of segs) {
      const share = Math.max(1, Math.round((s.people / totalPeople) * MAX_PARTICLES))
      const [r, g, b] = losRgb(s.dens)
      for (let j = 0; j < share && k < MAX_PARTICLES; j++, k++) {
        // Denser corridors shuffle slower — queueing, not free walking.
        const speed = (0.55 + Math.random() * 0.5) / Math.max(1, s.len) * (1 / (1 + s.dens * 0.32))
        meta.push({ s, t: Math.random(), speed, lat: (Math.random() - 0.5) * 0.8 })
        col[k * 3] = r; col[k * 3 + 1] = g; col[k * 3 + 2] = b
      }
    }
    return { pos, col, meta, count: k }
  }, [station, sim, geo])

  useFrame((_, dt) => {
    if (!data || !ref.current) return
    const step = Math.min(dt, 0.05) * 26 * (0.35 + intensity)
    const { pos, meta } = data
    for (let i = 0; i < meta.length; i++) {
      const m = meta[i]
      m.t += m.speed * step
      if (m.t > 1) m.t -= 1
      const { a, b } = m.s
      pos[i * 3] = a.x + (b.x - a.x) * m.t + m.lat
      pos[i * 3 + 1] = a.y + (b.y - a.y) * m.t
      pos[i * 3 + 2] = a.z + (b.z - a.z) * m.t + m.lat
    }
    ref.current.geometry.attributes.position.needsUpdate = true
  })

  if (!data) return null
  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={data.pos} count={data.count} itemSize={3} />
        <bufferAttribute attach="attributes-color" array={data.col} count={data.count} itemSize={3} />
      </bufferGeometry>
      {/* Normal blending, not additive: overlapping particles on a busy corridor
          would sum past 1.0 and read as a white streak, destroying the LOS
          colour that is the whole point of the layer. */}
      <pointsMaterial
        size={3.4} sizeAttenuation vertexColors transparent opacity={0.85}
        depthWrite={false} toneMapped={false}
      />
    </points>
  )
}

/* -------------------------------------------------------------- crush beacons */

function CrushBeacons({ geo, sim }) {
  const hotspots = useMemo(
    () => (sim?.node_hotspots || []).filter((h) => h.los === 'F' || h.los === 'E').slice(0, 6),
    [sim],
  )
  const ref = useRef()
  useFrame(({ clock }) => {
    if (!ref.current) return
    const t = clock.elapsedTime
    ref.current.children.forEach((g, i) => {
      const s = 1 + Math.sin(t * 3 + i * 0.7) * 0.16
      g.scale.set(s, 1, s)
    })
  })

  return (
    <group ref={ref}>
      {hotspots.map((h, i) => {
        const v = geo.p3(h.node)
        if (!v) return null
        const crit = h.los === 'F'
        const col = crit ? '#ff3b30' : '#ff9500'
        return (
          <group key={h.node} position={[v.x, v.y, v.z]}>
            <mesh position={[0, 17, 0]}>
              <cylinderGeometry args={[crit ? 5.2 : 3.6, crit ? 1.6 : 1.2, 34, 14, 1, true]} />
              <meshBasicMaterial
                color={col} transparent opacity={crit ? 0.2 : 0.12}
                side={THREE.DoubleSide} depthWrite={false} blending={THREE.AdditiveBlending}
              />
            </mesh>
            <mesh position={[0, 0.5, 0]}>
              <ringGeometry args={[6, 9.5, 32]} />
              <meshBasicMaterial color={col} transparent opacity={0.55} side={THREE.DoubleSide} />
            </mesh>
            <pointLight position={[0, 14, 0]} color={col} intensity={crit ? 9 : 4} distance={110} />
            {i === 0 && (
              <Html position={[0, 40, 0]} center distanceFactor={230} zIndexRange={[20, 0]}>
                {/* LOS F is the crush regime; LOS E is dangerous but NOT a crush
                    point. Labelling both "CRUSH" contradicted the status bar's
                    crush count and made a mitigated run read as a failed one. */}
                <div className={`v3-crush ${crit ? '' : 'warn'}`}>
                  ⚠ {crit ? 'CRUSH' : 'DANGER'} · {h.density.toFixed(1)} p/m²
                  <span>queue {Math.round(h.queue)} · {h.node}</span>
                </div>
              </Html>
            )}
          </group>
        )
      })}
    </group>
  )
}

/* --------------------------------------------------------- analyser overlay */

// Phases mirror what the backend is actually doing, with the dwell times taken
// from measured cost: 16 sims ~1.7 s, then the Gemini brief (~6-10 s).
const ANALYSIS_PHASES = [
  [0, 'SIMULATING MITIGATION PLANS'],
  [1900, 'RANKING BY CRUSH RISK'],
  [2900, 'GENERATING CONTROL BRIEF'],
]

/**
 * "Working" overlay pinned to the danger zone while the optimizer runs.
 *
 * A spinner in the sidebar tells you something is happening; this tells you
 * WHERE and on WHAT. Scan rings climb the crush column, a sweep line rotates
 * over it, and the caption names the stage — so the wait reads as the system
 * examining the hotspot rather than as latency.
 */
function AnalyzerOverlay({ geo, sim, baseline, active }) {
  // Prefer the no-action hotspot: on a re-run the current sim may already be
  // mitigated, and the overlay should sit on the danger zone being solved.
  const node = baseline?.node_hotspots?.[0] || sim?.node_hotspots?.[0]
  const ringRefs = useRef([])
  const sweepRef = useRef()
  const t0 = useRef(0)
  const [phase, setPhase] = useState(ANALYSIS_PHASES[0][1])

  useEffect(() => {
    if (!active) return
    setPhase(ANALYSIS_PHASES[0][1])
    const timers = ANALYSIS_PHASES.slice(1).map(([at, label]) =>
      setTimeout(() => setPhase(label), at))
    return () => timers.forEach(clearTimeout)
  }, [active])

  useFrame(({ clock }) => {
    if (!active) return
    if (!t0.current) t0.current = clock.elapsedTime
    const t = clock.elapsedTime - t0.current
    ringRefs.current.forEach((m, i) => {
      if (!m) return
      const f = ((t * 0.55 + i / 3) % 1)          // 0->1 climb
      m.position.y = f * 46
      const sc = 0.55 + f * 1.5
      m.scale.set(sc, sc, sc)
      m.material.opacity = 0.5 * (1 - f)
    })
    if (sweepRef.current) sweepRef.current.rotation.y = t * 2.1
  })
  useEffect(() => { if (!active) t0.current = 0 }, [active])

  if (!active || !node) return null
  const v = geo.p3(node.node)
  if (!v) return null

  return (
    <group position={[v.x, v.y, v.z]}>
      {[0, 1, 2].map((i) => (
        <mesh key={i} ref={(el) => (ringRefs.current[i] = el)} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[8, 10.5, 40]} />
          <meshBasicMaterial
            color="#8ab4f8" transparent opacity={0.5}
            side={THREE.DoubleSide} depthWrite={false} toneMapped={false}
          />
        </mesh>
      ))}
      {/* rotating sweep line */}
      <group ref={sweepRef}>
        <mesh position={[9, 1.2, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[19, 1.1]} />
          <meshBasicMaterial
            color="#8ab4f8" transparent opacity={0.6}
            side={THREE.DoubleSide} depthWrite={false} toneMapped={false}
          />
        </mesh>
      </group>
      <pointLight position={[0, 16, 0]} color="#8ab4f8" intensity={5} distance={130} />
      <Html position={[0, 58, 0]} center distanceFactor={230} zIndexRange={[21, 0]}>
        <div className="v3-analyse">
          <span className="dots"><i /><i /><i /></span>
          {phase}
          <span>optimising at {node.node} · {node.density.toFixed(1)} p/m²</span>
        </div>
      </Html>
    </group>
  )
}

/* ------------------------------------------------------------------ deck piers */

/** Support columns under every FOB-deck node, so the bridge stands on legs
 *  instead of floating. Deck membership comes from the real OSM bridge tags. */
function DeckPiers({ geo, station }) {
  const piers = useMemo(
    () => station.nodes
      .map((n) => n.id ?? n.node)
      .filter((id) => (geo.level[id] || 0) > 0)
      .map((id) => geo.p3(id))
      .filter(Boolean),
    [station, geo],
  )
  if (!piers.length) return null
  return (
    <group>
      {piers.map((v, i) => (
        <mesh key={i} position={[v.x, v.y / 2 - 0.2, v.z]}>
          <cylinderGeometry args={[0.5, 0.62, Math.max(v.y - 0.4, 0.1), 8]} />
          <meshStandardMaterial color="#243447" roughness={0.85} />
        </mesh>
      ))}
    </group>
  )
}

/* ------------------------------------------------------- before/after overlay */

/**
 * Ghost columns for the NO-ACTION run, drawn behind the live (mitigated) ones.
 *
 * A percentage chip tells a judge the peak fell; it does not let them *see* it.
 * This draws the baseline height as a hollow red cage at each node that was
 * dangerous before mitigation, so the short solid column now standing inside a
 * tall red cage is the improvement, in place, at the spot it matters.
 *
 * Only baseline LOS E/F nodes are ghosted (max 8) — ghosting every node would
 * double the scene and destroy the read.
 */
function BaselineGhosts({ geo, baseline, sim }) {
  const rows = useMemo(() => {
    if (!baseline || !sim || baseline === sim) return []
    const after = Object.fromEntries((sim.nodes || []).map((n) => [n.node, n.density]))
    return (baseline.nodes || [])
      .filter((n) => (n.los === 'E' || n.los === 'F') && geo.p3(n.node))
      .map((n) => ({ ...n, after: after[n.node] ?? 0 }))
      .sort((a, b) => b.density - a.density)
      .slice(0, 8)
  }, [baseline, sim, geo])

  // Same height/radius mapping as DensityColumns, so the cage and the live
  // column are directly comparable rather than merely suggestive.
  const dims = (d) => ({
    h: Math.min(d, 20) * 2.6 + 0.4,
    r: 2.2 + Math.min(d, 12) * 0.34,
  })

  if (!rows.length) return null
  const worst = rows[0]

  // The badge must describe the STATION, not just this node. Relieving n150
  // while the crush reappears at n126 is a relocation, not a fix — reporting it
  // as "cleared" next to a live red CRUSH beacon is exactly the contradiction
  // this overlay exists to remove.
  const crushNow = sim?.summary?.crush_count ?? 0
  const nodeCleared = worst.density >= 5 && worst.after < 5
  const nowWorst = sim?.node_hotspots?.[0]
  const peakBefore = baseline?.summary?.peak_density ?? 0
  const peakAfter = sim?.summary?.peak_density ?? 0
  // Some controls (staggered release, extra gates) leave the peak untouched on
  // this scenario. Saying "reduced" when nothing moved is the same overclaim in
  // the opposite direction, so that case gets its own honest state.
  const improved = peakBefore > 0 && (peakBefore - peakAfter) / peakBefore >= 0.02
  const state = crushNow === 0 && nodeCleared ? 'cleared'
    : nodeCleared ? 'moved'
      : improved ? 'reduced'
        : 'none'

  return (
    <group>
      {rows.map((n) => {
        const v = geo.p3(n.node)
        const { h, r } = dims(n.density)
        return (
          <group key={`ghost-${n.node}`} position={[v.x, v.y, v.z]}>
            <mesh position={[0, h / 2, 0]}>
              <cylinderGeometry args={[r, r, h, 14, 1, true]} />
              <meshBasicMaterial
                color="#ff3b30" wireframe transparent opacity={0.22}
                toneMapped={false} depthWrite={false}
              />
            </mesh>
            {/* cap ring marks the old peak height */}
            <mesh position={[0, h, 0]} rotation={[-Math.PI / 2, 0, 0]}>
              <ringGeometry args={[r * 0.92, r, 24]} />
              <meshBasicMaterial
                color="#ff3b30" transparent opacity={0.45}
                side={THREE.DoubleSide} depthWrite={false}
              />
            </mesh>
          </group>
        )
      })}

      {/* One badge on the worst former hotspot — the Feb 2025 FOB landing. */}
      {(() => {
        const v = geo.p3(worst.node)
        const { h } = dims(worst.density)
        return (
          <Html
            position={[v.x, v.y + h + 26, v.z]} center
            distanceFactor={230} zIndexRange={[19, 0]}
          >
            <div className={`v3-cleared ${state}`}>
              {state === 'cleared' && '✓ CRUSH CLEARED'}
              {state === 'moved' && '⚠ CRUSH RELOCATED'}
              {state === 'reduced' && '↓ PEAK REDUCED'}
              {state === 'none' && '— NO IMPROVEMENT'}
              <span>
                {state === 'none'
                  ? `peak still ${peakAfter.toFixed(1)} p/m² · ${crushNow} crush point${crushNow === 1 ? '' : 's'}`
                  : `${worst.node} ${worst.density.toFixed(1)} → ${worst.after.toFixed(1)} p/m²`}
                {state === 'moved' && nowWorst
                  ? ` · now ${nowWorst.node} at ${nowWorst.density.toFixed(1)}`
                  : ''}
              </span>
            </div>
          </Html>
        )
      })()}
    </group>
  )
}

/* ------------------------------------------------------------------- exit pads */

function ExitPads({ geo }) {
  return (
    <group>
      {geo.entrances.map((e) => (
        <group key={e.node} position={[e.v.x, e.v.y + 0.3, e.v.z]}>
          <mesh rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[7, 24]} />
            <meshBasicMaterial color="#26a69a" transparent opacity={0.3} />
          </mesh>
          <mesh position={[0, 5, 0]}>
            <cylinderGeometry args={[1.1, 1.1, 10, 8]} />
            <meshBasicMaterial color="#26a69a" transparent opacity={0.35} />
          </mesh>
        </group>
      ))}
    </group>
  )
}

/* ------------------------------------------------------------------ camera rig */

const VIEWS = {
  aerial: { label: 'Aerial' },
  fob: { label: 'FOB crush' },
  platform: { label: 'Platform' },
  concourse: { label: 'Deck' },
}

function CameraRig({ view, geo, sim, baseline, controls }) {
  const { camera } = useThree()
  const defaultControls = useThree((s) => s.controls)
  const goal = useRef({ pos: new THREE.Vector3(), tgt: new THREE.Vector3() })
  const armed = useRef(null)
  // Set once the user grabs the camera. The fly-in must never fight a hand on
  // the mouse, and data landing later must not yank the view back.
  const userTook = useRef(false)

  useEffect(() => {
    if (!defaultControls) return
    const yieldToUser = () => { armed.current = null; userTook.current = true }
    defaultControls.addEventListener('start', yieldToUser)
    return () => defaultControls.removeEventListener('start', yieldToUser)
  }, [defaultControls])

  // Picking a view button is an explicit request to move the camera again.
  useEffect(() => { userTook.current = false }, [view])

  useEffect(() => {
    const r = geo.radius
    // With a mitigation active the current run may have NO hotspot left — the
    // baseline's worst node is where the outcome badge stands, so views that
    // frame "the hotspot" fall back to it instead of drifting to a wide shot.
    const baseTop = baseline?.node_hotspots?.[0]
    const top = sim?.node_hotspots?.[0] || baseTop
    const hot = top ? geo.p3(top.node) : null
    const td = geo.trackDir, ad = geo.acrossDir
    let pos, tgt

    if (view === 'fob' && hot) {
      // Frame the actual worst hotspot, from across the tracks.
      tgt = new THREE.Vector3(hot.x, hot.y + 8, hot.z)
      pos = hot.clone()
        .addScaledVector(ad, 95)
        .addScaledVector(td, -55)
        .add(new THREE.Vector3(0, 62, 0))
    } else if (view === 'platform') {
      // Stand on the platform closest to the crush, eye height, looking along
      // the track so the arriving train comes straight at the camera.
      let base = geo.platforms[0].v
      if (hot) {
        let best = Infinity
        for (const p of geo.platforms) {
          const d = p.v.distanceTo(hot)
          if (d < best) { best = d; base = p.v }
        }
      }
      pos = base.clone().addScaledVector(td, -140).add(new THREE.Vector3(0, 4.2, 0))
      tgt = base.clone().addScaledVector(td, 90).add(new THREE.Vector3(0, 6, 0))
    } else if (view === 'concourse') {
      // Low oblique across the FOB deck.
      const c = hot || new THREE.Vector3(0, DECK_Y, 0)
      tgt = new THREE.Vector3(c.x, DECK_Y + 6, c.z)
      pos = c.clone().addScaledVector(ad, -r * 0.55).add(new THREE.Vector3(0, r * 0.42, 0))
    } else if (baseTop && geo.p3(baseTop.node)) {
      // A mitigation result just landed: fly IN to the outcome badge (the
      // baseline's worst node) instead of resetting to the wide aerial — the
      // judge should be looking AT the CLEARED / RELOCATED tag, not searching
      // for it. If the crush relocated, frame old and new worst together.
      const a = geo.p3(baseTop.node)
      const curTop = sim?.node_hotspots?.[0]
      const b = curTop && curTop.node !== baseTop.node ? geo.p3(curTop.node) : null
      const c = b ? a.clone().add(b).multiplyScalar(0.5) : a.clone()
      const spread = b ? a.distanceTo(b) : 0
      const ghostH = Math.min(baseTop.density, 20) * 2.6
      const d = Math.max(110, spread * 1.3, ghostH * 2.8)
      // Aim above the ghost cage so the floating outcome badge (cage top + 26)
      // sits inside the frame instead of clipping at the canvas edge.
      tgt = new THREE.Vector3(c.x, c.y + ghostH * 0.75, c.z)
      pos = c.clone()
        .addScaledVector(ad, d * 0.85)
        .addScaledVector(td, -d * 0.5)
        .add(new THREE.Vector3(0, d * 0.85, 0))
    } else {
      // Aerial: look down the yard along the (rail-derived) track axis — the
      // classic throat shot — from a three-quarter offset so depth still reads.
      tgt = new THREE.Vector3(0, 4, 0)
      pos = new THREE.Vector3(0, r * 0.8, 0)
        .addScaledVector(td, -r * 0.95)
        .addScaledVector(ad, r * 0.22)
    }

    goal.current = { pos, tgt }
    if (!userTook.current) armed.current = performance.now()
  }, [view, geo, sim, baseline])

  useFrame((_, dt) => {
    if (!armed.current) return
    // Time-based, not per-frame: a fixed 0.055 step meant the fly-in took ~110
    // frames, and the FIRST frames are the slowest (shader compile, particle
    // and rail-mesh build). At ~15fps that locked the controls for seconds.
    const k = 1 - Math.pow(0.05, Math.min(dt, 0.1))
    camera.position.lerp(goal.current.pos, k)
    if (controls.current) {
      controls.current.target.lerp(goal.current.tgt, k)
      controls.current.update()
    }
    // Release on arrival OR on a hard deadline, so a slow first paint can never
    // hold the camera hostage.
    if (camera.position.distanceTo(goal.current.pos) < 1.5
        || performance.now() - armed.current > 1600) {
      armed.current = null
    }
  })
  return null
}

/* ------------------------------------------------------------------------ root */

export default function StationScene3D({ station, sim, baseline, analyzing = false }) {
  const geo = useStationGeometry(station)
  const controls = useRef()
  const [view, setView] = useState('aerial')
  const [playing, setPlaying] = useState(false)
  const [intensity, setIntensity] = useState(1)
  const raf = useRef(0)

  // Replay the surge build-up using the sim's own global density timeline as the
  // envelope. Peak-state colours stay put; what animates is how hard it is running.
  const timeline = sim?.timeline || []
  useEffect(() => () => cancelAnimationFrame(raf.current), [])

  function playSurge() {
    cancelAnimationFrame(raf.current)
    if (!timeline.length) return
    setPlaying(true)
    const peak = Math.max(...timeline) || 1
    const dur = 9000
    const t0 = performance.now()
    const tick = (now) => {
      const p = (now - t0) / dur
      if (p >= 1) { setIntensity(1); setPlaying(false); return }
      const idx = Math.min(timeline.length - 1, Math.floor(p * timeline.length))
      setIntensity(Math.max(0.06, timeline[idx] / peak))
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
  }

  if (!station || !geo) {
    return <div className="v3-wrap"><div className="v3-loading">loading station geometry…</div></div>
  }

  return (
    <div className="v3-wrap">
      <Canvas
        shadows={false}
        dpr={[1, 1.8]}
        camera={{ position: [200, 700, 700], fov: 45, near: 1, far: 6000 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#0a0b0c']} />
        <fog attach="fog" args={['#0a0b0c', 700, 2400]} />
        <Lights />
        <Grid
          args={[2600, 2600]} cellSize={25} cellThickness={0.5} cellColor="#13273a"
          sectionSize={125} sectionThickness={1} sectionColor="#1d374e"
          fadeDistance={1900} fadeStrength={1.4} followCamera={false} infiniteGrid
          position={[0, -0.4, 0]}
        />
        <RailNetwork geo={geo} station={station} />
        <TrackBeds geo={geo} />
        <Platforms geo={geo} showLabels={view === 'aerial' || view === 'concourse'} />
        <StationTrains geo={geo} intensity={intensity} />
        <WalkNetwork geo={geo} station={station} sim={sim} />
        <DeckPiers geo={geo} station={station} />
        <DensityColumns geo={geo} sim={sim} intensity={intensity} />
        <CrowdParticles geo={geo} station={station} sim={sim} intensity={intensity} />
        <CrushBeacons geo={geo} sim={sim} />
        {analyzing && <AnalyzerOverlay geo={geo} sim={sim} baseline={baseline} active />}
        <BaselineGhosts geo={geo} baseline={baseline} sim={sim} />
        <ExitPads geo={geo} />
        <OrbitControls
          ref={controls} makeDefault enableDamping dampingFactor={0.08}
          maxPolarAngle={Math.PI / 2.06} minDistance={30} maxDistance={2000}
        />
        <CameraRig view={view} geo={geo} sim={sim} baseline={baseline} controls={controls} />
      </Canvas>

      <div className="v3-hud">
        {Object.entries(VIEWS).map(([k, v]) => (
          <button key={k} className={`v3-btn ${view === k ? 'on' : ''}`} onClick={() => setView(k)}>
            {v.label}
          </button>
        ))}
        <button className="v3-btn" onClick={playSurge} disabled={playing}>
          {playing ? '▶ surge…' : '▶ Replay surge'}
        </button>
      </div>

      <div className="v3-note">
        Schematic 3D · track alignments <b>real</b> (OpenStreetMap{station.rails?.length ? `, ${station.rails.length} ways` : ''}; widths exaggerated) ·
        FOB / subway levels <b>real</b> (OSM bridge &amp; tunnel tags; heights schematic) ·
        particles show <b>aggregate modelled flow</b>, not individual passengers ·
        column height = peak density, colour = Fruin LOS
      </div>
    </div>
  )
}
