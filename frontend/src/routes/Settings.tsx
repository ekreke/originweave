import { useTheme } from '@/theme/theme'

export function Settings() {
  const { theme, toggle } = useTheme()

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>设置</h2>
          <span className="cnt">主题</span>
        </div>
        <div style={{ padding: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="cnt">当前主题：{theme}</span>
          <button className="btn" type="button" onClick={toggle}>
            切换亮 / 暗
          </button>
        </div>
      </div>
    </div>
  )
}
