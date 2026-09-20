import { useMemo } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'

import { classifyEdges } from './mapping'
import { FactNode, IntentNode } from './nodes'

const nodeTypes = { fact: FactNode, intent: IntentNode }

const EMPTY_NODES: Node[] = []
const EMPTY_EDGES: Edge[] = []

// Legend rows: fact-kind colour chips + the three frozen relation line styles.
const KIND_LEGEND = [
  ['origin/goal', '--c-k-origin'],
  ['fact', '--c-k-fact'],
  ['citation', '--c-k-citation'],
  ['source', '--c-k-source'],
  ['boundary', '--c-k-boundary'],
  ['compare', '--c-k-compare'],
  ['deviation', '--c-k-deviation'],
] as const

const RELATION_LEGEND = [
  ['main-chain', 'solid'],
  ['dependency', 'dashed'],
  ['decomposes', 'dotted'],
] as const

export interface GraphCanvasProps {
  nodes?: Node[]
  edges?: Edge[]
  onSelect?: (id: string | null) => void
  /** Console-managed selection: highlights the node and dims unrelated edges. */
  selectedId?: string | null
}

// Presentation-only canvas: nodes/edges are supplied by the caller (mapped from
// RunGraph) and positions come from the server / dagre fallback. Without data it
// stays an empty canvas.
export function GraphCanvas({
  nodes = EMPTY_NODES,
  edges = EMPTY_EDGES,
  onSelect,
  selectedId,
}: GraphCanvasProps) {
  const styledEdges = useMemo(() => classifyEdges(edges, selectedId), [edges, selectedId])

  const markedNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        selected: selectedId == null ? node.selected : node.id === selectedId,
        // Keyboard activation (Enter/Space on the focused card) reports through
        // the same callback as clicks.
        data: { ...node.data, onSelect },
      })),
    [nodes, selectedId, onSelect],
  )

  return (
    <div className="graph-canvas" data-testid="graph-canvas">
      <ReactFlow
        nodes={markedNodes}
        edges={styledEdges}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable
        elementsSelectable
        onNodeClick={(_event, node) => onSelect?.(node.id)}
        onPaneClick={() => onSelect?.(null)}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls showInteractive={false} position="top-right" />
        <MiniMap pannable zoomable position="bottom-right" />
        <Panel position="bottom-left">
          <div className="graph-legend" aria-label="graph legend">
            <div className="legend-col">
              {KIND_LEGEND.map(([label, token]) => (
                <span key={label} className="legend-row">
                  <i className="legend-chip" style={{ background: `rgb(var(${token}))` }} />
                  {label}
                </span>
              ))}
            </div>
            <div className="legend-col">
              {RELATION_LEGEND.map(([label, line]) => (
                <span key={label} className="legend-row">
                  <i className={`legend-line legend-${line}`} />
                  {label}
                </span>
              ))}
              <span className="legend-row">
                <i className="legend-line legend-intent" />
                intent
              </span>
            </div>
          </div>
        </Panel>
      </ReactFlow>
    </div>
  )
}
