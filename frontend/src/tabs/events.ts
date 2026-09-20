import type { Event } from '@/gen/originweave/v1/originweave_pb'

// Pure helpers for the EVENTS tab, kept out of the component file so the tab only
// exports a component. A worker id lives on SESSION/WORKER_STEP payloads (M6).

export const ALL_WORKERS = 'all'

export function eventWorker(event: Event): string | undefined {
  const worker = event.payload?.worker
  return typeof worker === 'string' && worker ? worker : undefined
}

export function eventWorkers(events: Event[]): string[] {
  const seen: string[] = []
  for (const event of events) {
    const worker = eventWorker(event)
    if (worker && !seen.includes(worker)) seen.push(worker)
  }
  return seen
}

export function filterByWorker(events: Event[], worker: string): Event[] {
  if (worker === ALL_WORKERS) return events
  return events.filter((event) => eventWorker(event) === worker)
}
