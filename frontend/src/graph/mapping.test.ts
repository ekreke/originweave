import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { RunDetailSchema } from '@/gen/originweave/v1/originweave_pb'
import { edgeDash, factColor, factShape, intentVariant, runDetailToGraph } from '@/graph/mapping'

import { sampleRunDetail } from '@/test/fixtures'

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

  it('hides nodes and drops dangling edges when given visibleIds', () => {
    const graph = runDetailToGraph(sampleRunDetail(), new Set(['origin', 'goal', 'f1']))

    const ids = graph.nodes.map((n) => n.id)
    expect(ids).toContain('origin')
    expect(ids).toContain('goal')
    expect(ids).toContain('f1')
    expect(ids).not.toContain('c1')
    expect(ids).not.toContain('i1')
    // No rendered edge points at a hidden node.
    for (const edge of graph.edges) {
      expect(ids).toContain(edge.source)
      expect(ids).toContain(edge.target)
    }
  })

  it('always keeps the anchors, even for an empty visible set', () => {
    const graph = runDetailToGraph(sampleRunDetail(), new Set())
    expect(graph.nodes.map((n) => n.id)).toEqual(['origin', 'goal'])
    expect(graph.edges).toEqual([])
  })
})
