import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { RunDetailSchema } from '@/gen/originweave/v1/originweave_pb'
import { LAYOUT_ROW_H, hasPosition, layoutRunDetail } from '@/graph/layout'
import { edge, fact } from '@/test/fixtures'

function detail(edges: { source: string; target: string }[]) {
  return create(RunDetailSchema, {
    origin: fact({ id: 'origin', kind: 'origin' }),
    goal: fact({ id: 'goal', kind: 'goal' }),
    facts: [
      fact({ id: 'f1', role: 'main-claim' }),
      fact({ id: 'c1', kind: 'citation' }),
      fact({ id: 'c2', kind: 'citation' }),
    ],
    edges: edges.map((e, index) =>
      edge({ id: `e${index}`, source: e.source, target: e.target, relation: 'main-chain' }),
    ),
  })
}

describe('hasPosition', () => {
  it('treats an absent or zero position as "no position"', () => {
    expect(hasPosition(undefined)).toBe(false)
    expect(hasPosition({ x: 0, y: 0 })).toBe(false)
    expect(hasPosition({ x: 1, y: 0 })).toBe(true)
    expect(hasPosition({ x: 0, y: 5 })).toBe(true)
  })
})

describe('layoutRunDetail', () => {
  it('places origin/goal and layers facts by BFS depth', () => {
    const points = layoutRunDetail(
      detail([
        { source: 'origin', target: 'f1' },
        { source: 'f1', target: 'c1' },
        { source: 'f1', target: 'c2' },
      ]),
    )
    expect(points.get('origin')).toEqual({ x: 0, y: 0 })
    expect(points.get('goal')).toEqual({ x: 0, y: -LAYOUT_ROW_H })
    expect(points.get('f1')?.y).toBe(160) // depth 1
    expect(points.get('c1')?.y).toBe(320) // depth 2
    expect(points.get('c2')?.y).toBe(320)
    // Siblings spread horizontally, so they never overlap.
    expect(points.get('c1')?.x).not.toBe(points.get('c2')?.x)
  })

  it('never gives two nodes the same coordinate', () => {
    const points = layoutRunDetail(
      detail([
        { source: 'origin', target: 'f1' },
        { source: 'f1', target: 'c1' },
        { source: 'f1', target: 'c2' },
      ]),
    )
    const keys = [...points.values()].map((p) => `${p.x},${p.y}`)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('spreads a wide unreachable row without collisions', () => {
    const facts = ['u1', 'u2', 'u3', 'u4', 'u5'].map((id) => fact({ id }))
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      goal: fact({ id: 'goal', kind: 'goal' }),
      facts,
    })
    const points = layoutRunDetail(detail)
    const row = ['u1', 'u2', 'u3', 'u4', 'u5'].map((id) => points.get(id)!)
    expect(new Set(row.map((p) => p.x)).size).toBe(row.length)
    expect(new Set(row.map((p) => p.y)).size).toBe(1)
  })

  it('is deterministic and handles unreachable facts (default depth 1)', () => {
    const input = detail([{ source: 'origin', target: 'f1' }]) // c1/c2 unreachable
    const a = layoutRunDetail(input)
    expect(a.get('c1')?.y).toBe(160)
    expect(layoutRunDetail(input)).toEqual(a)
  })
})
