import type { RunDetail } from '@/gen/originweave/v1/originweave_pb'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { runDetailToGraph } from '@/graph/mapping'
import { useMemo } from 'react'
import type { XYPosition } from '@xyflow/react'

export function GraphTab({
  detail,
  onSelect,
  positions,
  onPositionChange,
  draggable,
}: {
  detail?: RunDetail
  onSelect?: (id: string | null) => void
  positions?: Record<string, XYPosition>
  onPositionChange?: (id: string, position: XYPosition) => void
  draggable?: boolean
}) {
  const graph = useMemo(() => (detail ? runDetailToGraph(detail) : undefined), [detail])
  const nodes = useMemo(
    () =>
      graph?.nodes.map((node) => ({ ...node, position: positions?.[node.id] ?? node.position })),
    [graph, positions],
  )
  return (
    <div className="graph-tab">
      <GraphCanvas
        nodes={nodes}
        edges={graph?.edges}
        onSelect={onSelect}
        onPositionChange={onPositionChange}
        draggable={draggable}
      />
    </div>
  )
}
