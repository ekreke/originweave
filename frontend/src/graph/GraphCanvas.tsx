import { useCallback, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type OnNodesChange,
} from '@xyflow/react'

import { applyPositionOverrides, collectPositionChanges, type PositionOverrides } from './drag'
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
// stays an empty canvas. Nodes are draggable (dashboard.md §2); the dragged
// coordinates are a view-only, session-local override -- they never leave the
// client -- and a "reset layout" button clears them. The caller remounts the canvas
// (a `key` on the run id) to drop the overrides when another run opens.
export function GraphCanvas({
  nodes = EMPTY_NODES,
  edges = EMPTY_EDGES,
  onSelect,
  selectedId,
}: GraphCanvasProps) {
  const [overrides, setOverrides] = useState<PositionOverrides>(() => new Map())
  const styledEdges = useMemo(() => classifyEdges(edges, selectedId), [edges, selectedId])

  // Inject the console-managed selection/onSelect and the session drag positions.
  // Re-derived whenever the graph data, selection or drags change; a poll that
  // returns unchanged data keeps the same node identity.
  const flowNodes = useMemo(
    () =>
      applyPositionOverrides(
        nodes.map((node) => ({
          ...node,
          selected: selectedId == null ? node.selected : node.id === selectedId,
          data: { ...node.data, onSelect },
        })),
        overrides,
      ),
    [nodes, overrides, selectedId, onSelect],
  )

  const onNodesChange = useCallback<OnNodesChange<Node>>((changes) => {
    const moved = collectPositionChanges(changes)
    if (moved.size === 0) return
    setOverrides((previous) => {
      const next = new Map(previous)
      for (const [id, position] of moved) next.set(id, position)
      return next
    })
  }, [])

  return (
    <div className="graph-canvas" data-testid="graph-canvas">
      <ReactFlow
        nodes={flowNodes}
        edges={styledEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        fitView
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable
        nodesConnectable={false}
        nodesFocusable
        elementsSelectable
        onNodeClick={(_event, node) => onSelect?.(node.id)}
        onPaneClick={() => onSelect?.(null)}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls showInteractive={false} position="top-right" />
        <MiniMap pannable zoomable position="bottom-right" />
        <Panel position="top-left">
          {nodes.length > 0 ? <ResetLayoutButton onReset={() => setOverrides(new Map())} /> : null}
        </Panel>
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

// Lives inside <ReactFlow> so it can refit the viewport after the dragged positions
// are dropped back to the automatic layout (dashboard.md §2).
function ResetLayoutButton({ onReset }: { onReset: () => void }) {
  const { fitView } = useReactFlow()
  return (
    <button
      type="button"
      className="graph-reset"
      onClick={() => {
        onReset()
        fitView()
      }}
    >
      重置布局
    </button>
  )
}
