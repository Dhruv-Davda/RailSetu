/*
 * M2 — the New Delhi → Kanpur corridor in 3D.
 *
 * Driven entirely by /api/m2/network and /api/m2/simulate:
 *   · station km          -> position along the line
 *   · train timeline arr/dep -> position at any simulated minute
 *   · held_min > 0        -> the train is shunted onto the LOOP line, so a
 *                            hold-and-overtake is something you watch happen
 *   · `progress`          -> morphs every train between the no-action (FCFS)
 *                            and rescheduled runs, same as the string-line chart
 *
 * Schematic scale: 1 unit = 1 km, with train and platform sizes exaggerated so
 * they are visible at corridor zoom.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Grid, Html } from '@react-three/drei'
import * as THREE from 'three'
import { TYPE_COLOR, timeRange } from '../components/StringLineChart.jsx'
import PlatformPassScene from './PlatformPassScene.jsx'

const MAIN_Z = 0
const LOOP_Z = 2.4
const TRAIN_LEN = 3.0
const PLAT_LEN = 5.0
const lerp = (a, b, p) => a + (b - a) * p
const hhmm = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(Math.floor(m) % 60).padStart(2, '0')}`

/* --------------------------------------------------- per-train motion profile */

/**
 * Merge the baseline and optimized timelines into one list of station events so
 * a single `progress` value tweens the whole motion. Each event carries both
 * runs' arrive/depart minute and hold duration.
 */
function buildProfiles(stations, baseline, optimized) {
  const kmOf = Object.fromEntries(stations.map((s) => [s.code, s.km]))
  const optByNo = Object.fromEntries((optimized || []).map((t) => [t.no, t]))

  return (baseline || []).map((bt) => {
    const ot = optByNo[bt.no] || bt
    const oByCode = Object.fromEntries(ot.timeline.map((p) => [p.code, p]))
    const events = []
    for (const bp of bt.timeline) {
      const op = oByCode[bp.code] || bp
      events.push({
        km: kmOf[bp.code] ?? 0,
        arrB: bp.arr, arrO: op.arr,
        depB: bp.dep ?? bp.arr, depO: op.dep ?? op.arr,
        heldB: bp.held_min || 0, heldO: op.held_min || 0,
      })
    }
    return {
      no: bt.no,
      name: bt.name,
      type: bt.type,
      color: TYPE_COLOR[bt.type] || '#38bdf8',
      delayB: bt.delay_min,
      delayO: ot.delay_min,
      events,
    }
  })
}

/** Position (km, lateral, held) of a train at simulated minute `t` and morph `p`. */
function locate(profile, t, p) {
  const ev = profile.events
  if (!ev.length) return null
  const arr = (e) => lerp(e.arrB, e.arrO, p)
  const dep = (e) => lerp(e.depB, e.depO, p)
  const held = (e) => lerp(e.heldB, e.heldO, p)

  if (t < arr(ev[0]) || t > arr(ev[ev.length - 1])) return null

  for (let i = 0; i < ev.length; i++) {
    const a = arr(ev[i]), d = dep(ev[i])
    // Dwelling at a station.
    if (t >= a && t <= d) {
      const h = held(ev[i])
      return { km: ev[i].km, held: h, lateral: h > 0.4 ? 1 : 0, moving: false }
    }
    // Running to the next station.
    if (i + 1 < ev.length) {
      const nextA = arr(ev[i + 1])
      if (t > d && t < nextA) {
        const f = nextA === d ? 0 : (t - d) / (nextA - d)
        return {
          km: lerp(ev[i].km, ev[i + 1].km, f),
          held: 0,
          // ease off the loop as it pulls away / onto it as it arrives
          lateral: held(ev[i]) > 0.4 ? Math.max(0, 1 - f * 4) : 0,
          moving: true,
        }
      }
    }
  }
  return null
}

/* --------------------------------------------------------------- static track */

function Rails({ length, z, color = '#8fa4bb' }) {
  return (
    <group position={[length / 2, 0, z]}>
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[length, 0.12, 1.5]} />
        <meshStandardMaterial color="#18212e" roughness={0.95} />
      </mesh>
      {[-0.32, 0.32].map((o) => (
        <mesh key={o} position={[0, 0.12, o]}>
          <boxGeometry args={[length, 0.08, 0.09]} />
          <meshStandardMaterial color={color} metalness={0.85} roughness={0.28} />
        </mesh>
      ))}
    </group>
  )
}

