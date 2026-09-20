import type { RunDetail } from '@/gen/originweave/v1/originweave_pb'

// Deterministic fallback layout for runs whose Facts carry no `position` (dashboard.md
// §2: the position is recomputable on the render side). A live run writes no positions,
// so without this every node would stack at (0,0). Server-provided positions always win;
// this only fills the gaps (per node), so a partially-positioned run still works.

export const LAYOUT_ROW_H = 160
export const LAYOUT_COL_W = 220

export interface LayoutPoint {
  x: number
  y: number
}

// Provenance relations that express depth from a claim; structural/semantic edges the
// reducer derives. Relation types outside this set do not move a node down a row.
const DEPTH_RELATIONS = new Set(['main-chain', 'dependency', 'decomposes'])

/** True when a Fact carries a non-zero, server-provided position. */
export function hasPosition(position: { x?: number; y?: number } | undefined): boolean {
  return Boolean(position && (position.x !== 0 || position.y !== 0))
}

function byId(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

/**
 * Lay a provenance DAG out top-down: `origin` at the top, `goal` above it, facts in rows
 * by their BFS depth over provenance edges, spread horizontally in id order. Nodes in
 * the same row never share a coordinate. The result is a pure function of the input, so
 * two renders (or a replay) place nodes identically.
 */
export function layoutRunDetail(detail: RunDetail): Map<string, LayoutPoint> {
  const points = new Map<string, LayoutPoint>()
  if (detail.origin) points.set(detail.origin.id, { x: 0, y: 0 })
  if (detail.goal) points.set(detail.goal.id, { x: 0, y: -LAYOUT_ROW_H })

  const originId = detail.origin?.id
  const goalId = detail.goal?.id
  // `goal` is deliberately not a depth source: goal-derived edges do not express
  // provenance depth, so facts hanging off the goal fall back to depth 1.
  const facts = detail.facts.filter((f) => f.id !== originId && f.id !== goalId)
  const known = new Set<string>(facts.map((f) => f.id))
  if (originId) known.add(originId)

  const adjacency = new Map<string, string[]>()
  for (const edge of detail.edges) {
    if (!DEPTH_RELATIONS.has(edge.relation)) continue
    if (!known.has(edge.source) || !known.has(edge.target)) continue
    const list = adjacency.get(edge.source) ?? []
    list.push(edge.target)
    adjacency.set(edge.source, list)
  }

  // BFS depth from origin (depth 0); unreachable facts default to depth 1.
  const depth = new Map<string, number>()
  if (originId) depth.set(originId, 0)
  const queue = originId ? [originId] : []
  while (queue.length > 0) {
    const current = queue.shift()!
    const base = depth.get(current) ?? 0
    for (const next of (adjacency.get(current) ?? []).slice().sort()) {
      if (!depth.has(next)) {
        depth.set(next, base + 1)
        queue.push(next)
      }
    }
  }

  const rows = new Map<number, string[]>()
  for (const fact of [...facts].sort(byId)) {
    const row = depth.get(fact.id) ?? 1
    const list = rows.get(row) ?? []
    list.push(fact.id)
    rows.set(row, list)
  }
  for (const [row, ids] of rows) {
    ids.forEach((id, index) => {
      points.set(id, { x: (index - (ids.length - 1) / 2) * LAYOUT_COL_W, y: row * LAYOUT_ROW_H })
    })
  }
  return points
}
