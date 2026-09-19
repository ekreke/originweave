import type { Event } from '@/gen/originweave/v1/originweave_pb'

// Presentation-only event timeline, coloured by tone. Without data it keeps the
// M1b empty state; wiring to the server lands in M1c-2b.
export function EventsTab({ events }: { events?: Event[] }) {
  if (!events || events.length === 0) {
    return (
      <div>
        <div className="panel-hd">
          <h2>EVENTS</h2>
          <span className="cnt">append-only 时间线</span>
        </div>
        <div className="empty">暂无事件。数据由 server 提供（M1c）。</div>
      </div>
    )
  }

  return (
    <div>
      <div className="panel-hd">
        <h2>EVENTS</h2>
        <span className="cnt">{events.length}</span>
      </div>
      <ol className="event-list">
        {events.map((e) => (
          <li key={e.id} className={`event-row tone-${e.tone}`}>
            <span className="mono event-id">{e.id}</span>
            <span className="mono event-type">{e.type}</span>
            <span className="event-msg">{e.message}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