function Corridor({ stations }) {
  const total = stations[stations.length - 1].km
  return (
    <group>
      <Rails length={total} z={MAIN_Z} />
      {/* loop line stub at each intermediate station — where holds happen */}
      {stations.slice(0, -1).map((s) => (
        <group key={s.code} position={[s.km - 9, 0, 0]}>
          <Rails length={18} z={LOOP_Z} color="#6b7f96" />
        </group>
      ))}
    </group>
  )
}

function Stations({ stations, disruptionAt }) {
  return (
    <group>
      {stations.map((s) => {
        const flagged = disruptionAt === s.code
        return (
          <group key={s.code} position={[s.km, 0, 0]}>
            {/* island platform between main and loop */}
            <mesh position={[0, 0.28, LOOP_Z / 2]}>
              <boxGeometry args={[PLAT_LEN, 0.55, 1.25]} />
              <meshStandardMaterial color="#2a4760" roughness={0.8} />
            </mesh>
            <mesh position={[0, 0.57, LOOP_Z / 2]}>
              <boxGeometry args={[PLAT_LEN, 0.03, 0.16]} />
              <meshStandardMaterial color="#f5c542" emissive="#5c4200" emissiveIntensity={0.5} />
            </mesh>
            {/* canopy */}
            <mesh position={[0, 1.75, LOOP_Z / 2]}>
              <boxGeometry args={[PLAT_LEN * 0.8, 0.1, 1.9]} />
              <meshStandardMaterial color="#16324a" transparent opacity={0.55} />
            </mesh>
            {[-1, 1].map((k) => (
              <mesh key={k} position={[k * PLAT_LEN * 0.32, 1.15, LOOP_Z / 2]}>
                <cylinderGeometry args={[0.07, 0.07, 1.2, 6]} />
                <meshStandardMaterial color="#20384f" />
              </mesh>
            ))}
            {/* signal mast — reds up when this is the disruption point */}
            <group position={[PLAT_LEN * 0.6, 0, -1.5]}>
              <mesh position={[0, 1.1, 0]}>
                <cylinderGeometry args={[0.06, 0.06, 2.2, 6]} />
                <meshStandardMaterial color="#2b3d52" />
              </mesh>
              <mesh position={[0, 2.2, 0]}>
                <sphereGeometry args={[0.22, 12, 12]} />
                <meshBasicMaterial color={flagged ? '#ff3b30' : '#2ecc71'} />
              </mesh>
              <pointLight
                position={[0, 2.2, 0]} distance={9}
                intensity={flagged ? 3.5 : 1.2} color={flagged ? '#ff3b30' : '#2ecc71'}
              />
            </group>
            <Html position={[0, 3.4, LOOP_Z / 2]} center zIndexRange={[4, 0]}>
              <div className={`v3-stn ${flagged ? 'hot' : ''}`}>
                <b>{s.code}</b><span>{s.km} km</span>
              </div>
            </Html>
          </group>
        )
      })}
    </group>
  )
}

/* -------------------------------------------------------------------- trains */

function Train({ profile }) {
  const cars = profile.type === 'PASSENGER' ? 9 : 7
  const carLen = TRAIN_LEN / cars
  return (
    <group>
      {Array.from({ length: cars }, (_, i) => {
        const x = (i - (cars - 1) / 2) * carLen
        const loco = i === 0
        return (
          <group key={i} position={[x, 0.62, 0]}>
            <mesh>
              <boxGeometry args={[carLen * 0.9, 0.72, 0.86]} />
              <meshStandardMaterial
                color={loco ? '#4a6d8c' : profile.color}
                emissive={loco ? '#16283a' : profile.color}
                emissiveIntensity={0.4}
                metalness={0.25} roughness={0.5}
              />
            </mesh>
            <mesh position={[0, 0.17, 0]}>
              <boxGeometry args={[carLen * 0.78, 0.2, 0.88]} />
              <meshBasicMaterial color="#ffd7a0" toneMapped={false} />
            </mesh>
          </group>
        )
      })}
      {/* headlight */}
      <pointLight position={[-TRAIN_LEN / 2 - 0.3, 0.7, 0]} distance={14} intensity={2.4} color="#dceaff" />
    </group>
  )
}

