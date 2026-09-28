import type { Node, NodeChange } from '@xyflow/react'
import { describe, expect, it } from 'vitest'

import { applyPositionOverrides, collectPositionChanges } from '@/graph/drag'

function node(id: string, x = 0, y = 0): Node {
  return { id, position: { x, y }, data: {} }
}

describe('collectPositionChanges', () => {
  it('keeps only position changes and skips valueless ones', () => {
    const changes = [
      { id: 'f1', type: 'position', position: { x: 10, y: 20 } },
      { id: 'f2', type: 'select', selected: true },
      { id: 'f3', type: 'position' },
      { id: 'f4', type: 'dimensions', dimensions: { width: 1, height: 1 } },
    ] as NodeChange[]

    const moved = collectPositionChanges(changes)

    expect([...moved]).toEqual([['f1', { x: 10, y: 20 }]])
  })

  it('returns an empty map for an empty batch', () => {
    expect(collectPositionChanges([]).size).toBe(0)
  })
})

describe('applyPositionOverrides', () => {
  it('returns the same array when nothing is overridden', () => {
    const nodes = [node('f1')]
    expect(applyPositionOverrides(nodes, new Map())).toBe(nodes)
  })

  it('overrides matching nodes and keeps the rest verbatim', () => {
    const nodes = [node('f1'), node('f2')]
    const merged = applyPositionOverrides(nodes, new Map([['f2', { x: 7, y: 8 }]]))

    expect(merged[0].position).toEqual({ x: 0, y: 0 })
    expect(merged[1].position).toEqual({ x: 7, y: 8 })
    // Untouched nodes keep identity so React Flow sees no spurious change.
    expect(merged[0]).toBe(nodes[0])
  })
})
