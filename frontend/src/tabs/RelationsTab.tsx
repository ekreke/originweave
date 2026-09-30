import { useMemo } from 'react'

import type { EntityGraph } from '@/gen/originweave/v1/originweave_pb'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { entityGraphToFlow } from '@/graph/mapping'

// RELATIONS tab (M5d): the entity-relation graph, reusing the provenance canvas
// with entity nodes and relation edges. Data comes from RunDetail.entity_graph
// (fetched on demand by the console); with no graph it stays an empty canvas.
export function RelationsTab({
  graph,
  runId,
  onSelect,
  selectedId,
  selectedEdgeId,
  onEdgeClick,
}: {
  graph?: EntityGraph
  runId?: string
  onSelect?: (id: string | null) => void
  selectedId?: string | null
  selectedEdgeId?: string | null
  onEdgeClick?: (id: string) => void
}) {
  // Memoised on the graph identity so an unchanged poll keeps the same nodes and the
  // canvas skips re-laying-out (mirrors GraphTab).
  const model = useMemo(() => (graph ? entityGraphToFlow(graph) : undefined), [graph])
  return (
    <GraphCanvas
      key={runId}
      variant="relations"
      nodes={model?.nodes}
      edges={model?.edges}
      onSelect={onSelect}
      selectedId={selectedId}
      selectedEdgeId={selectedEdgeId}
      onEdgeClick={onEdgeClick}
    />
  )
}
