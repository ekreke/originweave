import { Link, useParams } from 'react-router-dom'
import { useMemo, useState } from 'react'

import { useProjectRuns } from '@/api/hooks'
import { RunList } from '@/layout/RunList'

// Filter options are derived from the statuses actually present in the loaded
// runs (canonical set: blackboard.py RUN_STATUSES, minus `paused`, which the
// reducer never emits yet), so the select never offers a dead choice.
export function Project() {
  const { projectId } = useParams()
  const { data: runs, isLoading, isError } = useProjectRuns(projectId)
  const [statusFilter, setStatusFilter] = useState('')
  const [prevProjectId, setPrevProjectId] = useState(projectId)
  // The router reuses this component across /projects/:projectId; resetting
  // during render (not in an effect) drops a stale filter without cascading.
  if (prevProjectId !== projectId) {
    setPrevProjectId(projectId)
    setStatusFilter('')
  }

  const statuses = useMemo(() => {
    return [...new Set((runs ?? []).map((run) => run.status))].sort()
  }, [runs])

  const filtered = useMemo(() => {
    if (!runs) return undefined
    return statusFilter ? runs.filter((run) => run.status === statusFilter) : runs
  }, [runs, statusFilter])

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>项目 · {projectId ?? '—'}</h2>
          <span className="run-filter-group">
            <select
              className="run-filter"
              aria-label="按状态过滤"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="">全部状态</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <Link className="cnt mono" to={`/projects/${projectId}/runs/new`}>
              新建核验 →
            </Link>
          </span>
        </div>
      </div>
      {isLoading ? (
        <div className="empty">加载 run 中…</div>
      ) : isError ? (
        <div className="empty">无法加载该项目的 run。</div>
      ) : (
        <RunList runs={filtered} projectId={projectId} />
      )}
    </div>
  )
}
