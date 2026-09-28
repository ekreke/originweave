import type { Node, NodeChange, XYPosition } from '@xyflow/react'

// Session-local node dragging (dashboard.md §2): the user may reposition graph
// nodes, but the coordinates are a *view* concern -- they never travel back to the
// server (`Fact.position` stays "recomputable at render time"). These helpers are
// pure so the canvas merge logic is unit-testable without driving React Flow.

/**
 * User-dragged positions keyed by node id (authoritative for this run/session).
 * Overrides for a node that momentarily disappears (e.g. replay stepping back) are
 * kept, so a node that reappears returns to its dragged spot ("session memory").
 */
export type PositionOverrides = Map<string, XYPosition>

/**
 * Layer the dragged positions on top of freshly mapped nodes: a node the user has
 * moved keeps its position across polls / replay steps, everything else uses the
 * dagre coordinate. Returns the input array untouched when there is nothing to
 * override, so the caller can skip the extra allocation.
 */
export function applyPositionOverrides(nodes: Node[], overrides: PositionOverrides): Node[] {
  if (overrides.size === 0) return nodes
  return nodes.map((node) => {
    const position = overrides.get(node.id)
    return position ? { ...node, position } : node
  })
}

/**
 * Pull the position deltas out of a React Flow `onNodesChange` batch. Non-position
 * changes (select, dimensions, remove, ...) are ignored; a position change without
 * a value is skipped.
 */
export function collectPositionChanges(changes: NodeChange[]): PositionOverrides {
  const moved: PositionOverrides = new Map()
  for (const change of changes) {
    if (change.type === 'position' && change.position) {
      moved.set(change.id, change.position)
    }
  }
  return moved
}
