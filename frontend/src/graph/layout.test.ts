import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { RunGraphSchema } from '@/gen/originweave/v1/originweave_pb'
import { hasPosition, layoutRunGraph } from '@/graph/layout'
import { edge, factSummary, intent, vec2 } from '@/test/fixtures'

function graph(edges: { source: string; target: string }[]) {
  return create(RunGraphSchema, {
    origin: factSummary({ id: 'origin', kind: 'origin' }),
    goal: factSummary({ id: 'goal', kind: 'goal' }),
    facts: [
      factSummary({ id: 'f1', role: 'main-claim' }),
      factSummary({ id: 'c1', kind: 'citation' }),
      factSummary({ id: 'c2', kind: 'citation' }),
    ],
    intents: [],
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

describe('layoutRunGraph', () => {
  it('places every node and never overlaps', () => {
    const points = layoutRunGraph(
      graph([
        { source: 'origin', target: 'f1' },
        { source: 'f1', target: 'c1' },
        { source: 'f1', target: 'c2' },
      ]),
    )
    expect(points.size).toBe(5) // origin + goal + 3 facts
    const keys = [...points.values()].map((p) => `${p.x},${p.y}`)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('ranks the dagre chain top-down (origin above claims above citations)', () => {
    const points = layoutRunGraph(
      graph([
        { source: 'origin', target: 'f1' },
        { source: 'f1', target: 'c1' },
      ]),
    )
    const origin = points.get('origin')!
    const f1 = points.get('f1')!
    const c1 = points.get('c1')!
    expect(f1.y).toBeGreaterThan(origin.y)
    expect(c1.y).toBeGreaterThan(f1.y)
  })

  it('lays out intents together with facts', () => {
    const detail = create(RunGraphSchema, {
      origin: factSummary({ id: 'origin', kind: 'origin' }),
      facts: [factSummary({ id: 'f1', role: 'main-claim' })],
      intents: [intent({ id: 'i1', from: 'f1' })],
      edges: [edge({ id: 'e1', source: 'origin', target: 'f1' })],
    })
    const points = layoutRunGraph(detail)
    expect(points.get('i1')).toBeDefined()
  })

  it('honours explicit positions verbatim and fills only the gaps', () => {
    const detail = create(RunGraphSchema, {
      origin: factSummary({ id: 'origin', kind: 'origin', position: vec2(30, 30) }),
      goal: factSummary({ id: 'goal', kind: 'goal' }),
      facts: [factSummary({ id: 'f1', position: vec2(400, 40) })],
    })
    const points = layoutRunGraph(detail)
    // Explicit (non-zero) coordinates are kept verbatim...
    expect(points.get('origin')).toEqual({ x: 30, y: 30 })
    expect(points.get('f1')).toEqual({ x: 400, y: 40 })
    // ...while a node with no position gets a dagre point (not the default 0,0).
    const goal = points.get('goal')!
    expect(goal.x !== 0 || goal.y !== 0).toBe(true)
  })

  it('lays out a disconnected board without stacking nodes', () => {
    const detail = create(RunGraphSchema, {
      origin: factSummary({ id: 'origin', kind: 'origin' }),
      goal: factSummary({ id: 'goal', kind: 'goal' }),
      facts: ['u1', 'u2', 'u3', 'u4', 'u5'].map((id) => factSummary({ id })),
    })
    const points = layoutRunGraph(detail)
    const keys = [...points.values()].map((p) => `${p.x},${p.y}`)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('returns an empty map without nodes', () => {
    expect(layoutRunGraph(create(RunGraphSchema, {})).size).toBe(0)
  })

  it('is deterministic for the same input', () => {
    const input = graph([{ source: 'origin', target: 'f1' }])
    expect(layoutRunGraph(input)).toEqual(layoutRunGraph(input))
  })
})
