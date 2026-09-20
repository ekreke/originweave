import type { Event } from '@/gen/originweave/v1/originweave_pb'

// Frontend Replay stepper helper. It does NOT replay the reducer: it only derives the
// event index at which each board node first appears (PROJECT seeds the origin/goal
// anchors, INTENT adds an intent id, CONCLUDE adds the facts it wrote). The console
// uses that to hide nodes/edges that had not been created yet at a given step, then
// still renders with the server's full RunDetail (positions, statuses, edges).

function asObject(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}

function readId(value: unknown): string | undefined {
  const id = asObject(value)?.['id']
  return typeof id === 'string' ? id : undefined
}

export function firstSeenAt(events: Event[]): Map<string, number> {
  const seen = new Map<string, number>()
  events.forEach((event, index) => {
    const payload = asObject(event.payload) ?? {}
    if (event.type === 'PROJECT') {
      seen.set(readId(payload['origin']) ?? 'origin', index)
      seen.set(readId(payload['goal']) ?? 'goal', index)
    } else if (event.type === 'INTENT') {
      const id = readId(payload['intent'])
      if (id) seen.set(id, index)
    } else if (event.type === 'CONCLUDE') {
      const facts = payload['facts']
      if (Array.isArray(facts)) {
        for (const fact of facts) {
          const id = readId(fact)
          if (id && !seen.has(id)) seen.set(id, index)
        }
      }
    }
  })
  return seen
}

// Ids whose first appearance is at or before `step`; undefined means "no filter"
// (live view).
export function visibleIdsAt(seen: Map<string, number>, step: number): Set<string> {
  const visible = new Set<string>()
  for (const [id, index] of seen) {
    if (index <= step) visible.add(id)
  }
  return visible
}
