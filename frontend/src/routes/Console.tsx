import { Code, ConnectError } from '@connectrpc/connect'
import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { useProjectRuns, useRun } from '@/api/hooks'
import { Inspector } from '@/layout/Inspector'
import { RunList } from '@/layout/RunList'
import { EventsTab } from '@/tabs/EventsTab'
import { FactsTab } from '@/tabs/FactsTab'
import { GraphTab } from '@/tabs/GraphTab'
import { IntentsTab } from '@/tabs/IntentsTab'

const TABS = ['GRAPH', 'FACTS', 'INTENTS', 'EVENTS'] as const

type Tab = (typeof TABS)[number]

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
  const run = useRun(runId)
  const runs = useProjectRuns(projectId)
  const detail = run.data

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
        return <GraphTab detail={detail} />
      case 'FACTS':
        return <FactsTab facts={detail?.facts} />
      case 'INTENTS':
        return <IntentsTab intents={detail?.intents} />
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
      <Inspector intents={detail?.intents} waitingFor={detail?.waitingFor} />
    </div>
  )
}
