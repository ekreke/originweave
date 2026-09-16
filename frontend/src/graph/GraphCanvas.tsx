import { Background, ReactFlow } from '@xyflow/react'
import type { Edge, Node } from '@xyflow/react'

const nodes: Node[] = []
const edges: Edge[] = []

// Empty canvas shell. Real Fact/Intent nodes and provenance edges are rendered
// from server data in M1c.
export function GraphCanvas() {
  return (
    <div className="graph-canvas" data-testid="graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        elementsSelectable={false}
      >
        <Background />
      </ReactFlow>
    </div>
  )
}
