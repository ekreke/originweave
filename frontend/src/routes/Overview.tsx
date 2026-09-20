import { Link } from 'react-router-dom'

import { useProjects } from '@/api/hooks'

export function Overview() {
  const { data: projects, isLoading, isError } = useProjects()

  if (isLoading) {
    return (
      <div className="wrap">
        <div className="panel">
          <div className="empty">加载项目中…</div>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="wrap">
        <div className="panel">
          <div className="empty">无法连接 server。确认 `originweave ui` 正在运行。</div>
        </div>
      </div>
    )
  }

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>总览 · 项目与 run 汇总</h2>
          <span className="cnt">只读视图 · 由事件派生</span>
          <Link className="btn" to="/projects/new">
            新建项目
          </Link>
        </div>
        {!projects || projects.length === 0 ? (
          <div className="empty">
            暂无项目。<Link to="/projects/new">立即新建</Link> 后即可发起核验。
          </div>
        ) : (
          <ul className="list">
            {projects.map((project) => (
              <li key={project.id} className="run-card" data-testid={`project-card-${project.id}`}>
                <div className="run-card-hd">
                  <Link className="t" to={`/projects/${project.id}`}>
                    {project.name || project.id}
                  </Link>
                  <span className="cnt mono">{project.id}</span>
                </div>
                <div className="m mono">
                  runs {project.runCount} · updated {project.updatedAt || '—'}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
