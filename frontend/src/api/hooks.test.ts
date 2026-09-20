import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AWAITING_POLL_MS, awaitingPollInterval, useAddHint } from '@/api/hooks'

const mocks = vi.hoisted(() => ({ addHint: vi.fn() }))

vi.mock('@/api/client', () => ({ client: mocks }))

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return createElement(QueryClientProvider, { client }, children)
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
    mocks.addHint
      .mockReset()
      .mockResolvedValue({ hint: { id: 'h1', text: 'x', author: 'human', createdAt: '' } })
  })

  it('calls AddHint with the run id and text', async () => {
    const { result } = renderHook(() => useAddHint('run_001'), { wrapper })

    result.current.mutate('check it')

    await waitFor(() =>
      expect(mocks.addHint).toHaveBeenCalledWith({ runId: 'run_001', text: 'check it' }),
    )
  })
})
