import { describe, expect, it } from 'vitest'

import { firstSeenAt, visibleIdsAt } from '@/graph/replay'
import { event } from '@/test/fixtures'

describe('firstSeenAt', () => {
  it('maps each node to the event that first introduced it', () => {
    const events = [
      event({ id: 'e1', type: 'PROJECT' }),
      event({ id: 'e2', type: 'INTENT', payload: { intent: { id: 'i1' } } }),
      event({
        id: 'e3',
        type: 'CONCLUDE',
        payload: { intentId: 'i1', facts: [{ id: 'f1' }, { id: 'f2' }] },
      }),
    ]

    const seen = firstSeenAt(events)

    expect(seen.get('origin')).toBe(0)
    expect(seen.get('goal')).toBe(0)
    expect(seen.get('i1')).toBe(1)
    expect(seen.get('f1')).toBe(2)
    expect(seen.get('f2')).toBe(2)
  })

  it('ignores events that introduce no node', () => {
    const events = [event({ id: 'e1', type: 'PROJECT' }), event({ id: 'e2', type: 'HEARTBEAT' })]
    expect(firstSeenAt(events).size).toBe(2)
  })
})

describe('visibleIdsAt', () => {
  const seen = new Map([
    ['origin', 0],
    ['goal', 0],
    ['i1', 2],
    ['f1', 3],
  ])

  it('is monotonic in the step', () => {
    expect([...visibleIdsAt(seen, 0)].sort()).toEqual(['goal', 'origin'])
    expect(visibleIdsAt(seen, 2).has('i1')).toBe(true)
    expect(visibleIdsAt(seen, 3).has('f1')).toBe(true)
  })

  it('excludes nodes introduced after the step', () => {
    expect(visibleIdsAt(seen, 2).has('f1')).toBe(false)
  })
})
