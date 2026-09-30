import { Code, ConnectError } from '@connectrpc/connect'
import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  activePollInterval,
  useAddHint,
  useFactDetail,
  useProjectRuns,
  useProjects,
  useRun,
  useRunEvents,
  useRunGraph,
  useRunSessions,
  useSubmitHumanInput,
  useUpdateRun,
} from '@/api/hooks'
import type {
  EntityGraph,
  FactSummary,
  Intent,
  RunGraph,
} from '@/gen/originweave/v1/originweave_pb'
import { Inspector, type InspectorSelection } from '@/layout/Inspector'
import { RunList } from '@/layout/RunList'
import { activityLabel, tabsFor, type Tab } from '@/routes/consoleModel'
import { EntitiesTab } from '@/tabs/EntitiesTab'
import { EventsTab } from '@/tabs/EventsTab'
import { FactsTab } from '@/tabs/FactsTab'
import { GraphTab } from '@/tabs/GraphTab'
import { IntentsTab } from '@/tabs/IntentsTab'
import { RelationsTab } from '@/tabs/RelationsTab'

// Map a graph/table selection id to an Inspector selection. The origin and goal
// anchors are selectable too, so they are searched alongside the derived facts.
// Entity and relation ids (n*/r*) come from the on-demand entity graph (M5d).
function resolveSelection(
  graph: RunGraph | undefined,
  entityGraph: EntityGraph | undefined,
  id: string | null,
): InspectorSelection | null {
  if (!id) return null
  if (graph) {
    const anchors = [graph.origin, graph.goal, ...graph.facts].filter(
      (f): f is FactSummary => f !== undefined,
    )
    const fact = anchors.find((f) => f.id === id)
    if (fact) return { type: 'fact', fact }
    const intent: Intent | undefined = graph.intents.find((it) => it.id === id)
    if (intent) return { type: 'intent', intent }
  }
  if (entityGraph) {
    const entity = entityGraph.entities.find((e) => e.id === id)
    if (entity) return { type: 'entity', entity }
    const relation = entityGraph.relations.find((r) => r.id === id)
    if (relation) return { type: 'relation', relation }
  }
  return null
}

function NotFound() {
  return (
    <section className="col" aria-label="run console">
      <div className="empty">找不到该 run。它可能已被删除或从未创建。</div>
    </section>
  )
}

