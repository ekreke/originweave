import {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  useNodesState,
  type Edge,
  type Node,
  type XYPosition,
} from '@xyflow/react'
import { useEffect, useState, type KeyboardEvent } from 'react'

import { FactNode, IntentNode } from './nodes'

const nodeTypes = { fact: FactNode, intent: IntentNode }

const EMPTY_NODES: Node[] = []
const EMPTY_EDGES: Edge[] = []

export interface GraphCanvasProps {
  nodes?: Node[]
  edges?: Edge[]
  onSelect?: (id: string | null) => void
  onPositionChange?: (id: string, position: XYPosition) => void
  draggable?: boolean
}

// Presentation-only canvas: nodes/edges are supplied by the caller and positions are
// render-side state. Without data it stays an empty canvas.
export function GraphCanvas({
  nodes = EMPTY_NODES,
  edges = EMPTY_EDGES,
  onSelect,
  onPositionChange,
  draggable = true,
}: GraphCanvasProps) {
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState(nodes)
  const [dragging, setDragging] = useState(false)
  // Active runs poll for new facts. Do not replace the local React Flow state in the
  // middle of a gesture, or a node being dragged would jump back under the cursor.
  useEffect(() => {
    if (!dragging) setFlowNodes(nodes)
  }, [dragging, nodes, setFlowNodes])
  // React Flow's built-in keyboard handler updates its internal selected state,
  // but controlled nodes do not reliably surface that change to onSelectionChange.
  // Capture activation from the focusable node wrapper so keyboard and mouse both
  // drive the external Inspector selection.
  const onCanvasKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    const node = (event.target as HTMLElement).closest<HTMLElement>('.react-flow__node[data-id]')
    if (node?.dataset.id) onSelect?.(node.dataset.id)
  }

  return (
    <div className="graph-canvas" data-testid="graph-canvas" onKeyDownCapture={onCanvasKeyDown}>
      <ReactFlow
        nodes={flowNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
        minZoom={0.15}
        maxZoom={1.8}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={draggable}
        onNodesChange={onNodesChange}
        elementsSelectable
        nodesFocusable
        edgesFocusable={false}
        onNodeClick={(_event, node) => onSelect?.(node.id)}
        onNodeDragStart={() => setDragging(true)}
        onNodeDragStop={(_event, node) => {
          onPositionChange?.(node.id, node.position)
          setDragging(false)
        }}
        onPaneClick={() => onSelect?.(null)}
        aria-label="溯源 DAG"
      >
        <Background gap={20} size={1} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap
          ariaLabel="图谱概览"
          className="graph-minimap"
          maskColor="rgb(var(--c-paper) / 0.72)"
          nodeColor="rgb(var(--c-accent))"
          pannable
          zoomable
        />
        <Panel position="top-left" className="graph-summary" role="status" aria-label="图谱摘要">
          <div className="graph-title">PROVENANCE DAG</div>
          <div className="graph-counts">
            <span>{flowNodes.filter((node) => node.type === 'fact').length} facts</span>
            <span>{flowNodes.filter((node) => node.type === 'intent').length} intents</span>
            <span>{edges.length} links</span>
          </div>
        </Panel>
        <Panel position="top-right" className="graph-legend" role="list" aria-label="节点图例">
          <span className="legend-item legend-fact" role="listitem">
            Fact
          </span>
          <span className="legend-item legend-intent" role="listitem">
            Intent
          </span>
          <span className="legend-item legend-source" role="listitem">
            Source
          </span>
          <span className="legend-item legend-deviation" role="listitem">
            Deviation
          </span>
        </Panel>
      </ReactFlow>
    </div>
  )
}
