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
      <span className={`node-symbol symbol-${data.shape}`} aria-hidden="true" />
      <div className="node-kicker">
        <span>{data.fact.kind}</span>
        <span className="mono">{data.fact.id}</span>
      </div>
      <span className="node-label">{data.preview}</span>
      <div className="node-foot">
        <span>{data.fact.status}</span>
        {data.fact.confidence > 0 ? <span>{Math.round(data.fact.confidence * 100)}%</span> : null}
      </div>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
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
      <span className="intent-mark" aria-hidden="true">
        ?
      </span>
      <div className="intent-copy">
        <span className="intent-id mono">{data.intent.id}</span>
        <span className="node-label">{data.preview || data.intent.question || '待处理意图'}</span>
      </div>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
