import { useState } from 'react'

import type { Event } from '@/gen/originweave/v1/originweave_pb'
import { ALL_WORKERS, eventWorkers, filterByWorker } from '@/tabs/events'

// Presentation-only event timeline, coloured by tone and filterable by worker. With a
// `step` (Replay) only events[0..step] are shown and the current one is highlighted;
// `step` null/undefined is the live, full timeline.
export function EventsTab({ events, step }: { events?: Event[]; step?: number | null }) {
  const [worker, setWorker] = useState<string>(ALL_WORKERS)

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

  const sliced = step != null ? events.slice(0, step + 1) : events
  const workers = eventWorkers(sliced)
  // Clamp a stale filter (e.g. left over after switching runs): a worker with no events
  // in view falls back to "all" so the select never points at a missing option.
  const activeWorker = worker !== ALL_WORKERS && workers.includes(worker) ? worker : ALL_WORKERS
  const shown = filterByWorker(sliced, activeWorker)
  const filtering = activeWorker !== ALL_WORKERS || step != null
  // The Replay cursor is the last sliced event; match by id so a worker filter does not
  // move the highlight onto an unrelated row.
  const currentId = step != null ? sliced[sliced.length - 1]?.id : undefined

  return (
    <div>
      <div className="panel-hd">
        <h2>EVENTS</h2>
        {workers.length > 0 ? (
          <select
            className="btn"
            aria-label="worker filter"
            value={activeWorker}
            onChange={(event) => setWorker(event.target.value)}
          >
            <option value={ALL_WORKERS}>all workers</option>
            {workers.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : null}
        <span className="cnt">
          {filtering ? `${shown.length}/${events.length}` : events.length}
        </span>
      </div>
      <ol className="event-list">
        {shown.map((e) => (
          <li
            key={e.id}
            className={`event-row tone-${e.tone}${
              currentId !== undefined && e.id === currentId ? ' event-current' : ''
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
