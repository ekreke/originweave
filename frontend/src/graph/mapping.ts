import { MarkerType, type Edge, type Node } from '@xyflow/react'

import type { FactSummary, Intent, RunGraph } from '@/gen/originweave/v1/originweave_pb'
import { layoutRunGraph } from '@/graph/layout'

// Pure mapping from the proto RunGraph contract to React Flow nodes/edges.
// Following dashboard.md §2, Facts are compact cards colour-coded by kind
// (colour tokens in tokens.css) and Intents are status-toned mini cards. No
// server calls here.

export type IntentVariant = 'open' | 'claimed' | 'done' | 'dropped' | 'awaiting_human'

export interface FactNodeData extends Record<string, unknown> {
  summary: FactSummary
  /** CSS custom-property name holding the kind colour, e.g. `--c-k-fact`. */
  color: string
  /** Short, single-line-block preview (the full text is in the Inspector). */
  preview: string
  /** Injected by GraphCanvas: keyboard activation (Enter/Space) on the card. */
  onSelect?: (id: string) => void
}

export interface IntentNodeData extends Record<string, unknown> {
  intent: Intent
  variant: IntentVariant
  preview: string
  /** Injected by GraphCanvas: keyboard activation (Enter/Space) on the card. */
  onSelect?: (id: string) => void
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

// dashboard.md §2: kind -> colour token (compact cards, no shape clipping).
const FACT_KINDS: Record<string, string> = {
  origin: '--c-k-origin',
  goal: '--c-k-goal',
  fact: '--c-k-fact',
  citation: '--c-k-citation',
  source: '--c-k-source',
  boundary: '--c-k-boundary',
  compare: '--c-k-compare',
  deviation: '--c-k-deviation',
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

export function factColor(kind: string): string {
  return Object.hasOwn(FACT_KINDS, kind) ? FACT_KINDS[kind] : '--c-k-fact'
}

export function intentVariant(status: string): IntentVariant {
  return Object.hasOwn(INTENT_VARIANTS, status) ? INTENT_VARIANTS[status] : 'open'
}

export function edgeDash(relation: string): string | undefined {
  return Object.hasOwn(EDGE_DASH, relation) ? EDGE_DASH[relation] : undefined
}

// Edge emphasis rules: with a selection, incident edges highlight (`edge-active`)
// and the rest dim (`edge-dim`); without one, the frozen main-chain gets a subtle
// accent (`edge-main`). Pure so the console canvas stays presentation-only.
export function classifyEdges(edges: Edge[], selectedId: string | null | undefined): Edge[] {
  const incident =
    selectedId == null
      ? null
      : new Set(
          edges
            .filter((edge) => edge.source === selectedId || edge.target === selectedId)
            .map((edge) => edge.id),
        )
  return edges.map((edge) => {
    if (incident !== null) {
      const active = incident.has(edge.id)
      return { ...edge, className: active ? 'edge-active' : 'edge-dim' }
    }
    return edge.data?.relation === 'main-chain' ? { ...edge, className: 'edge-main' } : edge
  })
}

// Codepoint compare (not localeCompare) keeps node ordering deterministic
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

export function runGraphToFlow(detail: RunGraph): GraphModel {
  const nodes: GraphNode[] = []
  // Positions: explicit Fact.position wins per node, dagre layers the rest.
  const layout = layoutRunGraph(detail)
  const at = (id: string) => layout.get(id) ?? { x: 0, y: 0 }

  const pushFact = (summary: FactSummary | undefined) => {
    if (!summary) return
    nodes.push({
      id: summary.id,
      type: 'fact',
      position: at(summary.id),
      data: {
        summary,
        color: factColor(summary.kind),
        preview: shortLabel(summary.label),
      },
    })
  }

  pushFact(detail.origin)
  pushFact(detail.goal)
  for (const fact of [...detail.facts].sort(byId)) pushFact(fact)

  for (const intent of [...detail.intents].sort(byId)) {
    nodes.push({
      id: intent.id,
      type: 'intent',
      position: at(intent.id),
      data: { intent, variant: intentVariant(intent.status), preview: shortLabel(intent.question) },
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
