import type { KeyboardEvent } from 'react'

import type { Entity } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only entity table (M5d); the caller supplies data from
// RunDetail.entity_graph. Clicking (or Enter/Space on) a row reports the entity id
// so the console can drive the Inspector selection. Column set follows
// dashboard.md §2 (Evidence == the entity's collected evidence mentions).
export function EntitiesTab({
  entities,
  onSelect,
  selectedId,
}: {
  entities?: Entity[]
  onSelect?: (id: string) => void
  selectedId?: string | null
}) {
  if (!entities || entities.length === 0) {
    return (
      <div>
        <div className="panel-hd">
          <h2>ENTITIES</h2>
          <span className="cnt">ID · Name · Type · Aliases · Conf. · Evidence</span>
        </div>
        <div className="empty">暂无实体节点。</div>
      </div>
    )
  }

  const activate = (event: KeyboardEvent<HTMLTableRowElement>, id: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect?.(id)
    }
  }

  return (
    <div>
      <div className="panel-hd">
        <h2>ENTITIES</h2>
        <span className="cnt">{entities.length}</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Type</th>
            <th>Aliases</th>
            <th>Conf.</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {entities.map((entity) => (
            <tr
              key={entity.id}
              className={`selectable-row${entity.id === selectedId ? ' selected-row' : ''}`}
              tabIndex={0}
              onClick={() => onSelect?.(entity.id)}
              onKeyDown={(event) => activate(event, entity.id)}
            >
              <td className="mono">{entity.id}</td>
              <td>{entity.name}</td>
              <td>
                <span className={`kind-swatch etype-${entity.type}`} />
                {entity.type}
              </td>
              <td>{entity.aliases.join('、')}</td>
              <td className="mono">{entity.confidence.toFixed(2)}</td>
              <td className="mono">{entity.evidence.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
