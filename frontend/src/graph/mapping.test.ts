import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { EntityGraphSchema, RunGraphSchema } from '@/gen/originweave/v1/originweave_pb'
import {
  edgeDash,
  entityColor,
  entityGraphToFlow,
  factColor,
  intentVariant,
  relationLabel,
  runGraphToFlow,
  shortLabel,
} from '@/graph/mapping'

import {
  edge,
  entity,
  factSummary,
  relation,
  sampleEntityGraph,
  sampleRunGraph,
  vec2,
} from '@/test/fixtures'

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
  it('maps fact kinds to colour tokens', () => {
    expect(factColor('source')).toBe('--c-k-source')
    expect(factColor('goal')).toBe('--c-k-goal')
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

  it('maps entity types to colour tokens', () => {
    expect(entityColor('person')).toBe('--c-e-person')
    expect(entityColor('organization')).toBe('--c-e-organization')
    expect(entityColor('unknown')).toBe('--c-e-other')
  })

  it('derives forward and reverse relation labels', () => {
    expect(relationLabel('acquires')).toBe('收购')
    expect(relationLabel('acquires', true)).toBe('被收购')
    expect(relationLabel('subsidiary-of', true)).toBe('母公司')
    // Unknown types fall back to the raw type in both directions.
    expect(relationLabel('made-up', true)).toBe('made-up')
  })
})

describe('runGraphToFlow', () => {
  it('produces an empty graph without data', () => {
    const flow = runGraphToFlow(create(RunGraphSchema, {}))
    expect(flow.nodes).toEqual([])
    expect(flow.edges).toEqual([])
  })

  it('maps facts, intents and edges from a RunGraph', () => {
    const flow = runGraphToFlow(sampleRunGraph())

    const factNodes = flow.nodes.filter((n) => n.type === 'fact')
    const intentNodes = flow.nodes.filter((n) => n.type === 'intent')
    expect(factNodes).toHaveLength(6) // origin + goal + 4 facts
    expect(intentNodes).toHaveLength(4)
    expect(flow.edges).toHaveLength(6)
    expect(flow.edges[1]?.data?.relation).toBe('goal-derived')
  })

  it('keeps explicit fact positions and dagre-places intents', () => {
    const flow = runGraphToFlow(sampleRunGraph())

    const f1 = flow.nodes.find((n) => n.id === 'f1')
    expect(f1?.position).toEqual({ x: 0, y: 160 })

    // Intents have no server position; dagre gives each one a spot.
    const intentPositions = flow.nodes
      .filter((n) => n.type === 'intent')
      .map((n) => `${n.position.x},${n.position.y}`)
    expect(intentPositions).toHaveLength(4)
    expect(new Set(intentPositions).size).toBe(intentPositions.length)
  })

  it('is deterministic for the same input', () => {
    const a = runGraphToFlow(sampleRunGraph())
    const b = runGraphToFlow(sampleRunGraph())
    expect(a).toEqual(b)
  })

  it('lays out a live run (no positions) without stacking nodes', () => {
    const detail = create(RunGraphSchema, {
      origin: factSummary({ id: 'origin', kind: 'origin' }),
      goal: factSummary({ id: 'goal', kind: 'goal' }),
      facts: [
        factSummary({ id: 'f1', role: 'main-claim' }),
        factSummary({ id: 'c1', kind: 'citation' }),
      ],
      edges: [
        edge({ id: 'e1', source: 'origin', target: 'f1', relation: 'main-chain' }),
        edge({ id: 'e2', source: 'f1', target: 'c1', relation: 'dependency' }),
      ],
    })
    const positions = runGraphToFlow(detail).nodes.map((n) => `${n.position.x},${n.position.y}`)
    expect(new Set(positions).size).toBe(positions.length)
  })

  it('sets a short preview on each fact node and keeps the full label', () => {
    const detail = create(RunGraphSchema, {
      origin: factSummary({ id: 'origin', kind: 'origin' }),
      goal: factSummary({ id: 'goal', kind: 'goal', label: 'x'.repeat(200) }),
    })
    const node = runGraphToFlow(detail).nodes.find((n) => n.id === 'goal')
    const data = node?.data as { preview: string; summary: { label: string } }
    expect(data.preview.endsWith('…')).toBe(true)
    expect(data.summary.label).toHaveLength(200)
  })

  it('exposes an explicit position on the mapped node', () => {
    const detail = create(RunGraphSchema, {
      origin: factSummary({ id: 'origin', kind: 'origin', position: vec2(30, 30) }),
    })
    const node = runGraphToFlow(detail).nodes.find((n) => n.id === 'origin')
    expect(node?.position).toEqual({ x: 30, y: 30 })
  })
})

describe('entityGraphToFlow', () => {
  it('produces an empty graph without data', () => {
    const flow = entityGraphToFlow(create(EntityGraphSchema, {}))
    expect(flow.nodes).toEqual([])
    expect(flow.edges).toEqual([])
  })

  it('maps entities and relations, colour-coding by type', () => {
    const flow = entityGraphToFlow(sampleEntityGraph())

    expect(flow.nodes.map((n) => n.id)).toEqual(['n1', 'n2'])
    expect(flow.nodes.map((n) => n.type)).toEqual(['entity', 'entity'])
    const n1 = flow.nodes.find((n) => n.id === 'n1')
    expect((n1?.data as { color: string }).color).toBe('--c-e-organization')
    expect(flow.edges.map((e) => e.id)).toEqual(['r1', 'r2'])
    expect(flow.edges[0]?.label).toBe('acquires')
  })

  it('dashes inferred relations and keeps explicit positions', () => {
    const graph = create(EntityGraphSchema, {
      entities: [entity({ id: 'n1', position: vec2(10, 20) }), entity({ id: 'n2' })],
      relations: [
        relation({ id: 'r1', inferred: false }),
        relation({ id: 'r2', source: 'n2', target: 'n1', inferred: true }),
      ],
    })
    const flow = entityGraphToFlow(graph)

    expect(flow.edges[0]?.style?.strokeDasharray).toBeUndefined()
    expect(flow.edges[1]?.style?.strokeDasharray).toBe('6 4')
    expect(flow.nodes.find((n) => n.id === 'n1')?.position).toEqual({ x: 10, y: 20 })
  })

  it('is deterministic for the same input', () => {
    expect(entityGraphToFlow(sampleEntityGraph())).toEqual(entityGraphToFlow(sampleEntityGraph()))
  })
})
