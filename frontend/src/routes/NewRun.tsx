import { useState, type FormEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useCreateRun, useRun } from '@/api/hooks'

// New-run form (CreateRun). Only the "text" source is supported (url lands later) and
// analysis is fixed to "provenance" (relation/both land in M5). Budget overrides are
// optional; unset fields fall back to [worker].budget on the server. A run started in
// `originweave ui --run` (read-only) is rejected by the server and surfaced inline.
//
// With `?from=<runId>` (the run list's "retry") the form is prefilled from that run's
// inputs — GetRun returns its source_text plus the static title/goal.
export function NewRun() {
  const { projectId } = useParams()
  const [searchParams] = useSearchParams()
  const fromId = searchParams.get('from')
  const navigate = useNavigate()
  const createRun = useCreateRun()
  const source = useRun(fromId ?? undefined)
  const sourceDetail = source.data

  // Mirror the source run's inputs until the user edits a field; `edited ?? loaded`
  // keeps render pure (no effect, no cascading render). The title is prefixed once,
  // even if the source title was itself a retry.
  const sourceTitle = sourceDetail?.run?.title ?? fromId ?? ''
  const loaded = {
    title: sourceTitle
      ? sourceTitle.startsWith('重试：')
        ? sourceTitle
        : `重试：${sourceTitle}`
      : '',
    sourceText: sourceDetail?.sourceText ?? '',
    goal: sourceDetail?.run?.goal ?? '',
  }
  const [edited, setEdited] = useState<{ title?: string; sourceText?: string; goal?: string }>({})
  const title = edited.title ?? loaded.title
  const sourceText = edited.sourceText ?? loaded.sourceText
  const goal = edited.goal ?? loaded.goal

  const [auto, setAuto] = useState(false)
  const [showBudget, setShowBudget] = useState(false)
  const [maxSteps, setMaxSteps] = useState('')
  const [maxWall, setMaxWall] = useState('')
  const [maxCost, setMaxCost] = useState('')
  const [error, setError] = useState('')

  const valid = Boolean(projectId && sourceText.trim() && goal.trim())

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!valid || createRun.isPending) return
    const steps = maxSteps.trim() ? Number(maxSteps) : undefined
    const cost = maxCost.trim() ? Number(maxCost) : undefined
    if (steps !== undefined && (!Number.isFinite(steps) || steps <= 0)) {
      setError('max_steps 必须是正整数')
      return
    }
    if (cost !== undefined && (!Number.isFinite(cost) || cost < 0)) {
      setError('max_cost 必须是非负数')
      return
    }
    setError('')
    try {
      const run = await createRun.mutateAsync({
        projectId: projectId ?? '',
        // Keep the document text verbatim (paragraphs matter); trim only to test emptiness.
        sourceText,
        goal: goal.trim(),
        ...(title.trim() ? { title: title.trim() } : {}),
        auto,
        ...(steps !== undefined ? { maxSteps: Math.trunc(steps) } : {}),
        ...(maxWall.trim() ? { maxWall: maxWall.trim() } : {}),
        ...(cost !== undefined ? { maxCost: cost } : {}),
      })
      if (run?.id) {
        navigate(`/projects/${projectId}/runs/${run.id}`)
      } else {
        setError('CreateRun 未返回 run')
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <div className="wrap">
      <div className="panel">
        <div className="panel-hd">
          <h2>新建核验</h2>
          <span className="cnt mono">{fromId ? `重试 run ${fromId}` : 'CreateRun'}</span>
        </div>
        {source.isError ? (
          <p className="form-error">
            无法加载来源 run {fromId}：{source.error.message}
          </p>
        ) : null}
        <form className="new-run" onSubmit={submit}>
          <label>
            <div className="cnt">标题（可选）</div>
            <input
              className="btn"
              aria-label="run title"
              placeholder="run 标题"
              value={title}
              onChange={(event) => setEdited({ ...edited, title: event.target.value })}
            />
          </label>
          <label>
            <div className="cnt">资料 A 正文（source_text）</div>
            <textarea
              className="btn"
              aria-label="source text"
              rows={8}
              placeholder="粘贴资料 A 的正文…"
              value={sourceText}
              onChange={(event) => setEdited({ ...edited, sourceText: event.target.value })}
            />
          </label>
          <label>
            <div className="cnt">goal（停止条件 / 判定标准）</div>
            <input
              className="btn"
              aria-label="goal"
              placeholder="判定标准"
              value={goal}
              onChange={(event) => setEdited({ ...edited, goal: event.target.value })}
            />
          </label>
          <div className="cnt">sourceType: text（url 暂不支持） · analysis: provenance</div>
          <label className="inline">
            <input
              type="checkbox"
              checked={auto}
              onChange={(event) => setAuto(event.target.checked)}
            />
            <span className="cnt">auto：跳过 HITL Gate（默认人工介入）</span>
          </label>
          <div>
            <button className="btn" type="button" onClick={() => setShowBudget((value) => !value)}>
              {showBudget ? '收起预算覆盖' : '预算覆盖（可选）'}
            </button>
          </div>
          {showBudget ? (
            <div className="budget-grid">
              <label>
                <div className="cnt">max_steps</div>
                <input
                  className="btn"
                  type="number"
                  min={1}
                  value={maxSteps}
                  onChange={(event) => setMaxSteps(event.target.value)}
                />
              </label>
              <label>
                <div className="cnt">max_wall（如 10m）</div>
                <input
                  className="btn"
                  placeholder="10m"
                  value={maxWall}
                  onChange={(event) => setMaxWall(event.target.value)}
                />
              </label>
              <label>
                <div className="cnt">max_cost（USD）</div>
                <input
                  className="btn"
                  type="number"
                  step="0.01"
                  min={0}
                  value={maxCost}
                  onChange={(event) => setMaxCost(event.target.value)}
                />
              </label>
            </div>
          ) : null}
          <div>
            <button className="btn" type="submit" disabled={!valid || createRun.isPending}>
              {createRun.isPending ? '创建中…' : '创建并进入审阅台'}
            </button>
          </div>
          {error ? <p className="form-error">{error}</p> : null}
        </form>
      </div>
    </div>
  )
}
