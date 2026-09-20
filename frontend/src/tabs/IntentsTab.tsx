import type { Intent } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only table; the caller supplies data from the server.
export function IntentsTab({ intents }: { intents?: Intent[] }) {
  if (!intents || intents.length === 0) {
    return (
      <div>
        <div className="panel-hd">
          <h2>INTENTS</h2>
          <span className="cnt">ID · Type · Question · Status · From</span>
        </div>
        <div className="empty">暂无 Intent。</div>
      </div>
    )
  }

  return (
    <div>
      <div className="panel-hd">
        <h2>INTENTS</h2>
        <span className="cnt">{intents.length}</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Type</th>
            <th>Question</th>
            <th>Status</th>
            <th>From</th>
          </tr>
        </thead>
        <tbody>
          {intents.map((it) => (
            <tr key={it.id} className={it.status === 'dropped' ? 'row-dropped' : undefined}>
              <td className="mono">{it.id}</td>
              <td>{it.type}</td>
              <td>
                {it.question}
                {it.duplicateOf ? <span className="dup-tag">dup of {it.duplicateOf}</span> : null}
              </td>
              <td>
                <span className={`status-badge status-${it.status}`}>{it.status}</span>
              </td>
              <td className="mono">{it.from}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
