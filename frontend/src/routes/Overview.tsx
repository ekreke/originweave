export function Overview() {
  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>总览 · 项目与 run 汇总</h2>
          <span className="cnt">只读视图 · 由事件派生</span>
        </div>
        <div className="empty">暂无项目与 run。数据由 server 提供（M1c）。</div>
      </div>
    </div>
  )
}
