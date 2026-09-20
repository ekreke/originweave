import type { Event } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only event timeline, coloured by tone; the caller supplies the events.
// With a `step` (Replay) only events[0..step] are shown and the current one is
// highlighted; `step` null/undefined is the live, full timeline.
export function EventsTab({ events, step }: { events?: Event[]; step?: number | null }) {
  if (!events || events.length === 0) {
    return (
      <div>
        <div className="panel-hd">
          <h2>EVENTS</h2>
          <span className="cnt">append-only 时间线</span>
        </div>
        <div className="empty">暂无事件。</div>
      </div>
    )
  }

  const shown = step != null ? events.slice(0, step + 1) : events

  return (
    <div>
      <div className="panel-hd">
        <h2>EVENTS</h2>
        <span className="cnt">
          {step != null ? `${shown.length}/${events.length}` : events.length}
        </span>
      </div>
      <ol className="event-list">
        {shown.map((e, index) => (
          <li
            key={e.id}
            className={`event-row tone-${e.tone}${
              step != null && index === shown.length - 1 ? ' event-current' : ''
            }`}
          >
            <span className="mono event-id">{e.id}</span>
            <span className="mono event-type">{e.type}</span>
            <span className="event-msg">{e.message}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
