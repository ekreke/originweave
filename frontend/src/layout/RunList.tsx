import type { Run } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only run list. Without data it keeps the M1b empty state; wiring
// to the server lands in M1c-2b.
export function RunList({ runs }: { runs?: Run[] }) {
  if (!runs || runs.length === 0) {
    return (
      <div className="col" aria-label="run list">
        <div className="panel-hd">
          <h2>Runs</h2>
          <span className="cnt">0</span>
        </div>
        <div className="empty">尚无 run。数据由 server 提供（M1c）。</div>
      </div>
    )
  }

  return (
    <div className="col" aria-label="run list">
      <div className="panel-hd">
        <h2>Runs</h2>
        <span className="cnt">{runs.length}</span>
      </div>
      <ul className="list">
        {runs.map((run) => (
          <li
            key={run.id}
            className={`run-card${run.status === 'awaiting_human' ? ' run-card-alert' : ''}`}
            data-testid={`run-card-${run.id}`}
          >
            <div className="run-card-hd">
              <span className="t">{run.title || run.id}</span>
              <span className={`status-badge status-${run.status}`}>{run.status}</span>
            </div>
            <div className="m mono">
              {run.id} · facts {run.facts} · dev {run.deviations} · conf {run.confidence.toFixed(2)}{' '}
              · steps {run.steps?.current ?? 0}/{run.steps?.total ?? 0}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
