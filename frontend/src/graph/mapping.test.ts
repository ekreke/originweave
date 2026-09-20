import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { RunDetailSchema } from '@/gen/originweave/v1/originweave_pb'
import {
  edgeDash,
  factColor,
  factShape,
  INTENT_GRID_ROWS,
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

  it('lays out facts left-to-right and keeps intents in a separate lower lane', () => {
    const graph = runDetailToGraph(sampleRunDetail())

    const f1 = graph.nodes.find((n) => n.id === 'f1')
    const c1 = graph.nodes.find((n) => n.id === 'c1')
    expect(c1?.position.x).toBeGreaterThan(f1?.position.x ?? 0)

    // Intent cards are separated from both Fact lanes and each other.
    const i2 = graph.nodes.find((n) => n.id === 'i2')
    const i4 = graph.nodes.find((n) => n.id === 'i4')
    expect(i2?.position.y).toBeGreaterThan(f1?.position.y ?? 0)
    expect(i4?.position.x).toBeGreaterThan(i2?.position.x ?? 0)
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

  it('recomputes legacy explicit coordinates into the left-to-right layout', () => {
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin', position: vec2(30, 30) }),
      goal: fact({ id: 'goal', kind: 'goal' }),
      facts: [fact({ id: 'f1', position: vec2(400, 40) })],
    })
    const graph = runDetailToGraph(detail)
    expect(graph.nodes.find((n) => n.id === 'origin')?.position).toEqual({ x: 0, y: 0 })
    expect(graph.nodes.find((n) => n.id === 'f1')?.position.x).toBeGreaterThan(0)
    expect(graph.nodes.find((n) => n.id === 'goal')?.position.y).toBeLessThan(0)
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

  it('sets a compact question preview on intent cards', () => {
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      intents: [
        {
          id: 'i1',
          from: 'origin',
          status: 'open',
          question: '核对统计口径、对照组和指标定义。'.repeat(8),
        },
      ],
    })
    const node = runDetailToGraph(detail).nodes.find((item) => item.id === 'i1')
    const data = node?.data as { preview: string }
    expect(data.preview.endsWith('…')).toBe(true)
  })

  it('uses a multi-column task lane when a run has many intents', () => {
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      intents: Array.from({ length: INTENT_GRID_ROWS + 1 }, (_, index) => ({
        id: `i${String(index).padStart(2, '0')}`,
        from: 'origin',
        status: 'open',
        question: `问题 ${index}`,
      })),
    })
    const intents = runDetailToGraph(detail).nodes.filter((node) => node.type === 'intent')
    expect(intents).toHaveLength(INTENT_GRID_ROWS + 1)
    expect(intents[INTENT_GRID_ROWS]?.position.y).toBe(intents[0]?.position.y)
    expect(intents[INTENT_GRID_ROWS]?.position.x).toBeGreaterThan(intents[0]?.position.x ?? 0)
    expect(intents[0]?.position.x).toBeGreaterThan(0)
  })

  it('separates task grids whose source layers would otherwise overlap', () => {
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      facts: [fact({ id: 'f1' })],
      edges: [edge({ source: 'origin', target: 'f1', relation: 'main-chain' })],
      intents: [
        ...Array.from({ length: 17 }, (_, index) => ({
          id: `i${String(index).padStart(2, '0')}`,
          from: 'origin',
          status: 'open',
          question: `origin ${index}`,
        })),
        { id: 'i17', from: 'f1', status: 'open', question: 'child' },
      ],
    })
    const graph = runDetailToGraph(detail)
    const originIntent = graph.nodes.find((node) => node.id === 'i00')
    const childIntent = graph.nodes.find((node) => node.id === 'i17')
    expect(childIntent?.position.y).toBeGreaterThan(originIntent?.position.y ?? 0)
  })

  it('adds an accessible label that includes the node type, identity and status', () => {
    const graph = runDetailToGraph(sampleRunDetail())
    const node = graph.nodes.find((item) => item.id === 'f1')
    expect(node?.ariaLabel).toContain('fact f1')
    expect(node?.ariaLabel).toContain('状态 verified')
  })
})
