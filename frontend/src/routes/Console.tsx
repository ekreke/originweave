import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { Inspector } from '@/layout/Inspector'
import { RunList } from '@/layout/RunList'
import { EventsTab } from '@/tabs/EventsTab'
import { FactsTab } from '@/tabs/FactsTab'
import { GraphTab } from '@/tabs/GraphTab'
import { IntentsTab } from '@/tabs/IntentsTab'

const TABS = ['GRAPH', 'FACTS', 'INTENTS', 'EVENTS'] as const

type Tab = (typeof TABS)[number]

function renderTab(tab: Tab) {
  switch (tab) {
    case 'GRAPH':
      return <GraphTab />
    case 'FACTS':
      return <FactsTab />
    case 'INTENTS':
      return <IntentsTab />
    case 'EVENTS':
      return <EventsTab />
  }
}

export function Console() {
  const { runId } = useParams()
  const [tab, setTab] = useState<Tab>('GRAPH')

  return (
    <div className="console">
      <RunList />
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
            run: {runId ?? '—'} · 只读视图（M1b 空态）
          </div>
          {renderTab(tab)}
        </div>
      </section>
      <Inspector />
    </div>
  )
}
