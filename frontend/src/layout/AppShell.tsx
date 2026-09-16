import { NavLink, Outlet } from 'react-router-dom'

import { useTheme } from '@/theme/theme'

// Sample project id used for the placeholder navigation until projects come
// from the server (M1c).
const SAMPLE_PROJECT = 'copilot-productivity'

export function AppShell() {
  const { theme, toggle } = useTheme()

  return (
    <div className="shell">
      <header className="appbar">
        <div className="brand" data-testid="brand">
          origin<em>weave</em>
        </div>
        <nav className="nav" aria-label="main">
          <NavLink to="/">总览</NavLink>
          <NavLink to={`/projects/${SAMPLE_PROJECT}`}>项目</NavLink>
          <NavLink to={`/projects/${SAMPLE_PROJECT}/runs/new`}>新建核验</NavLink>
          <NavLink to="/settings">设置</NavLink>
        </nav>
        <div className="tools">
          <span className="live">OFFLINE</span>
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
