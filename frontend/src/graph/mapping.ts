import { MarkerType, type Edge, type Node } from '@xyflow/react'

import type { Fact, RunDetail } from '@/gen/originweave/v1/originweave_pb'
import { LAYOUT_ROW_H, layoutRunDetail } from '@/graph/layout'

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
  /** Compact question preview; the full text stays in the Inspector. */
  preview: string
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
const INTENT_LANE_OFFSET = LAYOUT_ROW_H
export const INTENT_GRID_ROWS = 8
export const INTENT_COL_W = 196
export const INTENT_ROW_H = 76
const INTENT_CARD_W = 156
const INTENT_CARD_H = 48

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

function factAriaLabel(fact: Fact, preview: string): string {
  const confidence = fact.confidence > 0 ? `，置信度 ${Math.round(fact.confidence * 100)}%` : ''
  return `${fact.kind} ${fact.id}：${preview}，状态 ${fact.status}${confidence}`
}

function intentAriaLabel(intent: RunDetail['intents'][number], preview: string): string {
  return `意图 ${intent.id}：${preview || '待处理意图'}，状态 ${intent.status}`
}

export function runDetailToGraph(detail: RunDetail): GraphModel {
  const nodes: GraphNode[] = []
  const anchors = new Map<string, { x: number; y: number }>()
  const layout = layoutRunDetail(detail)

  const pushFact = (f: Fact | undefined) => {
    if (!f) return
    const position = layout.get(f.id) ?? { x: 0, y: 0 }
    const preview = shortLabel(f.label)
    anchors.set(f.id, position)
    nodes.push({
      id: f.id,
      type: 'fact',
      position,
      ariaLabel: factAriaLabel(f, preview),
      data: {
        fact: f,
        shape: factShape(f.kind),
        color: factColor(f.kind),
        preview,
      },
    })
  }

  pushFact(detail.origin)
  pushFact(detail.goal)
  for (const f of detail.facts) pushFact(f)

  const bottomFactY = Math.max(0, ...[...anchors.values()].map((point) => point.y))
  const intentLaneY = bottomFactY + INTENT_LANE_OFFSET
  const groups = new Map<string, RunDetail['intents']>()
  for (const intent of [...detail.intents].sort(byId)) {
    const intents = groups.get(intent.from) ?? []
    intents.push(intent)
    groups.set(intent.from, intents)
  }
  // Intent cards sit in a bounded-height task lane below the evidence DAG. Each group
  // starts to the right of its `from` Fact. Group rectangles are packed into separate
  // lane bands whenever their horizontal ranges meet, avoiding dense overlap for large runs.
  const occupiedGroups: Array<{ x: number; y: number; width: number; height: number }> = []
  const orderedGroups = [...groups.entries()].sort(([a], [b]) => {
    const ax = anchors.get(a)?.x ?? 0
    const bx = anchors.get(b)?.x ?? 0
    return ax === bx ? byId({ id: a }, { id: b }) : ax - bx
  })
  for (const [from, intents] of orderedGroups) {
    const anchorX = anchors.get(from)?.x ?? 0
    const columns = Math.ceil(intents.length / INTENT_GRID_ROWS)
    const width = (columns - 1) * INTENT_COL_W + INTENT_CARD_W
    const height = (Math.min(intents.length, INTENT_GRID_ROWS) - 1) * INTENT_ROW_H + INTENT_CARD_H
    const x = anchorX + INTENT_COL_W
    let y = intentLaneY
    while (
      occupiedGroups.some(
        (group) =>
          x < group.x + group.width &&
          x + width > group.x &&
          y < group.y + group.height &&
          y + height > group.y,
      )
    ) {
      y += INTENT_ROW_H
    }
    occupiedGroups.push({ x, y, width, height })
    intents.forEach((intent, intentIndex) => {
      const column = Math.floor(intentIndex / INTENT_GRID_ROWS)
      const row = intentIndex % INTENT_GRID_ROWS
      const preview = shortLabel(intent.question, 56)
      nodes.push({
        id: intent.id,
        type: 'intent',
        position: { x: x + column * INTENT_COL_W, y: y + row * INTENT_ROW_H },
        ariaLabel: intentAriaLabel(intent, preview),
        data: {
          intent,
          variant: intentVariant(intent.status),
          preview,
        },
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
      className: `edge-${e.relation}`,
      ariaLabel: `${e.relation}: ${e.source} 到 ${e.target}`,
      ...(dash ? { style: { strokeDasharray: dash } } : {}),
      data: { relation: e.relation, note: e.note },
    }
  })

  return { nodes, edges }
}
