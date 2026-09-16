export function Inspector() {
  return (
    <div className="col inspector" aria-label="inspector">
      <h3>INSPECTOR</h3>
      <p className="cnt">选中节点后在此查看证据与 Intent/Hints。</p>
      <div className="empty">无选中项。数据由 server 提供（M1c）。</div>
    </div>
  )
}
