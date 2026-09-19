import { Background, ReactFlow, type Edge, type Node } from '@xyflow/react'

import { FactNode, IntentNode } from './nodes'

const nodeTypes = { fact: FactNode, intent: IntentNode }

const EMPTY_NODES: Node[] = []
const EMPTY_EDGES: Edge[] = []

export interface GraphCanvasProps {
  nodes?: Node[]
  edges?: Edge[]
  onSelect?: (id: string | null) => void
}

// Presentation-only canvas: nodes/edges are supplied by the caller (mapped from
// RunDetail) and positions come from the server. Without data it stays an empty
// canvas. Data fetching/wiring lands in M1c-2b.
export function GraphCanvas({
  nodes = EMPTY_NODES,
  edges = EMPTY_EDGES,
  onSelect,
}: GraphCanvasProps) {
  return (
    <div className="graph-canvas" data-testid="graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        elementsSelectable
        onNodeClick={(_event, node) => onSelect?.(node.id)}
        onPaneClick={() => onSelect?.(null)}
      >
        <Background />
      </ReactFlow>
    </div>
  )
}
