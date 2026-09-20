import type { KeyboardEvent } from 'react'

import type { FactSummary } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only table; the caller supplies data from the server. Clicking (or
// pressing Enter/Space on) a row reports the fact id so the console can drive the
// Inspector selection.
export function FactsTab({
  facts,
  onSelect,
  selectedId,
}: {
  facts?: FactSummary[]
  onSelect?: (id: string) => void
  selectedId?: string | null
}) {
  if (!facts || facts.length === 0) {
    return (
      <div>
        <div className="panel-hd">
          <h2>FACTS</h2>
          <span className="cnt">ID · Kind · Statement · Conf. · Evidence</span>
        </div>
        <div className="empty">暂无事实节点。</div>
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
        <h2>FACTS</h2>
        <span className="cnt">{facts.length}</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Kind</th>
            <th>Statement</th>
            <th>Conf.</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((f) => (
            <tr
              key={f.id}
              className={`selectable-row${f.id === selectedId ? ' selected-row' : ''}`}
              tabIndex={0}
              onClick={() => onSelect?.(f.id)}
              onKeyDown={(event) => activate(event, f.id)}
            >
              <td className="mono">{f.id}</td>
              <td>
                <span className={`kind-swatch kind-${f.kind}`} />
                {f.kind}
              </td>
              <td>
                {f.label}
                {f.role !== 'none' ? <span className="role-tag">{f.role}</span> : null}
              </td>
              <td className="mono">{f.confidence.toFixed(2)}</td>
              <td className="mono">{f.evidenceCount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
