import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { RunDetailSchema } from '@/gen/originweave/v1/originweave_pb'
import {
  edgeDash,
  factColor,
  factShape,
  intentVariant,
  runDetailToGraph,
  shortLabel,
} from '@/graph/mapping'

import { edge, fact, sampleRunDetail, vec2 } from '@/test/fixtures'

describe('shortLabel', () => {
  it('collapses whitespace and keeps short labels intact', () => {
    expect(shortLabel('  hi  ')).toBe('hi')
    expect(shortLabel('a\n\nb   c')).toBe('a b c')
  })

  it('truncates a long label with an ellipsis', () => {
    const out = shortLabel('x'.repeat(200), 80)
    expect(out.endsWith('…')).toBe(true)
    expect(out.length).toBeLessThanOrEqual(81)
  })
})

describe('visual encoding', () => {
  it('maps fact kinds to shapes and colour tokens', () => {
    expect(factShape('origin')).toBe('ring')
    expect(factShape('goal')).toBe('ring')
    expect(factShape('fact')).toBe('square')
    expect(factShape('citation')).toBe('triangle')
    expect(factShape('source')).toBe('diamond')
    expect(factShape('boundary')).toBe('dashed-box')
    expect(factShape('compare')).toBe('hexagon')
    expect(factShape('deviation')).toBe('warning-triangle')
    expect(factShape('unknown')).toBe('square')

    expect(factColor('source')).toBe('--c-k-source')
    expect(factColor('unknown')).toBe('--c-k-fact')
  })

  it('maps relations to line styles', () => {
    expect(edgeDash('main-chain')).toBeUndefined()
    expect(edgeDash('dependency')).toBe('6 3')
    expect(edgeDash('decomposes')).toBe('1 3')
  })

  it('maps intent statuses to variants', () => {
    expect(intentVariant('awaiting_human')).toBe('awaiting_human')
    expect(intentVariant('dropped')).toBe('dropped')
    expect(intentVariant('whatever')).toBe('open')
  })
})

describe('runDetailToGraph', () => {
  it('produces an empty graph without data', () => {
    const graph = runDetailToGraph(create(RunDetailSchema, {}))
    expect(graph.nodes).toEqual([])
    expect(graph.edges).toEqual([])
  })

  it('maps facts, intents and edges from a RunDetail', () => {
    const graph = runDetailToGraph(sampleRunDetail())

    const factNodes = graph.nodes.filter((n) => n.type === 'fact')
    const intentNodes = graph.nodes.filter((n) => n.type === 'intent')
    expect(factNodes).toHaveLength(6) // origin + goal + 4 facts
    expect(intentNodes).toHaveLength(4)
    expect(graph.edges).toHaveLength(6)
    expect(graph.edges[1]?.data?.relation).toBe('goal-derived')
  })

  it('passes Fact positions through and anchors intents below their source', () => {
    const graph = runDetailToGraph(sampleRunDetail())

    const f1 = graph.nodes.find((n) => n.id === 'f1')
    expect(f1?.position).toEqual({ x: 0, y: 160 })

    // i1/i2/i3 are anchored to f1, stacked in id order; i4 to c1.
    const i2 = graph.nodes.find((n) => n.id === 'i2')
    expect(i2?.position).toEqual({ x: -90, y: 160 + 96 + 56 })
    const i4 = graph.nodes.find((n) => n.id === 'i4')
    expect(i4?.position).toEqual({ x: -90, y: 320 + 96 })
  })

  it('is deterministic for the same input', () => {
    const a = runDetailToGraph(sampleRunDetail())
    const b = runDetailToGraph(sampleRunDetail())
    expect(a).toEqual(b)
  })

  it('lays out a live run (no positions) without stacking nodes', () => {
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      goal: fact({ id: 'goal', kind: 'goal' }),
      facts: [fact({ id: 'f1', role: 'main-claim' }), fact({ id: 'c1', kind: 'citation' })],
      edges: [
        edge({ id: 'e1', source: 'origin', target: 'f1', relation: 'main-chain' }),
        edge({ id: 'e2', source: 'f1', target: 'c1', relation: 'dependency' }),
      ],
    })
    const positions = runDetailToGraph(detail).nodes.map((n) => `${n.position.x},${n.position.y}`)
    expect(new Set(positions).size).toBe(positions.length)
  })

  it('keeps an explicit position and falls back per missing node (mixed)', () => {
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin', position: vec2(30, 30) }),
      goal: fact({ id: 'goal', kind: 'goal' }),
      facts: [fact({ id: 'f1', position: vec2(400, 40) })],
    })
    const graph = runDetailToGraph(detail)
    // Explicit (non-zero) coordinates are kept verbatim...
    expect(graph.nodes.find((n) => n.id === 'origin')?.position).toEqual({ x: 30, y: 30 })
    expect(graph.nodes.find((n) => n.id === 'f1')?.position).toEqual({ x: 400, y: 40 })
    // ...while a node with no position gets its fallback (not the default 0,0).
    expect(graph.nodes.find((n) => n.id === 'goal')?.position).toEqual({ x: 0, y: -160 })
  })

  it('sets a short preview on each fact node', () => {
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      goal: fact({ id: 'goal', kind: 'goal', label: 'x'.repeat(200) }),
    })
    const node = runDetailToGraph(detail).nodes.find((n) => n.id === 'goal')
    const data = node?.data as { preview: string; fact: { label: string } }
    expect(data.preview.endsWith('…')).toBe(true)
    expect(data.fact.label).toHaveLength(200)
  })
})
