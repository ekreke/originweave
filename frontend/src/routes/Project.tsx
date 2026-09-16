import { useParams } from 'react-router-dom'

export function Project() {
  const { projectId } = useParams()

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>项目 · {projectId ?? '—'}</h2>
          <span className="cnt">Runs</span>
        </div>
        <div className="empty">暂无 run。数据由 server 提供（M1c）。</div>
      </div>
    </div>
  )
}
