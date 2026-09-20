import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AWAITING_POLL_MS, awaitingPollInterval, useAddHint } from '@/api/hooks'

const mocks = vi.hoisted(() => ({ addHint: vi.fn() }))

vi.mock('@/api/client', () => ({ client: mocks }))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

describe('awaitingPollInterval', () => {
  it('polls only while a run awaits human input', () => {
    expect(awaitingPollInterval('awaiting_human')).toBe(AWAITING_POLL_MS)
    expect(awaitingPollInterval('running')).toBe(false)
    expect(awaitingPollInterval(undefined)).toBe(false)
  })
})

describe('useAddHint', () => {
  beforeEach(() => {
    mocks.addHint.mockReset().mockResolvedValue({ hint: undefined })
  })

  it('calls AddHint with the run id and the trimmed-by-caller text', async () => {
    const { result } = renderHook(() => useAddHint('run_001'), { wrapper })

    result.current.mutate('check it')

    await waitFor(() =>
      expect(mocks.addHint).toHaveBeenCalledWith({ runId: 'run_001', text: 'check it' }),
    )
  })

  it('refetches the run after adding a hint', async () => {
    const { result } = renderHook(() => useAddHint('run_001'), { wrapper })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    result.current.mutate('check it')

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['run', 'run_001'] }))
  })
})
