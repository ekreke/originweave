import { Link } from 'react-router-dom'

import type { Run } from '@/gen/originweave/v1/originweave_pb'

// Terminal states whose inputs can be re-submitted as a new run.
const RETRYABLE = new Set(['failed', 'stopped'])

// Presentation-only run list; the caller supplies data (and its loading/error
// state) from the server. A retryable run (failed/stopped) offers a "retry" link
// that opens the new-run form prefilled from that run's inputs.
export function RunList({
  runs,
  loading,
  error,
  projectId,
}: {
  runs?: Run[]
  loading?: boolean
  error?: boolean
  projectId?: string
}) {
  if (loading) {
    return (
      <div className="col" aria-label="run list">
        <div className="panel-hd">
          <h2>Runs</h2>
          <span className="cnt">…</span>
        </div>
        <div className="empty">加载 run 中…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="col" aria-label="run list">
        <div className="panel-hd">
          <h2>Runs</h2>
          <span className="cnt">—</span>
        </div>
        <div className="empty">无法加载 run。</div>
      </div>
    )
  }

  if (!runs || runs.length === 0) {
    return (
      <div className="col" aria-label="run list">
        <div className="panel-hd">
          <h2>Runs</h2>
          <span className="cnt">0</span>
        </div>
        <div className="empty">尚无 run。</div>
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
              {projectId ? (
                <Link className="t" to={`/projects/${projectId}/runs/${run.id}`}>
                  {run.title || run.id}
                </Link>
              ) : (
                <span className="t">{run.title || run.id}</span>
              )}
              <span className="run-card-actions">
                {projectId && RETRYABLE.has(run.status) ? (
                  <Link
                    className="btn run-retry"
                    to={`/projects/${projectId}/runs/new?from=${encodeURIComponent(run.id)}`}
                  >
                    重试
                  </Link>
                ) : null}
                <span className={`status-badge status-${run.status}`}>{run.status}</span>
              </span>
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
