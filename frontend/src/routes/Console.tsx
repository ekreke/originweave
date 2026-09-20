import { Code, ConnectError } from '@connectrpc/connect'
import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { useAddHint, useProjectRuns, useRun } from '@/api/hooks'
import type { Fact, Intent, RunDetail } from '@/gen/originweave/v1/originweave_pb'
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
  const detail = run.data
  const selectionId = selected.run === runId ? selected.id : null
  const selection = resolveSelection(detail, selectionId)
  const select = (id: string | null) => setSelected({ run: runId, id })

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
        return <GraphTab detail={detail} onSelect={select} />
      case 'FACTS':
        return <FactsTab facts={detail?.facts} onSelect={select} selectedId={selectionId} />
      case 'INTENTS':
        return <IntentsTab intents={detail?.intents} onSelect={select} selectedId={selectionId} />
      case 'EVENTS':
        return <EventsTab events={detail?.events} />
    }
  }

  const status = detail?.run?.status ?? (run.isLoading ? '…' : '—')

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
          <div className="cnt mono" style={{ padding: '6px 12px' }}>
            run: {runId ?? '—'} · {status}
          </div>
          {renderTab()}
        </div>
      </section>
      <Inspector
        selection={selection}
        intents={detail?.intents}
        hints={detail?.hints}
        waitingFor={detail?.waitingFor}
        onAddHint={(text) => addHint.mutateAsync(text).then(() => undefined)}
      />
    </div>
  )
}
