import { useState } from 'react'

import type { Fact, Hint, Intent, WaitingFor } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only inspector: node detail, verbatim evidence, intent/hint counts and
// the HITL gate card. Gate decisions are surfaced via `onDecision` and hints via
// `onAddHint`; submitting them over RPC is the console's job.

export type InspectorSelection = { type: 'fact'; fact: Fact } | { type: 'intent'; intent: Intent }

export type GateDecision = 'approve' | 'edit' | 'reject'

export interface InspectorProps {
  selection?: InspectorSelection | null
  intents?: Intent[]
  hints?: Hint[]
  waitingFor?: WaitingFor
  onDecision?: (decision: GateDecision, text: string) => void
  decisionPending?: boolean
  decisionError?: string
  onAddHint?: (text: string) => void | Promise<void>
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

const STATUS_ORDER = ['open', 'claimed', 'done', 'dropped', 'awaiting_human'] as const

function countByStatus(intents: Intent[]) {
  const counts = new Map<string, number>()
  for (const it of intents) counts.set(it.status, (counts.get(it.status) ?? 0) + 1)
  return counts
}

function FactDetail({ fact }: { fact: Fact }) {
  return (
    <div className="detail">
      <div className="detail-id mono">{fact.id}</div>
      <dl className="detail-grid">
        <dt>kind</dt>
        <dd>{fact.kind}</dd>
        <dt>role</dt>
        <dd>{fact.role}</dd>
        <dt>status</dt>
        <dd>{fact.status}</dd>
        <dt>conf.</dt>
        <dd className="mono">{fact.confidence.toFixed(2)}</dd>
      </dl>
      <p className="detail-note">{fact.label}</p>
      {fact.note ? <p className="detail-note">{fact.note}</p> : null}
      {fact.evidence.length > 0 ? (
        <div className="evidence">
          <h4>证据</h4>
          {fact.evidence.map((e) => (
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
      ) : null}
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
  selection,
  intents,
  hints,
  waitingFor,
  onDecision,
  decisionPending,
  decisionError,
  onAddHint,
}: InspectorProps) {
  const counts = intents && intents.length > 0 ? countByStatus(intents) : null
  const isEmpty = !waitingFor && !selection && !counts

  return (
    <div className="col inspector" aria-label="inspector">
      <h3>INSPECTOR</h3>

      {waitingFor ? (
        <GateCard
          waitingFor={waitingFor}
          onDecision={onDecision}
          pending={decisionPending}
          error={decisionError}
        />
      ) : null}

      {selection?.type === 'fact' ? <FactDetail fact={selection.fact} /> : null}
      {selection?.type === 'intent' ? <IntentDetail intent={selection.intent} /> : null}

      {counts ? (
        <div className="intent-counts">
          <h4>Intents</h4>
          <ul>
            {STATUS_ORDER.filter((s) => counts.has(s)).map((s) => (
              <li key={s}>
                <span className={`status-badge status-${s}`}>{s}</span>
                <span className="mono">{counts.get(s)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {onAddHint || (hints && hints.length > 0) ? (
        <HintsPanel hints={hints} onAddHint={onAddHint} />
      ) : null}

      {isEmpty ? <div className="empty">无选中项。</div> : null}
    </div>
  )
}