// The run title, edited in place (M8). The title is static metadata (not an event), so
// saving only refreshes the lists and this header -- the board and `replay` don't move.
// Editing is hidden while replaying a historical step (writing a live run mid-replay
// would be confusing) and rejected by the server in the pinned read-only view.
function RunTitle({
  runId,
  title,
  editable,
}: {
  runId: string | undefined
  title: string
  editable: boolean
}) {
  const updateRun = useUpdateRun(runId)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title)
  const [error, setError] = useState('')

  const start = () => {
    setDraft(title)
    setError('')
    setEditing(true)
  }

  const save = async () => {
    const next = draft.trim()
    if (!next) {
      setError('标题不能为空')
      return
    }
    try {
      await updateRun.mutateAsync(next)
      setEditing(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  if (!editing) {
    return (
      <div className="title-wrap">
        <h2 className="center-title">{title}</h2>
        {editable ? (
          <button className="btn title-edit" type="button" aria-label="edit title" onClick={start}>
            ✎
          </button>
        ) : null}
      </div>
    )
  }
  return (
    <div className="title-edit-form">
      <input
        className="btn"
        aria-label="run title"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button
        className="btn"
        type="button"
        aria-label="save title"
        disabled={updateRun.isPending}
        onClick={save}
      >
        {updateRun.isPending ? '保存中…' : '保存'}
      </button>
      <button
        className="btn"
        type="button"
        aria-label="cancel title"
        onClick={() => setEditing(false)}
      >
        取消
      </button>
      {error ? <span className="form-error">{error}</span> : null}
    </div>
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
  // Replay stepper: `step` is a 0-based event index (null = live). The server folds
  // the board to `step + 1` events (see GetRunGraphRequest.at_event); the cursor
  // bound stays the full event count so its length is stable. Like `selected`, the
  // step is tagged with its run so switching runs resets it.
  const [replay, setReplay] = useState<{ run: string | undefined; step: number | null }>({
    run: runId,
    step: null,
  })
  const replayStep = replay.run === runId ? replay.step : null
  const atEvent = replayStep === null ? null : replayStep + 1
  const stepReplay = (next: number | null | ((current: number | null) => number | null)) => {
    setReplay((current) => {
      const base = current.run === runId ? current.step : null
      return { run: runId, step: typeof next === 'function' ? next(base) : next }
    })
  }

  // Light graph projection (polled); full detail and heavy sections load on demand.
  const graphQuery = useRunGraph(runId, atEvent)
  const graph = graphQuery.data
  // Tabs depend on the run's analysis; fall back to GRAPH if the current tab is not
  // available (e.g. navigating from a relation run to a provenance run).
  const tabs = tabsFor(graph?.run?.analysis)
  const activeTab: Tab = tabs.includes(tab) ? tab : 'GRAPH'
  // The entity graph lives on RunDetail (not the light RunGraph), so the heavier
  // GetRun is fetched only while a relation tab is open (M5d), mirroring EVENTS.
  const relationTab = activeTab === 'RELATIONS' || activeTab === 'ENTITIES'
  const runQuery = useRun(runId, atEvent, relationTab)
  const entityGraph = runQuery.data?.entityGraph
  const runs = useProjectRuns(projectId)
  const projects = useProjects()
  const sessionsQuery = useRunSessions(runId)
  const eventsQuery = useRunEvents(
    runId,
    atEvent,
    activeTab === 'EVENTS',
    activePollInterval(graph?.run?.status) !== false,
  )
  const addHint = useAddHint(runId)
  const submitGate = useSubmitHumanInput(runId)

  const selectionId = selected.run === runId ? selected.id : null
  const selection = resolveSelection(graph, entityGraph, selectionId)
  // A relation edge is a non-node selection: highlight the edge (not a node).
  const selectedEdgeId = selection?.type === 'relation' ? selection.relation.id : null
  const selectedNodeId = selection?.type === 'relation' ? null : selectionId
  // Stable identity so the graph's node memo survives Console re-renders (polls).
  const select = useCallback((id: string | null) => setSelected({ run: runId, id }), [runId])

  // Full Fact (note + verbatim evidence) only for the selected node.
  const factDetailQuery = useFactDetail(
    runId,
    selection?.type === 'fact' ? selection.fact.id : undefined,
    atEvent,
  )

  const graphRun = graph?.run
  const eventCount = graph?.eventCount ?? 0
  const maxStep = eventCount - 1
  const events = eventsQuery.data ?? []

  const project = projects.data?.find((p) => p.id === projectId)

  const notFound =
    graphQuery.error instanceof ConnectError && graphQuery.error.code === Code.NotFound

  const inspector = (
    <Inspector
      run={graphRun}
      selection={selection}
      factDetail={factDetailQuery.data}
      factLoading={factDetailQuery.isFetching}
      factError={
        factDetailQuery.error
          ? factDetailQuery.error instanceof Error
            ? factDetailQuery.error.message
            : String(factDetailQuery.error)
          : undefined
      }
      intents={graph?.intents}
      hints={graph?.hints}
      waitingFor={graph?.waitingFor}
      sessions={sessionsQuery.data}
      onDecision={
        replayStep === null
          ? (decision, text) =>
              submitGate.mutate({ gate: graph?.waitingFor?.gate ?? '', decision, text })
          : undefined
      }
      decisionPending={submitGate.isPending}
      decisionError={
        submitGate.error
          ? submitGate.error instanceof Error
            ? submitGate.error.message
            : String(submitGate.error)
          : undefined
      }
      onAddHint={
        replayStep === null ? (text) => addHint.mutateAsync(text).then(() => undefined) : undefined
      }
    />
  )

  if (notFound) {
    return (
      <div className="console">
        <RunList
          runs={runs.data}
          loading={runs.isLoading}
          error={runs.isError}
          projectId={projectId}
          activeRunId={runId}
        />
        <NotFound />
        {inspector}
      </div>
    )
  }

  if (graphQuery.isError) {
    return (
      <div className="console">
        <RunList
          runs={runs.data}
          loading={runs.isLoading}
          error={runs.isError}
          projectId={projectId}
          activeRunId={runId}
        />
        <section className="col" aria-label="run console">
          <div className="empty">无法加载 run：{graphQuery.error.message}</div>
        </section>
        {inspector}
      </div>
    )
  }

  function renderTab() {
    switch (activeTab) {
      case 'GRAPH':
        return (
          <GraphTab graph={graph} runId={runId} onSelect={select} selectedId={selectedNodeId} />
        )
      case 'FACTS':
        return <FactsTab facts={graph?.facts} onSelect={select} selectedId={selectedNodeId} />
      case 'INTENTS':
        return <IntentsTab intents={graph?.intents} onSelect={select} selectedId={selectedNodeId} />
      case 'RELATIONS':
        return (
          <RelationsTab
            graph={entityGraph}
            runId={runId}
            onSelect={select}
            selectedId={selectedNodeId}
            selectedEdgeId={selectedEdgeId}
            onEdgeClick={select}
          />
        )
      case 'ENTITIES':
        return (
          <EntitiesTab
            entities={entityGraph?.entities}
            onSelect={select}
            selectedId={selectedNodeId}
          />
        )
      case 'EVENTS':
        return <EventsTab events={events} step={replayStep} />
    }
  }

  const runStatus = graphRun?.status
  const statusLabel = runStatus ?? (graphQuery.isLoading ? '…' : '—')
  // In-flight phase while running (server-derived, not an event): shows "推理中…"
  // between graph changes. Non-running runs carry no activity.
  const activity = graphRun && graphRun.status === 'running' ? activityLabel(graphRun.activity) : ''
  const budgetSummary = graphRun
    ? `steps ${graphRun.steps?.current ?? 0}/${graphRun.steps?.total ?? 0}` +
      ` · tok ${String(graphRun.budget?.tokens ?? 0n)}` +
      ` · cost ${(graphRun.budget?.cost ?? 0).toFixed(2)}` +
      ` · intents ${graphRun.intents?.open ?? 0}/${graphRun.intents?.done ?? 0}`
    : ''
  // The folded board is historical, so writing is disabled while replaying.
  const title = graphRun?.title || runId || '—'

  return (
    <div className="console">
      <RunList
        runs={runs.data}
        loading={runs.isLoading}
        error={runs.isError}
        projectId={projectId}
        activeRunId={runId}
      />
      <section className="col console-main" aria-label="run console">
        <header className="center-head">
          <nav className="crumb mono" aria-label="breadcrumb">
            <Link to="/">Projects</Link>
            <span className="crumb-sep">/</span>
            {project ? (
              <Link to={`/projects/${projectId}`}>{project.name || project.id}</Link>
            ) : (
              <span>{projectId ?? '—'}</span>
            )}
            <span className="crumb-sep">/</span>
            <span className="mono crumb-run">{runId ?? '—'}</span>
          </nav>
          <div className="center-title-row">
            <RunTitle key={runId} runId={runId} title={title} editable={replayStep === null} />
            <div className="head-tools">
              {runStatus ? (
                <span className={`status-badge status-${runStatus}`}>{runStatus}</span>
              ) : (
                <span className="cnt mono">{statusLabel}</span>
              )}
              {activity ? (
                <span className="activity" role="status">
                  <i className="activity-dot" aria-hidden />
                  {activity}
                </span>
              ) : null}
              {budgetSummary ? <span className="budget mono">{budgetSummary}</span> : null}
              <div className="replay" role="group" aria-label="replay">
                <button
                  className="btn"
                  type="button"
                  aria-label="replay back"
                  disabled={eventCount === 0}
                  onClick={() =>
                    stepReplay((current) => {
                      if (eventCount === 0) return current
                      if (current === null) return maxStep
                      return Math.max(0, current - 1)
                    })
                  }
                >
                  ◀
                </button>
                <span className="mono replay-step">
                  {replayStep === null ? 'live' : `${replayStep + 1}/${eventCount}`}
                </span>
                <button
                  className="btn"
                  type="button"
                  aria-label="replay forward"
                  disabled={eventCount === 0}
                  onClick={() =>
                    stepReplay((current) => {
                      if (eventCount === 0) return current
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
          </div>
          <div className="tabs" role="tablist">
            {tabs.map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={name === activeTab}
                className={name === activeTab ? 'tab on' : 'tab'}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </div>
        </header>
        <div className="center-body">{renderTab()}</div>
      </section>
      {inspector}
    </div>
  )
}
