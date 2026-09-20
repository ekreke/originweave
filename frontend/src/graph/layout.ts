import type { RunDetail } from '@/gen/originweave/v1/originweave_pb'

// Deterministic, left-to-right provenance layout. Render-side positions are deliberately
// recomputed so legacy server coordinates cannot reintroduce a dense top-down graph.
export const LAYOUT_ROW_H = 168
// A Fact card (172px) plus an Intent card (156px) must fit between consecutive
// provenance layers when an intent resolves into the next Fact.
export const LAYOUT_COL_W = 400

export interface LayoutPoint {
  x: number
  y: number
}

// Provenance relations that express depth from a claim; structural/semantic edges the
// reducer derives. Relation types outside this set do not move a node down a row.
const DEPTH_RELATIONS = new Set(['main-chain', 'dependency', 'decomposes'])

function byId(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

/**
 * Lay a provenance DAG left-to-right: `origin` anchors the first column and Facts advance
 * by BFS depth. Siblings occupy generously spaced vertical lanes in id order. The result
 * is a pure function of the input, so two renders (or a replay) place nodes identically.
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
      points.set(id, {
        x: row * LAYOUT_COL_W,
        y: (index - (ids.length - 1) / 2) * LAYOUT_ROW_H,
      })
    })
  }
  return points
}
