import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { CSSProperties } from 'react'

import type {
  EntityNode as EntityNodeType,
  FactNode as FactNodeType,
  IntentNode as IntentNodeType,
} from './mapping'

// Custom React Flow nodes: compact cards (dashboard.md §2). Colour comes from the
// `--c-k-*` tokens so the graph follows the light/dark theme; the header carries
// the id + kind, the body a short preview (full text in the Inspector / title).

export function FactNode({ data, selected }: NodeProps<FactNodeType>) {
  const style = { '--node-color': `rgb(var(${data.color}))` } as CSSProperties
  return (
    <div
      className={`node fact-node kind-${data.summary.kind}${selected ? ' selected' : ''}`}
      style={style}
      data-testid={`fact-node-${data.summary.id}`}
      title={data.summary.label}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          data.onSelect?.(data.summary.id)
        }
      }}
    >
      <div className="node-hd">
        <span className="node-id mono">{data.summary.id}</span>
        <span className="node-kind">{data.summary.kind}</span>
      </div>
      <span className="node-label">{data.preview}</span>
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
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          data.onSelect?.(data.intent.id)
        }
      }}
    >
      <div className="node-hd">
        <span className="node-id mono">{data.intent.id}</span>
        <span className="node-kind">{data.intent.type}</span>
      </div>
      <span className="node-label">{data.preview}</span>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

// Entity node (M5d): compact card colour-coded by Entity.type; the header carries the
// entity id + type, the body a short name preview (full details in the Inspector).
export function EntityNode({ data, selected }: NodeProps<EntityNodeType>) {
  const style = { '--node-color': `rgb(var(${data.color}))` } as CSSProperties
  return (
    <div
      className={`node entity-node${selected ? ' selected' : ''}`}
      style={style}
      data-testid={`entity-node-${data.entity.id}`}
      title={data.entity.name}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          data.onSelect?.(data.entity.id)
        }
      }}
    >
      <div className="node-hd">
        <span className="node-id mono">{data.entity.id}</span>
        <span className="node-kind">{data.entity.type}</span>
      </div>
      <span className="node-label">{data.preview}</span>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
