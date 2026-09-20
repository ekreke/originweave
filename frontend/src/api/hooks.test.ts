import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AWAITING_POLL_MS,
  awaitingPollInterval,
  useAddHint,
  useCreateRun,
  useSubmitHumanInput,
} from '@/api/hooks'

const mocks = vi.hoisted(() => ({
  addHint: vi.fn(),
  submitHumanInput: vi.fn(),
  createRun: vi.fn(),
}))

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

describe('useSubmitHumanInput', () => {
  beforeEach(() => {
    mocks.submitHumanInput.mockReset().mockResolvedValue({ run: { id: 'run_001' } })
  })

  it('submits the gate, decision and note with the run id', async () => {
    const { result } = renderHook(() => useSubmitHumanInput('run_001'), { wrapper })

    result.current.mutate({ gate: 'confirm-claim', decision: 'edit', text: 'revise' })

    await waitFor(() =>
      expect(mocks.submitHumanInput).toHaveBeenCalledWith({
        runId: 'run_001',
        gate: 'confirm-claim',
        decision: 'edit',
        text: 'revise',
        targets: [],
      }),
    )
  })

  it('refetches the run after resolving a gate', async () => {
    const { result } = renderHook(() => useSubmitHumanInput('run_001'), { wrapper })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    result.current.mutate({ gate: 'arbitrate', decision: 'approve' })

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['run', 'run_001'] }))
  })
})

describe('useCreateRun', () => {
  beforeEach(() => {
    mocks.createRun.mockReset().mockResolvedValue({ run: { id: 'run_007' } })
  })

  it('maps the form input to a text/provenance CreateRunRequest', async () => {
    const { result } = renderHook(() => useCreateRun(), { wrapper })

    result.current.mutate({ projectId: 'p', sourceText: 'doc A', goal: 'g', auto: false })

    await waitFor(() =>
      expect(mocks.createRun).toHaveBeenCalledWith({
        projectId: 'p',
        sourceType: 'text',
        sourceText: 'doc A',
        goal: 'g',
        analysis: 'provenance',
        auto: false,
      }),
    )
  })

  it('includes budget overrides only when provided', async () => {
    const { result } = renderHook(() => useCreateRun(), { wrapper })

    result.current.mutate({
      projectId: 'p',
      sourceText: 'doc A',
      goal: 'g',
      maxSteps: 7,
      maxWall: '10m',
      maxCost: 1.5,
    })

    await waitFor(() =>
      expect(mocks.createRun).toHaveBeenCalledWith(
        expect.objectContaining({ maxSteps: 7, maxWall: '10m', maxCost: 1.5 }),
      ),
    )
  })

  it('refreshes the run and project lists after creating', async () => {
    const { result } = renderHook(() => useCreateRun(), { wrapper })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    result.current.mutate({ projectId: 'p', sourceText: 'd', goal: 'g' })

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['runs'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projects'] })
    })
  })
})
