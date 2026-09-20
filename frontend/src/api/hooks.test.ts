import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ACTIVE_POLL_MS,
  activePollInterval,
  useAddHint,
  useCreateProject,
  useCreateRun,
  useFactDetail,
  useRun,
  useRunGraph,
  useRunEvents,
  useRunSessions,
  useSettings,
  useSubmitHumanInput,
  useUpdateSettings,
} from '@/api/hooks'
import { settings } from '@/test/fixtures'

const mocks = vi.hoisted(() => ({
  addHint: vi.fn(),
  submitHumanInput: vi.fn(),
  createRun: vi.fn(),
  createProject: vi.fn(),
  getRun: vi.fn(),
  getRunGraph: vi.fn(),
  getFactDetail: vi.fn(),
  listEvents: vi.fn(),
  listSessions: vi.fn(),
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}))

vi.mock('@/api/client', () => ({ client: mocks }))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

describe('activePollInterval', () => {
  it('polls while the run is still active and stops on a terminal state', () => {
    expect(activePollInterval('queued')).toBe(ACTIVE_POLL_MS)
    expect(activePollInterval('running')).toBe(ACTIVE_POLL_MS)
    expect(activePollInterval('awaiting_human')).toBe(ACTIVE_POLL_MS)
    expect(activePollInterval('completed')).toBe(false)
    expect(activePollInterval('failed')).toBe(false)
    expect(activePollInterval(undefined)).toBe(false)
  })
})

describe('useRun', () => {
  beforeEach(() => {
    mocks.getRun.mockReset().mockResolvedValue({ runDetail: {} })
  })

  it('forwards at_event when replaying', async () => {
    const { result } = renderHook(() => useRun('run_001', 3), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mocks.getRun).toHaveBeenCalledWith({ runId: 'run_001', atEvent: 3 })
  })

  it('omits at_event for the live view', async () => {
    const { result } = renderHook(() => useRun('run_001'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mocks.getRun).toHaveBeenCalledWith({ runId: 'run_001' })
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

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['run-graph', 'run_001'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['run-events', 'run_001'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['sessions', 'run_001'] })
    })
  })
})

describe('useRunGraph', () => {
  beforeEach(() => {
    mocks.getRunGraph.mockReset().mockResolvedValue({ graph: {} })
  })

  it('forwards at_event when replaying', async () => {
    const { result } = renderHook(() => useRunGraph('run_001', 3), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mocks.getRunGraph).toHaveBeenCalledWith({ runId: 'run_001', atEvent: 3 })
  })

  it('omits at_event for the live view', async () => {
    const { result } = renderHook(() => useRunGraph('run_001'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mocks.getRunGraph).toHaveBeenCalledWith({ runId: 'run_001' })
  })
})

describe('useFactDetail', () => {
  beforeEach(() => {
    mocks.getFactDetail.mockReset().mockResolvedValue({ fact: { id: 'f1' } })
  })

  it('fetches the selected fact, forwarding at_event', async () => {
    const { result } = renderHook(() => useFactDetail('run_001', 'f1', 2), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mocks.getFactDetail).toHaveBeenCalledWith({ runId: 'run_001', factId: 'f1', atEvent: 2 })
  })

  it('stays idle without a selection', async () => {
    const { result } = renderHook(() => useFactDetail('run_001', undefined), { wrapper })
    expect(result.current.fetchStatus).toBe('idle')
    expect(mocks.getFactDetail).not.toHaveBeenCalled()
  })
})

describe('useRunEvents', () => {
  beforeEach(() => {
    mocks.listEvents.mockReset().mockResolvedValue({ events: [] })
  })

  it('fetches the timeline only when enabled', async () => {
    const { result, rerender } = renderHook(
      ({ enabled }) => useRunEvents('run_001', null, enabled),
      { wrapper, initialProps: { enabled: false } },
    )
    expect(result.current.fetchStatus).toBe('idle')

    rerender({ enabled: true })
    await waitFor(() => expect(mocks.listEvents).toHaveBeenCalledWith({ runId: 'run_001' }))
  })

  it('forwards at_event while replaying', async () => {
    renderHook(() => useRunEvents('run_001', 2, true), { wrapper })
    await waitFor(() =>
      expect(mocks.listEvents).toHaveBeenCalledWith({ runId: 'run_001', atEvent: 2 }),
    )
  })
})

describe('useRunSessions', () => {
  beforeEach(() => {
    mocks.listSessions.mockReset().mockResolvedValue({ sessions: [] })
  })

  it('loads the session snapshots for the run', async () => {
    const { result } = renderHook(() => useRunSessions('run_001'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mocks.listSessions).toHaveBeenCalledWith({ runId: 'run_001' })
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

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['run-graph', 'run_001'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['fact', 'run_001'] })
    })
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

describe('useSettings', () => {
  beforeEach(() => {
    mocks.getSettings.mockReset().mockResolvedValue({ settings: settings() })
  })

  it('loads the project settings', async () => {
    const { result } = renderHook(() => useSettings(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mocks.getSettings).toHaveBeenCalledWith({})
    expect(result.current.data?.worker?.provider).toBe('pi')
  })
})

describe('useUpdateSettings', () => {
  beforeEach(() => {
    mocks.updateSettings.mockReset().mockResolvedValue({ settings: settings() })
  })

  it('sends the whole settings message and refreshes the cache', async () => {
    const { result } = renderHook(() => useUpdateSettings(), { wrapper })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    result.current.mutate(settings())

    await waitFor(() => expect(mocks.updateSettings).toHaveBeenCalledTimes(1))
    const request = mocks.updateSettings.mock.calls[0]![0] as {
      settings: { worker?: { provider: string } }
    }
    expect(request.settings.worker?.provider).toBe('pi')
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['settings'] }))
  })
})

describe('useCreateProject', () => {
  beforeEach(() => {
    mocks.createProject.mockReset().mockResolvedValue({ project: { id: 'newp', name: 'New' } })
  })

  it('sends the project identity and refreshes the project list', async () => {
    const { result } = renderHook(() => useCreateProject(), { wrapper })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    result.current.mutate({ id: 'newp', name: 'New', description: 'd' })

    await waitFor(() => expect(mocks.createProject).toHaveBeenCalledTimes(1))
    expect(mocks.createProject).toHaveBeenCalledWith({
      id: 'newp',
      name: 'New',
      description: 'd',
    })
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projects'] }))
  })
})
