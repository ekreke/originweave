import { MarkerType, type Edge, type Node } from '@xyflow/react'

import type { Fact, RunDetail } from '@/gen/originweave/v1/originweave_pb'
import { hasPosition, layoutRunDetail } from '@/graph/layout'

// Pure mapping from the proto RunDetail contract to React Flow nodes/edges.
// Following dashboard.md §2, Facts are double-encoded by kind (shape + colour)
// and Intents are rendered as question-mark badges. No server calls here.

export type FactShape =
  'ring' | 'square' | 'triangle' | 'diamond' | 'dashed-box' | 'hexagon' | 'warning-triangle'

export type IntentVariant = 'open' | 'claimed' | 'done' | 'dropped' | 'awaiting_human'

export interface FactNodeData extends Record<string, unknown> {
  fact: Fact
  shape: FactShape
  /** CSS custom-property name holding the kind colour, e.g. `--c-k-fact`. */
  color: string
  /** Short, single-line preview for the node label (the full text is in the Inspector). */
  preview: string
}

export interface IntentNodeData extends Record<string, unknown> {
  intent: RunDetail['intents'][number]
  variant: IntentVariant
}

export interface GraphEdgeData extends Record<string, unknown> {
  relation: string
  note: string
}

export type FactNode = Node<FactNodeData, 'fact'>
export type IntentNode = Node<IntentNodeData, 'intent'>
export type GraphNode = FactNode | IntentNode
export type GraphEdge = Edge<GraphEdgeData>

export interface GraphModel {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

const FACT_SHAPES: Record<string, FactShape> = {
  origin: 'ring',
  goal: 'ring',
  fact: 'square',
  citation: 'triangle',
  source: 'diamond',
  boundary: 'dashed-box',
  compare: 'hexagon',
  deviation: 'warning-triangle',
}

// dashboard.md §2 fixes main-chain / dependency / decomposes; the remaining
// semantic and structural edges get non-conflicting line styles.
const EDGE_DASH: Record<string, string | undefined> = {
  'main-chain': undefined,
  dependency: '6 3',
  'goal-derived': '4 2 1 2',
  decomposes: '1 3',
  spawns: '1 3',
  resolves: '1 3',
}

const INTENT_VARIANTS: Record<string, IntentVariant> = {
  open: 'open',
  claimed: 'claimed',
  done: 'done',
  dropped: 'dropped',
  awaiting_human: 'awaiting_human',
}

// Deterministic placement for Intents, which carry no position in the proto
// contract: anchor each one just below its `from` fact, stacked in id order.
const INTENT_ANCHOR_DX = -90
const INTENT_ANCHOR_DY = 96
const INTENT_GAP = 56
const UNANCHORED_DX = -270

export function factShape(kind: string): FactShape {
  return Object.hasOwn(FACT_SHAPES, kind) ? FACT_SHAPES[kind] : 'square'
}

export function factColor(kind: string): string {
  return Object.hasOwn(FACT_SHAPES, kind) ? `--c-k-${kind}` : '--c-k-fact'
}

export function intentVariant(status: string): IntentVariant {
  return Object.hasOwn(INTENT_VARIANTS, status) ? INTENT_VARIANTS[status] : 'open'
}

export function edgeDash(relation: string): string | undefined {
  return Object.hasOwn(EDGE_DASH, relation) ? EDGE_DASH[relation] : undefined
}

// Codepoint compare (not localeCompare) keeps intent stacking deterministic
// across environments.
function byId(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

// Node labels are previews: a long claim/goal must not blow up the canvas. Newlines and
// runs of whitespace collapse to one line; the node carries the full text in its title
// and the Inspector shows it verbatim. Sliced by code point (not UTF-16 unit) so a
// surrogate pair at the cut survives intact.
export const PREVIEW_MAX = 80

export function shortLabel(text: string, max = PREVIEW_MAX): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  const chars = Array.from(flat)
  if (chars.length <= max) return flat
  return `${chars.slice(0, max).join('').trimEnd()}…`
}

export function runDetailToGraph(detail: RunDetail): GraphModel {
  const nodes: GraphNode[] = []
  const anchors = new Map<string, { x: number; y: number }>()
  // Positions are server-provided; when a live run carries none, fill the gaps with a
  // deterministic layering so nodes do not all stack at (0,0).
  const fallback = layoutRunDetail(detail)

  const pushFact = (f: Fact | undefined) => {
    if (!f) return
    const position = hasPosition(f.position)
      ? { x: f.position!.x, y: f.position!.y }
      : (fallback.get(f.id) ?? { x: 0, y: 0 })
    anchors.set(f.id, position)
    nodes.push({
      id: f.id,
      type: 'fact',
      position,
      data: {
        fact: f,
        shape: factShape(f.kind),
        color: factColor(f.kind),
        preview: shortLabel(f.label),
      },
    })
  }

  pushFact(detail.origin)
  pushFact(detail.goal)
  for (const f of detail.facts) pushFact(f)

  const groups = new Map<string, RunDetail['intents']>()
  for (const it of [...detail.intents].sort(byId)) {
    const list = groups.get(it.from) ?? []
    list.push(it)
    groups.set(it.from, list)
  }

  let unanchored = 0
  for (const [from, intents] of groups) {
    const anchor = anchors.get(from)
    intents.forEach((it, index) => {
      const position = anchor
        ? { x: anchor.x + INTENT_ANCHOR_DX, y: anchor.y + INTENT_ANCHOR_DY + index * INTENT_GAP }
        : { x: UNANCHORED_DX, y: unanchored++ * INTENT_GAP }
      nodes.push({
        id: it.id,
        type: 'intent',
        position,
        data: { intent: it, variant: intentVariant(it.status) },
      })
    })
  }

  const edges: GraphEdge[] = detail.edges.map((e) => {
    const dash = edgeDash(e.relation)
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed },
      ...(dash ? { style: { strokeDasharray: dash } } : {}),
      data: { relation: e.relation, note: e.note },
    }
  })

  return { nodes, edges }
}
