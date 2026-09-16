import { Link } from 'react-router-dom'

export function NotFound() {
  return (
    <div className="wrap">
      <div className="panel">
        <div className="empty">
          404 · 未找到该页面。<Link to="/">返回总览</Link>
        </div>
      </div>
    </div>
  )
}
