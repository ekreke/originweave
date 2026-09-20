import { NavLink, Outlet } from 'react-router-dom'

import { useProjects } from '@/api/hooks'
import { useTheme } from '@/theme/theme'

export function AppShell() {
  const { theme, toggle } = useTheme()
  const { data: projects, isError, isSuccess } = useProjects()
  const connection = isError ? 'OFFLINE' : isSuccess ? 'LIVE' : 'SYNC'

  return (
    <div className="shell">
      <header className="appbar">
        <div className="brand" data-testid="brand">
          origin<em>weave</em>
        </div>
        <nav className="nav" aria-label="main">
          <NavLink to="/">总览</NavLink>
          {(projects ?? []).map((project) => (
            <NavLink key={project.id} to={`/projects/${project.id}`}>
              {project.name || project.id}
            </NavLink>
          ))}
          <NavLink to="/settings">设置</NavLink>
        </nav>
        <div className="tools">
          <span className={`live ${isError ? 'live-off' : ''}`} title="server connection">
            {connection}
          </span>
          <button className="btn" type="button" onClick={toggle}>
            {theme === 'dark' ? '☀ Theme' : '☾ Theme'}
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
