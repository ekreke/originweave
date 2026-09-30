import { MarkerType, type Edge, type Node } from '@xyflow/react'

import type {
  Entity,
  EntityGraph,
  FactSummary,
  Intent,
  Relation,
  RunGraph,
} from '@/gen/originweave/v1/originweave_pb'
import { layoutEntityGraph, layoutRunGraph } from '@/graph/layout'

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

export interface EntityNodeData extends Record<string, unknown> {
  entity: Entity
  /** CSS custom-property name holding the entity-type colour, e.g. `--c-e-person`. */
  color: string
  preview: string
  /** Injected by GraphCanvas: keyboard activation (Enter/Space) on the card. */
  onSelect?: (id: string) => void
}

export interface RelationEdgeData extends Record<string, unknown> {
  relation: Relation
}

export type FactNode = Node<FactNodeData, 'fact'>
export type IntentNode = Node<IntentNodeData, 'intent'>
export type EntityNode = Node<EntityNodeData, 'entity'>
export type GraphNode = FactNode | IntentNode
export type GraphEdge = Edge<GraphEdgeData>

export interface GraphModel {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface EntityGraphModel {
  nodes: EntityNode[]
  edges: Edge<RelationEdgeData>[]
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

// An inferred relation (no source evidence) renders dashed (dashboard.md §2 / M5d).
const INFERRED_DASH = '6 4'

// dashboard.md §2: entity type -> colour token (M5d).
const ENTITY_TYPES: Record<string, string> = {
  person: '--c-e-person',
  organization: '--c-e-organization',
  product: '--c-e-product',
  location: '--c-e-location',
  event: '--c-e-event',
  other: '--c-e-other',
}

// Relation ontology (product-overview.md §4): only forward types are stored, the
// renderer derives the reverse reading. `forward` reads source -> target; `reverse`
// reads target -> source (e.g. `subsidiary-of`: 隶属 / 母公司).
const RELATION_LABELS: Record<string, { forward: string; reverse: string }> = {
  'subsidiary-of': { forward: '隶属', reverse: '母公司' },
  'invests-in': { forward: '投资', reverse: '获投资' },
  acquires: { forward: '收购', reverse: '被收购' },
  'partners-with': { forward: '合作', reverse: '合作' },
  'competes-with': { forward: '竞争', reverse: '竞争' },
  supplies: { forward: '供应', reverse: '由…供应' },
  employs: { forward: '雇佣', reverse: '任职于' },
  founded: { forward: '创立', reverse: '由…创立' },
  owns: { forward: '拥有', reverse: '归…所有' },
  'located-in': { forward: '位于', reverse: '包含' },
  other: { forward: '相关', reverse: '相关' },
}

export function factColor(kind: string): string {
  return Object.hasOwn(FACT_KINDS, kind) ? FACT_KINDS[kind] : '--c-k-fact'
}

export function intentVariant(status: string): IntentVariant {
  return Object.hasOwn(INTENT_VARIANTS, status) ? INTENT_VARIANTS[status] : 'open'
}

export function entityColor(type: string): string {
  return Object.hasOwn(ENTITY_TYPES, type) ? ENTITY_TYPES[type] : '--c-e-other'
}

/** Human label for a relation type; `reverse` reads target -> source. */
export function relationLabel(type: string, reverse = false): string {
  const entry = Object.hasOwn(RELATION_LABELS, type) ? RELATION_LABELS[type] : undefined
  if (!entry) return type
  return reverse ? entry.reverse : entry.forward
}

export function edgeDash(relation: string): string | undefined {
  return Object.hasOwn(EDGE_DASH, relation) ? EDGE_DASH[relation] : undefined
}

// Edge emphasis rules: with a selection, incident edges highlight (`edge-active`)
// and the rest dim (`edge-dim`); without one, the frozen main-chain gets a subtle
// accent (`edge-main`). A selected relation edge (M5d) takes precedence: it is the
// focused edge and every other dims. Pure so the console canvas stays
// presentation-only.
export function classifyEdges(
  edges: Edge[],
  selectedId: string | null | undefined,
  selectedEdgeId?: string | null,
): Edge[] {
  if (selectedEdgeId != null) {
    return edges.map((edge) => ({
      ...edge,
      className: edge.id === selectedEdgeId ? 'edge-active' : 'edge-dim',
    }))
  }
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

// Pure mapping from the entity-relation graph (RunDetail.entity_graph, M5d) to
// React Flow nodes/edges. Entities colour-code by `type`; a relation edge shows its
// `type` as the label and is dashed when inferred (no source evidence).
export function entityGraphToFlow(graph: EntityGraph): EntityGraphModel {
  const layout = layoutEntityGraph(graph)
  const at = (id: string) => layout.get(id) ?? { x: 0, y: 0 }

  const nodes: EntityNode[] = [...graph.entities].sort(byId).map((entity) => ({
    id: entity.id,
    type: 'entity',
    position: at(entity.id),
    data: {
      entity,
      color: entityColor(entity.type),
      preview: shortLabel(entity.name),
    },
  }))

  const edges = [...graph.relations].sort(byId).map((relation) => ({
    id: relation.id,
    source: relation.source,
    target: relation.target,
    type: 'smoothstep',
    label: relation.type,
    markerEnd: { type: MarkerType.ArrowClosed },
    // Inferred relations carry no source: render dashed (dashboard.md §2 / M5d).
    ...(relation.inferred ? { style: { strokeDasharray: INFERRED_DASH } } : {}),
    data: { relation },
  }))

  return { nodes, edges }
}
