import { describe, expect, it } from 'vitest'

import { AWAITING_POLL_MS, awaitingPollInterval } from '@/api/hooks'

describe('awaitingPollInterval', () => {
  it('polls only while a run awaits human input', () => {
    expect(awaitingPollInterval('awaiting_human')).toBe(AWAITING_POLL_MS)
    expect(awaitingPollInterval('running')).toBe(false)
    expect(awaitingPollInterval(undefined)).toBe(false)
  })
})
