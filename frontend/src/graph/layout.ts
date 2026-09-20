import { Graph, layout as dagreLayout } from '@dagrejs/dagre'

import type { RunGraph } from '@/gen/originweave/v1/originweave_pb'

// Deterministic layered layout for the provenance DAG (dashboard.md §2). Dagre
// ranks the board top-down (origin -> claims -> citations, intents near their
// source); server-provided `Fact.position` still wins per node, dagre only fills
// the gaps (live runs carry no positions). A pure function of the input, so two
// renders -- or a replay step -- place nodes identically.

export const FACT_NODE_W = 190
export const FACT_NODE_H = 68
export const INTENT_NODE_W = 172
export const INTENT_NODE_H = 48

const NODESEP = 36
const RANKSEP = 84

export interface LayoutPoint {
  x: number
  y: number
}

/** True when a Fact carries a non-zero, server-provided position. */
export function hasPosition(position: { x?: number; y?: number } | undefined): boolean {
  return Boolean(position && (position.x !== 0 || position.y !== 0))
}

function byId(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

/**
 * Lay the run graph out with dagre: facts and intents become nodes, every edge a
 * dependency. Explicit (non-zero) `Fact.position` values are pinned verbatim;
 * everything else gets a dagre coordinate (top-left converted from dagre's
 * center). Unpinned nodes never share a coordinate (pinned duplicates are kept
 * as-is, mirroring the server's data).
 */
export function layoutRunGraph(detail: RunGraph): Map<string, LayoutPoint> {
  const points = new Map<string, LayoutPoint>()
  const sizes = new Map<string, { width: number; height: number }>()
  const pinned = new Set<string>()

  const pin = (fact: { id: string; position?: { x?: number; y?: number } } | undefined) => {
    if (!fact || !hasPosition(fact.position)) return
    const x = fact.position?.x ?? 0
    const y = fact.position?.y ?? 0
    points.set(fact.id, { x, y })
    pinned.add(fact.id)
  }

  const add = (id: string | undefined, width: number, height: number) => {
    if (id && !sizes.has(id)) sizes.set(id, { width, height })
  }

  pin(detail.origin)
  pin(detail.goal)
  add(detail.origin?.id, FACT_NODE_W, FACT_NODE_H)
  add(detail.goal?.id, FACT_NODE_W, FACT_NODE_H)
  for (const fact of detail.facts) {
    pin(fact)
    add(fact.id, FACT_NODE_W, FACT_NODE_H)
  }
  for (const intent of detail.intents) add(intent.id, INTENT_NODE_W, INTENT_NODE_H)
  if (sizes.size === 0) return points

  // Multigraph: several relations may connect the same pair (e.g. a goal-derived
  // edge on top of the main-chain), and dagre handles parallel edges fine.
  const g = new Graph({ multigraph: true })
  g.setGraph({ rankdir: 'TB', nodesep: NODESEP, ranksep: RANKSEP, marginx: 24, marginy: 24 })
  g.setDefaultEdgeLabel(() => ({}))
  // Pinned nodes join the graph too: dagre needs every edge endpoint, we simply
  // skip reading their computed coordinates below.
  for (const [id, size] of sizes) g.setNode(id, size)
  let seq = 0
  for (const edge of [...detail.edges].sort(byId)) {
    if (!sizes.has(edge.source) || !sizes.has(edge.target) || edge.source === edge.target) continue
    g.setEdge(edge.source, edge.target, {}, `e${seq++}`)
  }
  dagreLayout(g)

  for (const [id, size] of sizes) {
    if (pinned.has(id)) continue
    const node = g.node(id)
    // dagre returns the node center; React Flow wants the top-left corner.
    points.set(id, { x: node.x - size.width / 2, y: node.y - size.height / 2 })
  }
  return points
}
