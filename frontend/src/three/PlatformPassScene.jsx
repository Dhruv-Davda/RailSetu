/*
 * M2 — eye-level platform view: stand on the platform and watch the fleet pass.
 *
 * This is a SEPARATE scene from the corridor because the two need different
 * scales: the corridor works at 1 unit = 1 km, which makes a platform a 5 km
 * slab. Here 1 unit = 1 metre.
 *
 * The motion is data-driven, and it is the whole point of the view:
 *   · each train's speed is its OWN average speed on the section leaving this
 *     station, taken from the simulated timeline (Δkm / Δmin) — so under
 *     no-action every express is throttled to passenger speed and they crawl
 *     past nose-to-tail, and after rescheduling they tear through at line speed
 *   · a train the optimizer HOLDS here sits on the loop line while the trains
 *     overtaking it run through on the main
 *   · `progress` morphs between those two worlds, so the optimizer toggle is
 *     something you feel standing on the platform
 *
 * Playback is compressed — passes are spaced evenly instead of by real
 * timetable gaps — because the real gaps are tens of minutes of empty track.
 */
import { useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'

const COACH_LEN = 22
const MAIN_Z = 0
const PLAT_Z0 = 3.6
const PLAT_W = 12
const PLAT_CZ = PLAT_Z0 + PLAT_W / 2
const LOOP_Z = PLAT_Z0 + PLAT_W + 3.6
const TRACK_LEN = 2400
const WINDOW = 450          // metres either side of the platform we draw trains in
const SLOT_GAP = 20         // seconds between successive passes
const TAIL = 34             // seconds for the last train to clear

const lerp = (a, b, p) => a + (b - a) * p

/* ------------------------------------------------------------------ schedule */

/**
 * Build the pass list for one station: who comes through, how fast, and who is
 * being held on the loop. Speeds come from the timeline either side of this
 * station, so they carry the cascade / recovery signal.
 */
function buildPasses(profiles, stationKm, progress) {
  const rows = []
  for (const prof of profiles) {
    const i = prof.events.findIndex((e) => e.km === stationKm)
    if (i < 0) continue
    const here = prof.events[i]
    const next = prof.events[i + 1]

    const held = lerp(here.heldB, here.heldO, progress)
    // Average speed on the section leaving this station (km/min -> m/s).
    let mps = 22
    if (next) {
      const dkm = next.km - here.km
      const dtB = Math.max(0.5, next.arrB - here.depB)
      const dtO = Math.max(0.5, next.arrO - here.depO)
      const kmPerMin = lerp(dkm / dtB, dkm / dtO, progress)
      mps = Math.max(4, (kmPerMin * 1000) / 60)
    }
    rows.push({
      no: prof.no,
      name: prof.name,
      type: prof.type,
      color: prof.color,
      order: lerp(here.depB, here.depO, progress),
      held: held > 0.4,
      mps,
      coaches: prof.type === 'PASSENGER' ? 12 : 9,
    })
  }
  rows.sort((a, b) => a.order - b.order)

  // Held trains are parked, not passing — they don't consume a slot.
  let slot = 0
  for (const r of rows) r.slotT = r.held ? null : (slot++) * SLOT_GAP
  const cycle = Math.max(30, (slot - 1) * SLOT_GAP + TAIL)
  return { rows, cycle }
}

/* -------------------------------------------------------------------- pieces */

function Track({ z, bright = true }) {
  const sleepers = useMemo(() => {
    const out = []
    for (let x = -TRACK_LEN / 2; x < TRACK_LEN / 2; x += 12) out.push(x)
    return out
  }, [])
  return (
    <group position={[0, 0, z]}>
      <mesh position={[0, -0.28, 0]}>
        <boxGeometry args={[TRACK_LEN, 0.6, 6.2]} />
        <meshStandardMaterial color="#1b232f" roughness={0.98} />
      </mesh>
      {sleepers.map((x) => (
        <mesh key={x} position={[x, 0.02, 0]}>
          <boxGeometry args={[2.6, 0.16, 4.4]} />
          <meshStandardMaterial color="#2a2f36" roughness={0.95} />
        </mesh>
      ))}
      {[-0.7175, 0.7175].map((o) => (
        <mesh key={o} position={[0, 0.16, o]}>
          <boxGeometry args={[TRACK_LEN, 0.18, 0.14]} />
          <meshStandardMaterial
            color={bright ? '#9fb4cb' : '#6d8098'}
            metalness={0.9} roughness={0.25}
          />
        </mesh>
      ))}
    </group>
  )
}

function Platform({ code, name }) {
  const pillars = useMemo(
    () => Array.from({ length: 17 }, (_, i) => -320 + i * 40),
    [],
  )
  return (
    <group>
      {/* deck */}
      <mesh position={[0, 0.5, PLAT_CZ]} receiveShadow>
        <boxGeometry args={[820, 1.0, PLAT_W]} />
        <meshStandardMaterial color="#33506a" roughness={0.85} />
      </mesh>
      {/* tactile / safety strips on both faces */}
      {[PLAT_Z0 + 0.9, PLAT_Z0 + PLAT_W - 0.9].map((z) => (
        <mesh key={z} position={[0, 1.01, z]}>
          <boxGeometry args={[820, 0.04, 0.8]} />
          <meshBasicMaterial color="#f5c542" toneMapped={false} />
        </mesh>
      ))}
      {/* canopy */}
      <mesh position={[0, 8.4, PLAT_CZ]}>
        <boxGeometry args={[700, 0.5, PLAT_W + 5]} />
        <meshStandardMaterial color="#16324a" roughness={0.7} />
      </mesh>
      {pillars.map((x) => (
        <group key={x}>
          <mesh position={[x, 4.6, PLAT_CZ]}>
            <cylinderGeometry args={[0.3, 0.3, 7.6, 8]} />
            <meshStandardMaterial color="#22405a" metalness={0.3} roughness={0.6} />
          </mesh>
          {/* platform lamps under the canopy */}
          <mesh position={[x, 8.0, PLAT_CZ]}>
            <boxGeometry args={[3, 0.18, 0.6]} />
            <meshBasicMaterial color="#ffeccc" toneMapped={false} />
          </mesh>
          <pointLight position={[x, 7.4, PLAT_CZ]} distance={34} intensity={0.5} color="#ffe4bd" />
        </group>
      ))}
      {/* overhead line masts + contact wire over the main line */}
      {pillars.filter((_, i) => i % 2 === 0).map((x) => (
        <group key={`m${x}`}>
          <mesh position={[x, 4.2, -4.2]}>
            <cylinderGeometry args={[0.22, 0.22, 8.4, 6]} />
            <meshStandardMaterial color="#2b3d52" />
          </mesh>
          <mesh position={[x, 8.2, -2.2]} rotation={[0, 0, Math.PI / 2]}>
            <cylinderGeometry args={[0.1, 0.1, 4.4, 6]} />
            <meshStandardMaterial color="#2b3d52" />
          </mesh>
        </group>
      ))}
      <mesh position={[0, 6.6, MAIN_Z]}>
        <boxGeometry args={[TRACK_LEN, 0.06, 0.06]} />
        <meshBasicMaterial color="#4a5f78" toneMapped={false} />
      </mesh>
      {/* station name board */}
      <group position={[-40, 3.4, PLAT_CZ + PLAT_W / 2 - 0.4]}>
        <Html center zIndexRange={[4, 0]}>
          <div className="v3-board"><b>{code}</b><span>{name}</span></div>
        </Html>
      </group>
    </group>
  )
}

function Rake({ row, z }) {
  const { coaches, color, type } = row
  return (
    <group position={[0, 0, z]}>
      {Array.from({ length: coaches }, (_, i) => {
        const x = (i - (coaches - 1) / 2) * COACH_LEN
        const loco = i === 0
        return (
          <group key={i} position={[x, 2.5, 0]}>
            <mesh>
              <boxGeometry args={[COACH_LEN * 0.94, 3.7, 3.2]} />
              <meshStandardMaterial
                color={loco ? '#5b7f9e' : color}
                emissive={loco ? '#1b2f42' : color}
                emissiveIntensity={0.3}
                metalness={0.3} roughness={0.5}
              />
            </mesh>
            {/* lit window band */}
            <mesh position={[0, 0.85, 0]}>
              <boxGeometry args={[COACH_LEN * 0.8, 1.0, 3.26]} />
              <meshBasicMaterial color={loco ? '#20364a' : '#ffe6b8'} toneMapped={false} />
            </mesh>
            {/* livery stripe */}
            <mesh position={[0, -0.55, 0]}>
              <boxGeometry args={[COACH_LEN * 0.94, 0.3, 3.24]} />
              <meshBasicMaterial color="#f0d27a" toneMapped={false} />
            </mesh>
            {/* bogies */}
            {[-COACH_LEN * 0.29, COACH_LEN * 0.29].map((bx) => (
              <mesh key={bx} position={[bx, -2.05, 0]}>
                <boxGeometry args={[4.4, 1.0, 2.6]} />
                <meshStandardMaterial color="#15202c" roughness={0.9} />
              </mesh>
            ))}
            {loco && (
              <>
                <pointLight position={[-COACH_LEN * 0.5, 0.4, 0]} distance={90} intensity={4} color="#eaf4ff" />
                <mesh position={[-COACH_LEN * 0.48, 0.3, 0]}>
                  <boxGeometry args={[0.3, 0.7, 2.2]} />
                  <meshBasicMaterial color="#eaf4ff" toneMapped={false} />
                </mesh>
              </>
            )}
          </group>
        )
      })}
      {type === 'PASSENGER' && (
        <Html position={[0, 6.2, 0]} center zIndexRange={[3, 0]}>
          <div className="v3-train" style={{ borderColor: color, color }}>{row.no} HELD</div>
        </Html>
      )}
    </group>
  )
}

/* ------------------------------------------------------------------- runtime */

function Fleet({ passes, cycle, playing, rate, onTick }) {
  const groups = useRef([])
  const t = useRef(0)

  useFrame((_, dt) => {
    if (playing) {
      t.current += Math.min(dt, 0.05) * rate
      if (t.current > cycle) t.current -= cycle
    }
    onTick?.(t.current)

    passes.forEach((row, i) => {
      const g = groups.current[i]
      if (!g) return
      if (row.held) {
        // parked on the loop for the whole cycle
        g.visible = true
        g.position.x = 0
        return
      }
      const rakeLen = row.coaches * COACH_LEN
      const x = (t.current - row.slotT) * row.mps - WINDOW
      g.position.x = x
      g.visible = x > -WINDOW - rakeLen && x < WINDOW + rakeLen
    })
  })

  return (
    <group>
      {passes.map((row, i) => (
        <group key={row.no} ref={(el) => (groups.current[i] = el)}>
          <Rake row={row} z={row.held ? LOOP_Z : MAIN_Z} />
        </group>
      ))}
    </group>
  )
}

const CAM_POS = new THREE.Vector3(-58, 33, -76)
const CAM_TGT = new THREE.Vector3(58, 2, 9)

function PassRig({ controls }) {
  const { camera } = useThree()
  useFrame(() => {
    const c = controls.current
    camera.position.lerp(CAM_POS, 0.05)
    if (c) { c.target.lerp(CAM_TGT, 0.05); c.update() }
  })
  return null
}

/* ---------------------------------------------------------------------- root */

// Renders as a fragment: the parent owns the positioned wrapper so the corridor
// scene and this one can share one HUD.
export default function PlatformPassScene({
  station, profiles, progress = 0, playing = true, rate = 1,
}) {
  const controls = useRef()
  const { rows, cycle } = useMemo(
    () => buildPasses(profiles || [], station?.km ?? 0, progress),
    [profiles, station, progress],
  )

  if (!station || !rows.length) {
    return <div className="v3-loading">no passes at this station…</div>
  }

  const heldCount = rows.filter((r) => r.held).length
  const fastest = Math.max(...rows.filter((r) => !r.held).map((r) => r.mps), 0)

  return (
    <>
      <Canvas
        dpr={[1, 1.8]}
        camera={{ position: [-108, 16, -40], fov: 46, near: 0.5, far: 3000 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#0a0b0c']} />
        <fog attach="fog" args={['#0a0b0c', 240, 900]} />
        <ambientLight intensity={0.44} color="#9fc4e8" />
        <hemisphereLight args={['#3f6d96', '#070f18', 0.5]} />
        <directionalLight position={[-160, 220, 180]} intensity={0.62} color="#dceaff" />

        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.62, 0]}>
          <planeGeometry args={[TRACK_LEN, 1400]} />
          <meshStandardMaterial color="#0a121b" roughness={1} />
        </mesh>

        <Track z={MAIN_Z} />
        <Track z={LOOP_Z} bright={false} />
        <Platform code={station.code} name={station.name} />
        <Fleet passes={rows} cycle={cycle} playing={playing} rate={rate} />

        <OrbitControls
          ref={controls} makeDefault enableDamping dampingFactor={0.08}
          maxPolarAngle={Math.PI / 2.05} minDistance={8} maxDistance={520}
        />
        <PassRig controls={controls} />
      </Canvas>

      <div className="v3-note">
        Eye level on the {station.code} platform · 1 unit = 1 m ·
        each train runs at <b>its own simulated section speed</b>
        {fastest > 0 && <> (fastest here now <b>{Math.round(fastest * 3.6)} km/h</b>)</>}
        {heldCount > 0
          ? <> · <b>{heldCount} train held on the loop line</b> while the others overtake</>
          : <> · no train held here — everything is queued on the main line</>}
        {' '}· passes evenly spaced for playback (real gaps are tens of minutes)
      </div>
    </>
  )
}
