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
export function projectLL(lat, lon, center) {
  const kx = R_LON * Math.cos((center.lat * Math.PI) / 180)
  return { x: (lon - center.lon) * kx, z: -(lat - center.lat) * R_LAT }
}

export function projectNodes(nodes, center) {
  const out = {}
  for (const n of nodes) out[n.id ?? n.node] = projectLL(n.lat, n.lon, center)
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
 * Level per node. Two sources, in order of trust:
 *
 * 1. REAL OSM attributes — the graph builder carries bridge=yes / tunnel=yes /
 *    layer per edge as `level` (+1 FOB deck, -1 subway, 0 grade). A node's
 *    level comes from the non-stair edges that touch it; stairs are the
 *    transitions and vote only for nodes nothing else touches (mid-flight
 *    landings). Ground beats deck/tunnel so portals and stair feet stay at
 *    grade and the connecting span slopes.
 * 2. Fallback (fixtures without `level`): the old stair-count BFS inference.
 */
export function assignLevels(nodes, edges, platformIds, maxLevel = 1) {
  if (edges.some((e) => (e.level || 0) !== 0)) {
    const vote = {}
    const stairVote = {}
    for (const e of edges) {
      const lv = e.level || 0
      for (const id of [e.u, e.v]) {
        if (e.kind === 'steps') { (stairVote[id] ??= []).push(lv); continue }
        const v = (vote[id] ??= { deck: false, tunnel: false, ground: false })
        if (lv > 0) v.deck = true
        else if (lv < 0) v.tunnel = true
        else v.ground = true
      }
    }
    const level = {}
    const stairOnly = []
    for (const n of nodes) {
      const id = n.id ?? n.node
      const v = vote[id]
      if (v) level[id] = v.ground ? 0 : v.deck ? 1 : -1
      else {
        // Only stairs touch this node. Seed from the stair tags, then resolve
        // below — OSM tags a whole flight bridge=yes, so seeding alone leaves
        // the flight's loose end floating at deck height.
        const sv = stairVote[id] || [0]
        level[id] = sv.every((x) => x > 0) ? 1 : sv.every((x) => x < 0) ? -1 : 0
        stairOnly.push(id)
      }
    }

    // Resolve stair-only nodes so every flight actually descends:
    //  · a dead-end stair node is a stair FOOT — pin it to grade, else the
    //    whole flight renders flat at 13 m and the bridge looks unreachable;
    //  · interior landings relax to the mean of their neighbours (a mid-flight
    //    landing settles around half-height).
    if (stairOnly.length) {
      const adj = buildAdjacency(nodes, edges)
      for (const id of stairOnly) {
        if ((adj[id] || []).length <= 1) level[id] = 0
      }
      const pinned = new Set(stairOnly.filter((id) => (adj[id] || []).length <= 1))
      for (let pass = 0; pass < 4; pass++) {
        for (const id of stairOnly) {
          if (pinned.has(id)) continue
          const nb = adj[id] || []
          if (nb.length) level[id] = nb.reduce((a, x) => a + level[x.to], 0) / nb.length
        }
      }
    }
    return level
  }
  return assignLevelsByStairs(nodes, edges, platformIds, maxLevel)
}

function assignLevelsByStairs(nodes, edges, platformIds, maxLevel = 1) {
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

export const LEVEL_HEIGHT = 13  // FOB deck height — clears the platform canopies (7.4)
export const TUNNEL_DEPTH = 5   // subway passages sit this far below grade

/** Vertical position for a level: +1 deck, 0 grade, -1 subway. */
export function levelY(level) {
  if (!level) return 0
  return level > 0 ? level * LEVEL_HEIGHT : level * TUNNEL_DEPTH
}
