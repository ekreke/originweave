import type { Fact, Intent, WaitingFor } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only inspector: node detail, verbatim evidence, intent counts and
// the HITL gate card. Gate decisions are surfaced via `onDecision`; submitting
// them over RPC lands in M1c-2b.

export type InspectorSelection = { type: 'fact'; fact: Fact } | { type: 'intent'; intent: Intent }

export type GateDecision = 'approve' | 'edit' | 'reject'

export interface InspectorProps {
  selection?: InspectorSelection | null
  intents?: Intent[]
  waitingFor?: WaitingFor
  onDecision?: (decision: GateDecision) => void
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

export function Inspector({ selection, intents, waitingFor, onDecision }: InspectorProps) {
  const counts = intents && intents.length > 0 ? countByStatus(intents) : null
  const isEmpty = !waitingFor && !selection && !counts

  return (
    <div className="col inspector" aria-label="inspector">
      <h3>INSPECTOR</h3>

      {waitingFor ? (
        <div className="gate-card">
          <div className="gate-hd">
            <span className="status-badge status-awaiting_human">{waitingFor.gate}</span>
          </div>
          <p>{waitingFor.question}</p>
          <div className="gate-actions">
            {(['approve', 'edit', 'reject'] as const).map((d) => (
              <button
                key={d}
                type="button"
                className="btn"
                disabled={!onDecision}
                onClick={() => onDecision?.(d)}
              >
                {d}
              </button>
            ))}
          </div>
        </div>
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

      {isEmpty ? <div className="empty">无选中项。数据由 server 提供（M1c）。</div> : null}
    </div>
  )
}