function Fleet({ profiles, timeRef, progressRef, focusRef, labels }) {
  const groups = useRef([])

  useFrame(() => {
    const t = timeRef.current
    const p = progressRef.current
    profiles.forEach((prof, i) => {
      const g = groups.current[i]
      if (!g) return
      const loc = locate(prof, t, p)
      if (!loc) { g.visible = false; return }
      g.visible = true
      g.position.x = loc.km
      // smooth the lateral shift onto the loop line
      const targetZ = loc.lateral * LOOP_Z
      g.position.z += (targetZ - g.position.z) * 0.12
      if (focusRef.current?.no === prof.no) {
        focusRef.current.x = g.position.x
        focusRef.current.z = g.position.z
      }
    })
  })

  return (
    <group>
      {profiles.map((prof, i) => (
        <group key={prof.no} ref={(el) => (groups.current[i] = el)}>
          <Train profile={prof} />
          {labels && (
            <Html position={[0, 1.5, 0]} center zIndexRange={[3, 0]}>
              <div className="v3-train" style={{ borderColor: prof.color, color: prof.color }}>
                {prof.no}
              </div>
            </Html>
          )}
        </group>
      ))}
    </group>
  )
}

/* --------------------------------------------------------------- clock + rig */

function Clock({ timeRef, playing, speed, range, onWrap }) {
  useFrame((_, dt) => {
    if (!playing) return
    timeRef.current += Math.min(dt, 0.05) * speed
    if (timeRef.current > range[1]) { timeRef.current = range[0]; onWrap?.() }
  })
  return null
}

const VIEWS = {
  corridor: 'Corridor',
  platform: 'Platform (trains pass)',
  follow: 'Chase train',
  chart: 'Overhead',
}

function CameraRig({ view, stations, timeRef, profiles, focusRef, controls, platformStation }) {
  const { camera } = useThree()
  const total = stations[stations.length - 1].km

  useFrame(() => {
    const c = controls.current
    if (!c) return
    let pos, tgt

    if (view === 'platform' && platformStation) {
      const s = platformStation
      // stand on the platform deck, eye height, looking along the main line so
      // through trains sweep across frame
      pos = new THREE.Vector3(s.km - 7, 1.9, LOOP_Z / 2 + 0.75)
      tgt = new THREE.Vector3(s.km + 11, 0.85, MAIN_Z)
    } else if (view === 'follow') {
      const f = focusRef.current
      pos = new THREE.Vector3((f?.x ?? 0) - 7, 3.2, (f?.z ?? 0) + 6)
      tgt = new THREE.Vector3(f?.x ?? 0, 0.7, f?.z ?? 0)
    } else if (view === 'chart') {
      // high and slightly oblique so the whole 440 km fits and trains keep some form
      pos = new THREE.Vector3(total / 2, 300, 46)
      tgt = new THREE.Vector3(total / 2, 0, 0)
    } else {
      // corridor: drift along with the fleet centroid
      let sum = 0, n = 0
      for (const prof of profiles) {
        const loc = locate(prof, timeRef.current, 1)
        if (loc) { sum += loc.km; n++ }
      }
      const cx = n ? sum / n : total / 2
      pos = new THREE.Vector3(cx - 27, 14, 23)
      tgt = new THREE.Vector3(cx + 6, 0, 0)
    }

    const k = view === 'follow' || view === 'corridor' ? 0.06 : 0.05
    camera.position.lerp(pos, k)
    c.target.lerp(tgt, k)
    c.update()
  })
  return null
}

/* ------------------------------------------------------------------------ root */

