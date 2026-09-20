import { Code, ConnectError } from '@connectrpc/connect'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import { useAddHint, useProjectRuns, useRun, useSubmitHumanInput } from '@/api/hooks'
import type { Fact, Intent, RunDetail } from '@/gen/originweave/v1/originweave_pb'
import { firstSeenAt, visibleIdsAt } from '@/graph/replay'
import { Inspector, type InspectorSelection } from '@/layout/Inspector'
import { RunList } from '@/layout/RunList'
import { EventsTab } from '@/tabs/EventsTab'
import { FactsTab } from '@/tabs/FactsTab'
import { GraphTab } from '@/tabs/GraphTab'
import { IntentsTab } from '@/tabs/IntentsTab'

const TABS = ['GRAPH', 'FACTS', 'INTENTS', 'EVENTS'] as const

type Tab = (typeof TABS)[number]

// Map a graph/table selection id to an Inspector selection. The origin and goal
// anchors are selectable too, so they are searched alongside the derived facts.
function resolveSelection(
  detail: RunDetail | undefined,
  id: string | null,
): InspectorSelection | null {
  if (!detail || !id) return null
  const anchors = [detail.origin, detail.goal, ...detail.facts].filter(
    (f): f is Fact => f !== undefined,
  )
  const fact = anchors.find((f) => f.id === id)
  if (fact) return { type: 'fact', fact }
  const intent: Intent | undefined = detail.intents.find((it) => it.id === id)
  if (intent) return { type: 'intent', intent }
  return null
}

function NotFound() {
  return (
    <section className="col" aria-label="run console">
      <div className="empty">找不到该 run。它可能已被删除或从未创建。</div>
    </section>
  )
}

export function Console() {
  const { projectId, runId } = useParams()
  const [tab, setTab] = useState<Tab>('GRAPH')
  // Selection is tagged with the run it came from: navigating to another run
  // (same component instance) must not resolve the old id against the new board,
  // where fact/intent ids are re-numbered and collide.
  const [selected, setSelected] = useState<{ run: string | undefined; id: string | null }>({
    run: runId,
    id: null,
  })
  const run = useRun(runId)
  const runs = useProjectRuns(projectId)
  const addHint = useAddHint(runId)
  const submitGate = useSubmitHumanInput(runId)
  const detail = run.data
  const selectionId = selected.run === runId ? selected.id : null
  const selection = resolveSelection(detail, selectionId)
  const select = (id: string | null) => setSelected({ run: runId, id })

  // Replay stepper: null means the live board; a number hides nodes/edges that had
  // not appeared yet at that event step (see graph/replay.ts). Like `selected`, the
  // step is tagged with its run so switching runs resets it instead of leaking a
  // step from a longer run onto a shorter one.
  const [replay, setReplay] = useState<{ run: string | undefined; step: number | null }>({
    run: runId,
    step: null,
  })
  const replayStep = replay.run === runId ? replay.step : null
  const stepReplay = (next: number | null | ((current: number | null) => number | null)) => {
    setReplay((current) => {
      const base = current.run === runId ? current.step : null
      return { run: runId, step: typeof next === 'function' ? next(base) : next }
    })
  }
  const events = useMemo(() => detail?.events ?? [], [detail])
  const maxStep = events.length - 1
  const seen = useMemo(() => firstSeenAt(events), [events])
  const visible = replayStep === null ? undefined : visibleIdsAt(seen, replayStep)

  const notFound = run.error instanceof ConnectError && run.error.code === Code.NotFound

  if (notFound) {
    return (
      <div className="console">
        <RunList runs={runs.data} loading={runs.isLoading} error={runs.isError} />
        <NotFound />
        <Inspector />
      </div>
    )
  }

  if (run.isError) {
    return (
      <div className="console">
        <RunList runs={runs.data} loading={runs.isLoading} error={runs.isError} />
        <section className="col" aria-label="run console">
          <div className="empty">无法加载 run：{run.error.message}</div>
        </section>
        <Inspector />
      </div>
    )
  }

  function renderTab() {
    switch (tab) {
      case 'GRAPH':
        return <GraphTab detail={detail} onSelect={select} visibleIds={visible} />
      case 'FACTS':
        return <FactsTab facts={detail?.facts} onSelect={select} selectedId={selectionId} />
      case 'INTENTS':
        return <IntentsTab intents={detail?.intents} onSelect={select} selectedId={selectionId} />
      case 'EVENTS':
        return <EventsTab events={detail?.events} step={replayStep} />
    }
  }

  const runStatus = detail?.run?.status
  const statusLabel = runStatus ?? (run.isLoading ? '…' : '—')
  const budgetSummary = detail?.run
    ? `steps ${detail.run.steps?.current ?? 0}/${detail.run.steps?.total ?? 0}` +
      ` · tok ${String(detail.run.budget?.tokens ?? 0n)}` +
      ` · cost ${(detail.run.budget?.cost ?? 0).toFixed(2)}` +
      ` · intents ${detail.run.intents?.open ?? 0}/${detail.run.intents?.done ?? 0}`
    : ''

  return (
    <div className="console">
      <RunList runs={runs.data} loading={runs.isLoading} error={runs.isError} />
      <section className="col" aria-label="run console">
        <div className="tabs" role="tablist">
          {TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={name === tab}
              className={name === tab ? 'tab on' : 'tab'}
              onClick={() => setTab(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <div className="center-body">
          <div className="run-head">
            <div className="run-meta">
              <span className="mono run-id">{runId ?? '—'}</span>
              {runStatus ? (
                <span className={`status-badge status-${runStatus}`}>{runStatus}</span>
              ) : (
                <span className="cnt mono">{statusLabel}</span>
              )}
              {budgetSummary ? <span className="budget mono">{budgetSummary}</span> : null}
            </div>
            <div className="replay" role="group" aria-label="replay">
              <button
                className="btn"
                type="button"
                aria-label="replay back"
                disabled={events.length === 0}
                onClick={() =>
                  stepReplay((current) => {
                    if (events.length === 0) return current
                    if (current === null) return maxStep
                    return Math.max(0, current - 1)
                  })
                }
              >
                ◀
              </button>
              <span className="mono replay-step">
                {replayStep === null ? 'live' : `${replayStep + 1}/${events.length}`}
              </span>
              <button
                className="btn"
                type="button"
                aria-label="replay forward"
                disabled={events.length === 0}
                onClick={() =>
                  stepReplay((current) => {
                    if (events.length === 0) return current
                    if (current === null) return 0
                    const next = current + 1
                    return next > maxStep ? null : next
                  })
                }
              >
                ▶
              </button>
              <button
                className="btn"
                type="button"
                aria-label="replay live"
                disabled={replayStep === null}
                onClick={() => stepReplay(null)}
              >
                live
              </button>
            </div>
          </div>
          {renderTab()}
        </div>
      </section>
      <Inspector
        selection={selection}
        intents={detail?.intents}
        hints={detail?.hints}
        waitingFor={detail?.waitingFor}
        onDecision={(decision, text) =>
          submitGate.mutate({ gate: detail?.waitingFor?.gate ?? '', decision, text })
        }
        decisionPending={submitGate.isPending}
        decisionError={
          submitGate.error
            ? submitGate.error instanceof Error
              ? submitGate.error.message
              : String(submitGate.error)
            : undefined
        }
        onAddHint={(text) => addHint.mutateAsync(text).then(() => undefined)}
      />
    </div>
  )
}
