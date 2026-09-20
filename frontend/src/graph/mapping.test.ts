import { create } from '@bufbuild/protobuf'
import { describe, expect, it } from 'vitest'

import { RunGraphSchema } from '@/gen/originweave/v1/originweave_pb'
import { edgeDash, factColor, intentVariant, runGraphToFlow, shortLabel } from '@/graph/mapping'

import { edge, factSummary, sampleRunGraph, vec2 } from '@/test/fixtures'

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