export default function CorridorScene3D({ network, result, progress = 0, boxed = false }) {
  const wrapClass = `v3-wrap${boxed ? ' boxed' : ''}`
  const controls = useRef()
  const timeRef = useRef(0)
  const progressRef = useRef(progress)
  const focusRef = useRef(null)

  const [view, setView] = useState('corridor')
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(6)
  const [clockLabel, setClockLabel] = useState('')
  const [labels, setLabels] = useState(true)
  const [focusNo, setFocusNo] = useState(null)

  useEffect(() => { progressRef.current = progress }, [progress])

  const profiles = useMemo(() => {
    if (!network || !result?.baseline) return []
    return buildProfiles(network.stations, result.baseline.trains, result.optimized?.trains)
  }, [network, result])

  const range = useMemo(
    () => (result ? timeRange(result.baseline.trains, result.optimized?.trains) : [360, 700]),
    [result],
  )

  useEffect(() => { timeRef.current = range[0] }, [range])
  useEffect(() => {
    focusRef.current = focusNo ? { no: focusNo, x: 0, z: 0 } : null
    if (focusNo) setView('follow')
  }, [focusNo])

  // HUD clock at 8Hz rather than per-frame, so the scene isn't re-rendered by React.
  useEffect(() => {
    const id = setInterval(() => setClockLabel(hhmm(timeRef.current)), 125)
    return () => clearInterval(id)
  }, [])

  const disruptionAt = useMemo(() => {
    const a = result?.optimized?.actions?.[0]
    return a?.station || null
  }, [result])

  // For the eye-level view, stand at a THROUGH station. The first optimizer
  // action is usually at the origin terminus, where every train starts from a
  // stand and nothing actually passes.
  const platformStation = useMemo(() => {
    const st = network?.stations || []
    if (!st.length) return null
    const acted = (result?.optimized?.actions || [])
      .map((a) => st.find((s) => s.code === a.station))
      .find(Boolean)
    return acted || st[Math.min(2, st.length - 1)]
  }, [network, result])

  if (!network || !result?.baseline) {
    return <div className={wrapClass}><div className="v3-loading">loading corridor…</div></div>
  }

  const total = network.stations[network.stations.length - 1].km

  return (
    <div className={wrapClass}>
      {view === 'platform' ? (
        <PlatformPassScene
          station={platformStation} profiles={profiles} progress={progress}
          playing={playing} rate={speed / 6}
        />
      ) : (
      <Canvas
        dpr={[1, 1.8]}
        camera={{ position: [-30, 22, 32], fov: 48, near: 0.1, far: 4000 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#0a0b0c']} />
        <fog attach="fog" args={['#0a0b0c', 90, 420]} />
        <ambientLight intensity={0.6} color="#9fc4e8" />
        <hemisphereLight args={['#4a7ba8', '#08121d', 0.75]} />
        <directionalLight position={[120, 180, 90]} intensity={1.1} color="#dceaff" />
        <Grid
          args={[1400, 220]} cellSize={5} cellThickness={0.5} cellColor="#122437"
          sectionSize={25} sectionThickness={1} sectionColor="#1d374e"
          fadeDistance={520} fadeStrength={1.5} infiniteGrid={false}
          position={[total / 2, -0.05, 0]}
        />
        <Corridor stations={network.stations} />
        <Stations stations={network.stations} disruptionAt={disruptionAt} />
        <Fleet
          profiles={profiles} timeRef={timeRef} progressRef={progressRef}
          focusRef={focusRef} labels={labels}
        />
        <Clock timeRef={timeRef} playing={playing} speed={speed} range={range} />
        <OrbitControls
          ref={controls} makeDefault enableDamping dampingFactor={0.08}
          maxPolarAngle={Math.PI / 2.02} minDistance={3} maxDistance={600}
        />
        <CameraRig
          view={view} stations={network.stations} timeRef={timeRef} profiles={profiles}
          focusRef={focusRef} controls={controls} platformStation={platformStation}
        />
      </Canvas>
      )}

      <div className="v3-hud">
        {Object.entries(VIEWS).map(([k, label]) => (
          <button key={k} className={`v3-btn ${view === k ? 'on' : ''}`} onClick={() => setView(k)}>
            {label}
          </button>
        ))}
        <span className="v3-sep" />
        <button className="v3-btn" onClick={() => setPlaying((v) => !v)}>
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        {[2, 6, 20, 60].map((s) => (
          <button key={s} className={`v3-btn ${speed === s ? 'on' : ''}`} onClick={() => setSpeed(s)}>
            {s}×
          </button>
        ))}
        <span className="v3-sep" />
        <button className={`v3-btn ${labels ? 'on' : ''}`} onClick={() => setLabels((v) => !v)}>
          Labels
        </button>
        <span className="v3-clock">{clockLabel}</span>
      </div>

      <div className="v3-trainpick">
        {profiles.map((p) => {
          const d = lerp(p.delayB, p.delayO, progress)
          return (
            <button
              key={p.no}
              className={`v3-chip ${focusNo === p.no ? 'on' : ''}`}
              style={{ borderColor: p.color }}
              onClick={() => setFocusNo(focusNo === p.no ? null : p.no)}
              title={`${p.name} — click to chase`}
            >
              <span className="v3-dot" style={{ background: p.color }} />
              {p.no}
              <span className={d > 5 ? 'bad' : 'ok'}>{d > 0.5 ? `+${Math.round(d)}m` : 'RT'}</span>
            </button>
          )
        })}
      </div>

      {view !== 'platform' && (
      <div className="v3-note">
        Schematic 3D · 1 unit = 1 km, train/platform sizes exaggerated for visibility ·
        trains positioned from the <b>simulated timeline</b>; a train shunted onto the
        <b> loop line</b> is one the optimizer is holding so a faster train can overtake
      </div>
      )}
    </div>
  )
}
