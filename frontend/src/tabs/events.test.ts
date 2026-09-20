import { describe, expect, it } from 'vitest'

import { ALL_WORKERS, eventWorker, eventWorkers, filterByWorker } from '@/tabs/events'
import { event } from '@/test/fixtures'

const events = [
  event({ id: '1', type: 'PROJECT' }),
  event({ id: '2', type: 'SESSION', payload: { sessionId: 's1', worker: 'worker-1' } }),
  event({ id: '3', type: 'WORKER_STEP', payload: { sessionId: 's1', worker: 'worker-1', seq: 1 } }),
  event({ id: '4', type: 'SESSION', payload: { sessionId: 's2', worker: 'worker-2' } }),
]

describe('events worker helpers', () => {
  it('reads the worker from the payload when present', () => {
    expect(eventWorker(events[0]!)).toBeUndefined()
    expect(eventWorker(events[1]!)).toBe('worker-1')
    expect(eventWorker(event({ payload: { worker: '' } }))).toBeUndefined()
  })

  it('lists distinct workers in first-seen order', () => {
    expect(eventWorkers(events)).toEqual(['worker-1', 'worker-2'])
  })

  it('filters by worker and keeps every event for ALL_WORKERS', () => {
    expect(filterByWorker(events, ALL_WORKERS)).toHaveLength(4)
    expect(filterByWorker(events, 'worker-1').map((e) => e.id)).toEqual(['2', '3'])
    expect(filterByWorker(events, 'nope')).toEqual([])
  })
})
