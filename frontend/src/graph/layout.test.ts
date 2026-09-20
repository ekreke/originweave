import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { RunDetailSchema } from '@/gen/originweave/v1/originweave_pb'
import { LAYOUT_COL_W, LAYOUT_ROW_H, layoutRunDetail } from '@/graph/layout'
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

describe('layoutRunDetail', () => {
  it('places origin/goal and layers facts left-to-right by BFS depth', () => {
    const points = layoutRunDetail(
      detail([
        { source: 'origin', target: 'f1' },
        { source: 'f1', target: 'c1' },
        { source: 'f1', target: 'c2' },
      ]),
    )
    expect(points.get('origin')).toEqual({ x: 0, y: 0 })
    expect(points.get('goal')).toEqual({ x: 0, y: -LAYOUT_ROW_H })
    expect(points.get('f1')?.x).toBe(LAYOUT_COL_W) // depth 1
    expect(points.get('c1')?.x).toBe(2 * LAYOUT_COL_W) // depth 2
    expect(points.get('c2')?.x).toBe(2 * LAYOUT_COL_W)
    // Siblings occupy separate vertical lanes, so cards never overlap.
    expect(points.get('c1')?.y).not.toBe(points.get('c2')?.y)
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

  it('spreads a wide unreachable layer without collisions', () => {
    const facts = ['u1', 'u2', 'u3', 'u4', 'u5'].map((id) => fact({ id }))
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      goal: fact({ id: 'goal', kind: 'goal' }),
      facts,
    })
    const points = layoutRunDetail(detail)
    const row = ['u1', 'u2', 'u3', 'u4', 'u5'].map((id) => points.get(id)!)
    expect(new Set(row.map((p) => p.x)).size).toBe(1)
    expect(new Set(row.map((p) => p.y)).size).toBe(row.length)
  })

  it('is deterministic and handles unreachable facts (default depth 1)', () => {
    const input = detail([{ source: 'origin', target: 'f1' }]) // c1/c2 unreachable
    const a = layoutRunDetail(input)
    expect(a.get('c1')?.x).toBe(LAYOUT_COL_W)
    expect(layoutRunDetail(input)).toEqual(a)
  })
})
