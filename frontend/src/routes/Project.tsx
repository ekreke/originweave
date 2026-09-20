import { Link, useParams } from 'react-router-dom'

import { useProjectRuns } from '@/api/hooks'
import { RunList } from '@/layout/RunList'

export function Project() {
  const { projectId } = useParams()
  const { data: runs, isLoading, isError } = useProjectRuns(projectId)

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>项目 · {projectId ?? '—'}</h2>
          <Link className="cnt mono" to={`/projects/${projectId}/runs/new`}>
            新建核验 →
          </Link>
        </div>
      </div>
      {isLoading ? (
        <div className="empty">加载 run 中…</div>
      ) : isError ? (
        <div className="empty">无法加载该项目的 run。</div>
      ) : (
        <RunList runs={runs} projectId={projectId} />
      )}
    </div>
  )
}
