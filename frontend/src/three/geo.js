/*
 * Geometry helpers shared by the 3D scenes.
 *
 * Everything here is derived from data the API already returns — node lat/lon,
 * edge kind/length, and the exit set — so the 3D view is a projection of the
 * same graph the simulation runs on, not a hand-built model.
 *
 * The one inference is VERTICAL: the API has no level/z data, so we infer a
 * two-level station (ground + foot-over-bridge deck) by counting how many
 * `steps` edges you must cross to reach a node from a platform. That is a
 * schematic, and the UI labels it as such.
 */

const R_LAT = 110540 // metres per degree latitude
const R_LON = 111320 // metres per degree longitude at the equator

/** lat/lon -> local metres, x = east, z = south (so -z is north / "up" on screen). */
export function projectNodes(nodes, center) {
  const kx = R_LON * Math.cos((center.lat * Math.PI) / 180)
  const out = {}
  for (const n of nodes) {
    out[n.id ?? n.node] = {
      x: (n.lon - center.lon) * kx,
      z: -(n.lat - center.lat) * R_LAT,
    }
  }
  return out
}

/** Undirected adjacency: id -> [{ to, edge }]. */
export function buildAdjacency(nodes, edges) {
  const adj = {}
  for (const n of nodes) adj[n.id ?? n.node] = []
  for (const e of edges) {
    if (!adj[e.u] || !adj[e.v]) continue
    adj[e.u].push({ to: e.v, edge: e })
    adj[e.v].push({ to: e.u, edge: e })
  }
  return adj
}

/**
 * Level per node = minimum number of `steps` edges crossed to reach it from any
 * platform node, capped at `maxLevel`. 0-1 BFS (deque) so the result is the true
 * minimum and is deterministic regardless of input order.
 *
 * Platforms and anything step-free from them land on level 0 (ground); anything
 * you must climb a staircase to reach lands on level 1 (the FOB deck).
 */
export function assignLevels(nodes, edges, platformIds, maxLevel = 1) {
  const adj = buildAdjacency(nodes, edges)
  const level = {}
  for (const n of nodes) level[n.id ?? n.node] = Infinity

  const deque = []
  for (const id of platformIds) {
    if (level[id] === undefined) continue
    level[id] = 0
    deque.push(id)
  }

  while (deque.length) {
    const cur = deque.shift()
    for (const { to, edge } of adj[cur] || []) {
      const w = edge.kind === 'steps' ? 1 : 0
      const cand = Math.min(level[cur] + w, maxLevel)
      if (cand < level[to]) {
        level[to] = cand
        if (w === 0) deque.unshift(to) // zero-weight: same frontier
        else deque.push(to)
      }
    }
  }

  // Nodes in a disconnected component never got reached — put them on ground.
  for (const k of Object.keys(level)) if (!isFinite(level[k])) level[k] = 0
  return level
}

/**
 * Shortest walking distance (metres) from every node to the nearest exit.
 * Used to give the crowd particles a coherent direction of travel — the same
 * "route to your nearest exit" rule the simulation itself uses — so the
 * animation flows the way the model says people flow.
 */
export function distanceToExits(nodes, edges, exitIds) {
  const adj = buildAdjacency(nodes, edges)
  const dist = {}
  for (const n of nodes) dist[n.id ?? n.node] = Infinity

  // Simple binary-heap-free Dijkstra: fine for ~250 nodes.
  const pq = []
  for (const id of exitIds) {
    if (dist[id] === undefined) continue
    dist[id] = 0
    pq.push({ id, d: 0 })
  }
  while (pq.length) {
    pq.sort((a, b) => a.d - b.d)
    const { id, d } = pq.shift()
    if (d > dist[id]) continue
    for (const { to, edge } of adj[id] || []) {
      const nd = d + (edge.length_m || 1)
      if (nd < dist[to]) { dist[to] = nd; pq.push({ id: to, d: nd }) }
    }
  }
  return dist
}

/**
 * Dominant axis of a point cloud (radians, in the xz plane) via 2x2 PCA.
 * Platform nodes lie across the width of the station, so the axis through them
 * is perpendicular to the tracks — which is how we derive track direction
 * without any extra data.
 */
export function principalAxis(points) {
  const n = points.length
  if (n < 2) return 0
  let mx = 0, mz = 0
  for (const p of points) { mx += p.x; mz += p.z }
  mx /= n; mz /= n
  let sxx = 0, szz = 0, sxz = 0
  for (const p of points) {
    const dx = p.x - mx, dz = p.z - mz
    sxx += dx * dx; szz += dz * dz; sxz += dx * dz
  }
  // Principal eigenvector angle of [[sxx,sxz],[sxz,szz]].
  return 0.5 * Math.atan2(2 * sxz, sxx - szz)
}

export function centroid(points) {
  if (!points.length) return { x: 0, z: 0 }
  let x = 0, z = 0
  for (const p of points) { x += p.x; z += p.z }
  return { x: x / points.length, z: z / points.length }
}

/** Fruin LOS bands as linear RGB triples, matching los.js exactly. */
export const LOS_RGB = {
  A: [0.18, 0.80, 0.44],
  C: [0.80, 0.86, 0.22],
  D: [1.00, 0.70, 0.00],
  E: [0.98, 0.55, 0.00],
  F: [0.90, 0.22, 0.21],
}

export function losRgb(density) {
  if (density < 1.0) return LOS_RGB.A
  if (density < 2.0) return LOS_RGB.C
  if (density < 3.5) return LOS_RGB.D
  if (density < 5.0) return LOS_RGB.E
  return LOS_RGB.F
}

export const LEVEL_HEIGHT = 7.5 // metres between ground and the FOB deck
