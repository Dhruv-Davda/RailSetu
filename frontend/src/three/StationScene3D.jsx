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
  projectNodes, assignLevels, distanceToExits, principalAxis, centroid, losRgb, LEVEL_HEIGHT,
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

    // Platforms lie across the tracks, so the axis through them + 90 deg is the
    // track bearing. Derived, not hardcoded.
    const acrossAngle = principalAxis(platformIds.map((id) => pos[id]))
    const trackAngle = acrossAngle + Math.PI / 2
    const trackDir = new THREE.Vector3(Math.cos(trackAngle), 0, Math.sin(trackAngle))
    const acrossDir = new THREE.Vector3(Math.cos(acrossAngle), 0, Math.sin(acrossAngle))

    const mid = centroid(station.nodes.map((n) => pos[n.id]))
    const p3 = (id, lift = 0) => {
      const p = pos[id]
      if (!p) return null
      return new THREE.Vector3(p.x - mid.x, (level[id] || 0) * LEVEL_HEIGHT + lift, p.z - mid.z)
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
            <boxGeometry args={[PLATFORM_LEN + 90, 0.35, 9]} />
            <meshStandardMaterial color="#1a2330" roughness={0.95} />
          </mesh>
          {/* rail pair */}
          {[-0.75, 0.75].map((o) => (
            <mesh key={o} position={[0, 0.26, o]}>
              <boxGeometry args={[PLATFORM_LEN + 90, 0.22, 0.16]} />
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
                <div className="v3-crush">
                  ⚠ CRUSH · {h.density.toFixed(1)} p/m²
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

function CameraRig({ view, geo, sim, controls }) {
  const { camera } = useThree()
  const goal = useRef({ pos: new THREE.Vector3(), tgt: new THREE.Vector3() })
  const armed = useRef(null)

  useEffect(() => {
    const r = geo.radius
    const top = sim?.node_hotspots?.[0]
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
    } else {
      pos = new THREE.Vector3(r * 0.3, r * 0.95, r * 0.95)
      tgt = new THREE.Vector3(0, 4, 0)
    }

    goal.current = { pos, tgt }
    armed.current = performance.now()
  }, [view, geo, sim])

  useFrame(() => {
    if (!armed.current) return
    const k = 0.055
    camera.position.lerp(goal.current.pos, k)
    if (controls.current) {
      controls.current.target.lerp(goal.current.tgt, k)
      controls.current.update()
    }
    if (camera.position.distanceTo(goal.current.pos) < 1.5) armed.current = null
  })
  return null
}

/* ------------------------------------------------------------------------ root */

export default function StationScene3D({ station, sim }) {
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
        <TrackBeds geo={geo} />
        <Platforms geo={geo} showLabels={view === 'aerial' || view === 'concourse'} />
        <StationTrains geo={geo} intensity={intensity} />
        <WalkNetwork geo={geo} station={station} sim={sim} />
        <DensityColumns geo={geo} sim={sim} intensity={intensity} />
        <CrowdParticles geo={geo} station={station} sim={sim} intensity={intensity} />
        <CrushBeacons geo={geo} sim={sim} />
        <ExitPads geo={geo} />
        <OrbitControls
          ref={controls} makeDefault enableDamping dampingFactor={0.08}
          maxPolarAngle={Math.PI / 2.06} minDistance={30} maxDistance={2000}
        />
        <CameraRig view={view} geo={geo} sim={sim} controls={controls} />
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
        Schematic 3D · vertical levels <b>inferred</b> from stair topology (not surveyed) ·
        particles show <b>aggregate modelled flow</b>, not individual passengers ·
        column height = peak density, colour = Fruin LOS
      </div>
    </div>
  )
}
