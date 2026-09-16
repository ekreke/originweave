export function NewRun() {
  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>新建核验</h2>
          <span className="cnt mono">CreateRun</span>
        </div>
        <div style={{ padding: 16, display: 'grid', gap: 12, maxWidth: 640 }}>
          <label>
            <div className="cnt">资料 A sourceType</div>
            <select className="btn" defaultValue="url" disabled>
              <option value="url">url</option>
              <option value="text">text</option>
            </select>
          </label>
          <label>
            <div className="cnt">资料 A target</div>
            <input className="btn" style={{ width: '100%' }} placeholder="https://…" disabled />
          </label>
          <label>
            <div className="cnt">goal（停止条件 / 判定标准）</div>
            <input className="btn" style={{ width: '100%' }} disabled />
          </label>
          <label>
            <div className="cnt">analysis</div>
            <select className="btn" defaultValue="provenance" disabled>
              <option value="provenance">provenance</option>
              <option value="relation">relation</option>
              <option value="both">both</option>
            </select>
          </label>
          <div>
            <button className="btn" type="button" disabled>
              由 server 调度（M1c）
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
