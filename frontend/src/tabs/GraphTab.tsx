import type { RunDetail } from '@/gen/originweave/v1/originweave_pb'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { runDetailToGraph } from '@/graph/mapping'

export function GraphTab({
  detail,
  onSelect,
  visibleIds,
}: {
  detail?: RunDetail
  onSelect?: (id: string | null) => void
  visibleIds?: Set<string>
}) {
  const graph = detail ? runDetailToGraph(detail, visibleIds) : undefined
  return <GraphCanvas nodes={graph?.nodes} edges={graph?.edges} onSelect={onSelect} />
}
