import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { CSSProperties } from 'react'

import type { FactNode as FactNodeType, IntentNode as IntentNodeType } from './mapping'

// Custom React Flow nodes. Colour comes from the `--c-k-*` tokens so the graph
// follows the light/dark theme; shape encodes the Fact kind (dashboard.md §2).

export function FactNode({ data, selected }: NodeProps<FactNodeType>) {
  const style = { '--node-color': `rgb(var(${data.color}))` } as CSSProperties
  return (
    <div
      className={`node fact-node shape-${data.shape}${selected ? ' selected' : ''}`}
      style={style}
      data-testid={`fact-node-${data.fact.id}`}
      title={data.fact.label}
    >
      <span className="node-label">{data.preview}</span>
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

export function IntentNode({ data, selected }: NodeProps<IntentNodeType>) {
  return (
    <div
      className={`node intent-node intent-${data.variant}${selected ? ' selected' : ''}`}
      data-testid={`intent-node-${data.intent.id}`}
      title={data.intent.question}
    >
      <span className="intent-mark">?</span>
      <span className="node-label">{data.intent.id}</span>
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}
