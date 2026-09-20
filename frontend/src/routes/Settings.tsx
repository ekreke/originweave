import { type FormEvent, useState } from 'react'

import { useSettings, useUpdateSettings } from '@/api/hooks'
import {
  EMPTY_DRAFT,
  HEARTBEAT_ON_TIMEOUT,
  PROVIDERS,
  TOOLS,
  type Draft,
  draftToMessage,
  toDraft,
  validateDraft,
} from '@/routes/settingsModel'
import { useTheme } from '@/theme/theme'

export function Settings() {
  const { theme, toggle } = useTheme()
  const query = useSettings()
  const update = useUpdateSettings()
  // `edited` holds user changes; until the first edit the form mirrors the loaded
  // settings (derived during render -- no effect, no cascading render).
  const [edited, setEdited] = useState<Draft | null>(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const loaded = query.data ? toDraft(query.data) : null
  const draft = edited ?? loaded

  const patch = (changes: Partial<Draft>) => {
    setEdited({ ...(edited ?? loaded ?? EMPTY_DRAFT), ...changes })
    setError('')
    setSaved(false)
  }

  const toggleTool = (tool: string) => {
    const current = edited ?? loaded ?? EMPTY_DRAFT
    patch({
      tools: current.tools.includes(tool)
        ? current.tools.filter((item) => item !== tool)
        : [...current.tools, tool],
    })
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!draft || update.isPending) return
    const problem = validateDraft(draft)
    if (problem) {
      setError(problem)
      setSaved(false)
      return
    }
    setError('')
    setSaved(false)
    try {
      await update.mutateAsync(draftToMessage(draft))
      // Drop the local draft so the form mirrors the server's persisted values.
      setEdited(null)
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>设置</h2>
          <span className="cnt">主题</span>
        </div>
        <div className="settings-row">
          <span className="cnt">当前主题：{theme}</span>
          <button className="btn" type="button" onClick={toggle}>
            切换亮 / 暗
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-hd">
          <h2>Worker</h2>
          <span className="cnt">[worker] · 对后续 run 生效</span>
        </div>

        {query.isLoading ? <div className="empty">加载设置中…</div> : null}
        {query.isError ? <div className="empty">无法加载设置：{query.error.message}</div> : null}

        {draft ? (
          <form className="settings-form" onSubmit={submit}>
            <fieldset>
              <legend>执行体</legend>
              <label>
                provider
                <select
                  aria-label="worker provider"
                  value={draft.provider}
                  onChange={(event) => patch({ provider: event.target.value })}
                >
                  {PROVIDERS.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                max_concurrency
                <input
                  aria-label="max concurrency"
                  type="number"
                  min={1}
                  max={16}
                  value={draft.maxConcurrency}
                  onChange={(event) => patch({ maxConcurrency: event.target.value })}
                />
              </label>
            </fieldset>

            <fieldset>
              <legend>LLM（复用 [capability.model]）</legend>
              <label>
                provider
                <input aria-label="llm provider" value={draft.llmProvider} readOnly disabled />
              </label>
              <label>
                model
                <input
                  aria-label="llm model"
                  value={draft.llmModel}
                  onChange={(event) => patch({ llmModel: event.target.value })}
                />
              </label>
              <label>
                base_url
                <input
                  aria-label="llm base url"
                  placeholder="空 = 使用 OPENAI_BASE_URL"
                  value={draft.llmBaseUrl}
                  onChange={(event) => patch({ llmBaseUrl: event.target.value })}
                />
              </label>
              <label>
                api key
                <input
                  aria-label="llm api key"
                  value="（仅从环境变量 OPENAI_API_KEY 读取）"
                  readOnly
                  disabled
                />
              </label>
            </fieldset>

            <fieldset>
              <legend>预算</legend>
              <label>
                max_steps
                <input
                  aria-label="max steps"
                  type="number"
                  min={1}
                  value={draft.maxSteps}
                  onChange={(event) => patch({ maxSteps: event.target.value })}
                />
              </label>
              <label>
                max_wall
                <input
                  aria-label="max wall"
                  value={draft.maxWall}
                  onChange={(event) => patch({ maxWall: event.target.value })}
                />
              </label>
              <label>
                max_cost
                <input
                  aria-label="max cost"
                  type="number"
                  min={0}
                  step="0.1"
                  value={draft.maxCost}
                  onChange={(event) => patch({ maxCost: event.target.value })}
                />
              </label>
            </fieldset>

            <fieldset>
              <legend>心跳（单次调用租约）</legend>
              <label>
                interval
                <input
                  aria-label="heartbeat interval"
                  value={draft.heartbeatInterval}
                  onChange={(event) => patch({ heartbeatInterval: event.target.value })}
                />
              </label>
              <label>
                timeout
                <input
                  aria-label="heartbeat timeout"
                  value={draft.heartbeatTimeout}
                  onChange={(event) => patch({ heartbeatTimeout: event.target.value })}
                />
              </label>
              <label>
                on timeout
                <select
                  aria-label="heartbeat on timeout"
                  value={draft.heartbeatOnTimeout}
                  onChange={(event) => patch({ heartbeatOnTimeout: event.target.value })}
                >
                  {HEARTBEAT_ON_TIMEOUT.map((mode) => (
                    <option key={mode} value={mode}>
                      {mode}
                    </option>
                  ))}
                </select>
              </label>
            </fieldset>

            <fieldset>
              <legend>工具白名单</legend>
              <div className="settings-tools">
                {TOOLS.map((tool) => (
                  <label key={tool} className="settings-tool">
                    <input
                      type="checkbox"
                      aria-label={`tool ${tool}`}
                      checked={draft.tools.includes(tool)}
                      onChange={() => toggleTool(tool)}
                    />
                    {tool}
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="settings-actions">
              <button className="btn" type="submit" disabled={update.isPending}>
                保存
              </button>
              {saved ? <span className="cnt">已保存，对后续 run 生效</span> : null}
              {error ? <span className="gate-error">{error}</span> : null}
            </div>
          </form>
        ) : null}
      </div>
    </div>
  )
}
