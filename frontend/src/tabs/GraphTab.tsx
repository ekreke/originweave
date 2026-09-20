import { useMemo } from 'react'

import type { RunGraph } from '@/gen/originweave/v1/originweave_pb'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { runGraphToFlow } from '@/graph/mapping'

export function GraphTab({
  graph,
  onSelect,
  selectedId,
}: {
  graph?: RunGraph
  onSelect?: (id: string | null) => void
  selectedId?: string | null
}) {
  // Mapping is memoised on the graph identity: a poll that returns unchanged
  // data keeps the same reference (React Query structural sharing) and the
  // canvas skips re-laying-out every node.
  const model = useMemo(() => (graph ? runGraphToFlow(graph) : undefined), [graph])
  return (
    <GraphCanvas
      nodes={model?.nodes}
      edges={model?.edges}
      onSelect={onSelect}
      selectedId={selectedId}
    />
  )
}
