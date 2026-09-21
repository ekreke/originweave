import { useState } from 'react'

import type {
  Evidence,
  Fact,
  FactSummary,
  Hint,
  Intent,
  Run,
  Session,
  WaitingFor,
} from '@/gen/originweave/v1/originweave_pb'

// Presentation-only inspector: run stat tiles, node detail (summary now, verbatim
// evidence on demand), the HITL gate card and the worker session view. Gate
// decisions are surfaced via `onDecision` and hints via `onAddHint`; submitting
// them over RPC is the console's job.

export type InspectorSelection =
  { type: 'fact'; fact: FactSummary } | { type: 'intent'; intent: Intent }

export type GateDecision = 'approve' | 'edit' | 'reject'

export interface InspectorProps {
  run?: Run
  selection?: InspectorSelection | null
  /** Full Fact (note + verbatim evidence) fetched on demand for the selection. */
  factDetail?: Fact
  factLoading?: boolean
  factError?: string
  intents?: Intent[]
  hints?: Hint[]
  waitingFor?: WaitingFor
  sessions?: Session[]
  onDecision?: (decision: GateDecision, text: string) => void
  decisionPending?: boolean
  decisionError?: string
  onAddHint?: (text: string) => void | Promise<void>
}

// One Worker call's history: raw input/output plus the step chain (M6). Collapsed by
// default so a run with many sessions stays readable.
function SessionView({ session }: { session: Session }) {
  return (
    <details className="session">
      <summary>
        <span className="mono session-id">{session.id}</span>
        <span className="status-badge status-claimed">{session.task}</span>
        <span className="mono session-worker">{session.worker}</span>
      </summary>
      <dl className="detail-grid">
        <dt>model</dt>
        <dd className="mono">{session.model}</dd>
        {session.intentId ? (
          <>
            <dt>intent</dt>
            <dd className="mono">{session.intentId}</dd>
          </>
        ) : null}
        <dt>started</dt>
        <dd className="mono">{session.startedAt}</dd>
        <dt>ended</dt>
        <dd className="mono">{session.endedAt}</dd>
      </dl>
      <h4>原始输入</h4>
      <pre className="session-io">{JSON.stringify(session.input ?? {}, null, 2)}</pre>
      <h4>原始输出</h4>
      <pre className="session-io">{session.output}</pre>
      <h4>步骤链</h4>
      <ol className="session-steps">
        {session.steps.map((step) => (
          <li key={step.seq} className="session-step">
            <span className="mono session-step-seq">{step.seq}</span>
            <span className="mono session-step-kind">{step.kind}</span>
            {step.name ? <span className="mono session-step-name">{step.name}</span> : null}
            {step.ok === false ? <span className="gate-error">error</span> : null}
            {step.text ? <span className="session-step-text">{step.text}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  )
}

// A non-blocking Hint input: submit reports the text upward and clears it only after
// the write resolves (a failure keeps the text so the user can retry and shows the
// error). Without an `onAddHint` handler the control stays disabled (read-only).
function HintsPanel({
  hints,
  onAddHint,
}: {
  hints?: Hint[]
  onAddHint?: (text: string) => void | Promise<void>
}) {
  const [text, setText] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    const value = text.trim()
    if (!value || !onAddHint || pending) return
    setPending(true)
    setError('')
    try {
      await onAddHint(value)
      setText('')
    } catch (cause) {
      // Keep the text so the user can retry after a failed write.
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="hints">
      <h4>Hints</h4>
      {hints && hints.length > 0 ? (
        <ul className="hints-list">
          {hints.map((hint) => (
            <li key={hint.id}>
              <span className="hint-author mono">{hint.author}</span>
              <span className="hint-text">{hint.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="cnt">暂无 Hints。</p>
      )}
      <div className="hint-form">
        <input
          className="btn"
          aria-label="hint input"
          placeholder="写一条 Hint…"
          value={text}
          disabled={!onAddHint || pending}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Ignore Enter while an IME composition is in progress (Chinese input).
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
              event.preventDefault()
              void submit()
            }
          }}
        />
        <button
          className="btn"
          type="button"
          disabled={!onAddHint || pending || !text.trim()}
          onClick={() => void submit()}
        >
          提交
        </button>
      </div>
      {error ? <p className="hint-error">{error}</p> : null}
    </div>
  )
}

// Gate A/B card: approve/edit/reject plus an optional correction note (used by
// `edit`). The gate id is rendered as-is so Gate C works unchanged once M3 enables it.
function GateCard({
  waitingFor,
  onDecision,
  pending,
  error,
}: {
  waitingFor: WaitingFor
  onDecision?: (decision: GateDecision, text: string) => void
  pending?: boolean
  error?: string
}) {
  const [note, setNote] = useState('')
  return (
    <div className="gate-card">
      <div className="gate-hd">
        <span className="status-badge status-awaiting_human">{waitingFor.gate}</span>
      </div>
      <p>{waitingFor.question}</p>
      <input
        className="btn gate-note"
        aria-label="gate note"
        placeholder="修正说明（edit 时使用）"
        value={note}
        disabled={!onDecision || pending}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className="gate-actions">
        {(['approve', 'edit', 'reject'] as const).map((decision) => (
          <button
            key={decision}
            type="button"
            className="btn"
            disabled={!onDecision || pending}
            onClick={() => onDecision?.(decision, note.trim())}
          >
            {decision}
          </button>
        ))}
      </div>
      {error ? <p className="gate-error">{error}</p> : null}
    </div>
  )
}

// Run-level stat tiles + meta rows (dashboard.md §2 INSPECTOR).
function RunStats({ run, intents, hints }: { run: Run; intents?: Intent[]; hints?: Hint[] }) {
  // Keyed by run id: navigating to another run must start collapsed again (the
  // Inspector component instance is reused across runs by the console).
  const [openReasonFor, setOpenReasonFor] = useState<string | null>(null)
  const open = (intents ?? []).filter((it) => it.status === 'open').length
  const stats = [
    [run.facts, 'FACTS'],
    [intents?.length ?? 0, 'INTENTS'],
    [open, 'OPEN'],
    [hints?.length ?? 0, 'HINTS'],
  ] as const
  // A failed/stopped run carries its terminal reason (derived from the event log);
  // an opaque status badge alone leaves the user unable to tell why it died.
  const terminal = run.status === 'failed' || run.status === 'stopped'
  const reasonLabel = run.status === 'failed' ? '失败原因' : '终止原因'
  const reason = terminal ? run.statusReason : ''
  const showReason = openReasonFor === run.id
  return (
    <div className="run-stats">
      <div className="stat-grid">
        {stats.map(([value, label]) => (
          <div key={label} className="stat">
            <b className="mono">{value}</b>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <dl className="meta-rows">
        <dt>Status</dt>
        <dd>
          <span className={`status-badge status-${run.status}`}>{run.status}</span>
          {reason ? (
            <button
              className="btn status-reason-toggle"
              type="button"
              aria-expanded={showReason}
              aria-controls="run-status-reason"
              onClick={() => setOpenReasonFor(showReason ? null : run.id)}
            >
              {showReason ? '收起' : reasonLabel}
            </button>
          ) : null}
        </dd>
        {run.goal ? (
          <>
            <dt>Goal</dt>
            <dd>{run.goal}</dd>
          </>
        ) : null}
        {run.createdAt ? (
          <>
            <dt>Created</dt>
            <dd className="mono">{run.createdAt}</dd>
          </>
        ) : null}
        <dt>Steps</dt>
        <dd className="mono">
          {run.steps?.current ?? 0}/{run.steps?.total ?? 0}
        </dd>
        <dt>Conf.</dt>
        <dd className="mono">{run.confidence.toFixed(2)}</dd>
        <dt>Budget</dt>
        <dd className="mono">
          tok {String(run.budget?.tokens ?? 0n)} · ${(run.budget?.cost ?? 0).toFixed(2)}
        </dd>
      </dl>
      {reason && showReason ? (
        <div id="run-status-reason" className="status-reason" role="note">
          <h4>{reasonLabel}</h4>
          <p className="status-reason-text">{reason}</p>
        </div>
      ) : null}
    </div>
  )
}

function EvidenceBlock({ evidence }: { evidence: Evidence[] }) {
  return (
    <div className="evidence">
      <h4>证据</h4>
      {evidence.map((e) => (
        <figure key={e.id} className="evidence-item">
          <blockquote>{e.quote}</blockquote>
          <figcaption>
            <span>{e.sourceTitle}</span>
            {e.locator ? <span className="mono"> · {e.locator}</span> : null}
            {e.url ? (
              <a href={e.url} target="_blank" rel="noreferrer">
                {e.url}
              </a>
            ) : null}
          </figcaption>
        </figure>
      ))}
    </div>
  )
}

// Fact detail: the light summary immediately, the heavy part (note + verbatim
// evidence) as soon as the on-demand RPC resolves.
function FactSection({
  summary,
  detail,
  loading,
  error,
}: {
  summary: FactSummary
  detail?: Fact
  loading?: boolean
  error?: string
}) {
  return (
    <div className="detail">
      <div className="detail-id mono">{summary.id}</div>
      <dl className="detail-grid">
        <dt>kind</dt>
        <dd>{summary.kind}</dd>
        <dt>role</dt>
        <dd>{summary.role}</dd>
        <dt>status</dt>
        <dd>{summary.status}</dd>
        <dt>conf.</dt>
        <dd className="mono">{summary.confidence.toFixed(2)}</dd>
        <dt>evidence</dt>
        <dd className="mono">{summary.evidenceCount}</dd>
      </dl>
      <div className="detail-scroll">{summary.label}</div>
      {loading ? <p className="cnt">加载详情…</p> : null}
      {error ? <p className="gate-error">{error}</p> : null}
      {detail?.note ? <div className="detail-scroll">{detail.note}</div> : null}
      {detail && detail.evidence.length > 0 ? <EvidenceBlock evidence={detail.evidence} /> : null}
    </div>
  )
}

function IntentDetail({ intent }: { intent: Intent }) {
  return (
    <div className="detail">
      <div className="detail-id mono">{intent.id}</div>
      <dl className="detail-grid">
        <dt>type</dt>
        <dd>{intent.type}</dd>
        <dt>status</dt>
        <dd>
          <span className={`status-badge status-${intent.status}`}>{intent.status}</span>
        </dd>
        <dt>from</dt>
        <dd className="mono">{intent.from}</dd>
        {intent.claimedBy ? (
          <>
            <dt>claimed by</dt>
            <dd className="mono">{intent.claimedBy}</dd>
          </>
        ) : null}
        {intent.duplicateOf ? (
          <>
            <dt>duplicate of</dt>
            <dd className="mono">{intent.duplicateOf}</dd>
          </>
        ) : null}
      </dl>
      <p className="detail-note">{intent.question}</p>
      {intent.producedFacts.length > 0 ? (
        <p className="cnt">produced: {intent.producedFacts.join(', ')}</p>
      ) : null}
    </div>
  )
}

export function Inspector({
  run,
  selection,
  factDetail,
  factLoading,
  factError,
  intents,
  hints,
  waitingFor,
  sessions,
  onDecision,
  decisionPending,
  decisionError,
  onAddHint,
}: InspectorProps) {
  const intentSessions =
    selection?.type === 'intent'
      ? (sessions ?? []).filter((session) => session.intentId === selection.intent.id)
      : []
  // Bootstrap/Reason/Validate sessions have no Intent; surface them separately.
  const taskSessions = (sessions ?? []).filter((session) => !session.intentId)
  const hasSessions = intentSessions.length > 0 || taskSessions.length > 0
  const isEmpty = !run && !waitingFor && !selection && !hasSessions

  return (
    <div className="col inspector" aria-label="inspector">
      <h3>INSPECTOR</h3>

      {run ? <RunStats run={run} intents={intents} hints={hints} /> : null}

      {waitingFor ? (
        <GateCard
          waitingFor={waitingFor}
          onDecision={onDecision}
          pending={decisionPending}
          error={decisionError}
        />
      ) : null}

      {selection?.type === 'fact' ? (
        <FactSection
          summary={selection.fact}
          detail={factDetail}
          loading={factLoading}
          error={factError}
        />
      ) : null}
      {selection?.type === 'intent' ? <IntentDetail intent={selection.intent} /> : null}

      {intentSessions.length > 0 ? (
        <div className="sessions">
          <h4>会话</h4>
          {intentSessions.map((session) => (
            <SessionView key={session.id} session={session} />
          ))}
        </div>
      ) : null}

      {taskSessions.length > 0 ? (
        <div className="sessions">
          <h4>任务会话</h4>
          {taskSessions.map((session) => (
            <SessionView key={session.id} session={session} />
          ))}
        </div>
      ) : null}

      {onAddHint || (hints && hints.length > 0) ? (
        <HintsPanel hints={hints} onAddHint={onAddHint} />
      ) : null}

      {isEmpty ? <div className="empty">无选中项。</div> : null}
    </div>
  )
}
