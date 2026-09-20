import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { Settings } from '@/gen/originweave/v1/originweave_pb'

import { client } from './client'

// Read hooks over the Connect API. The frontend only consumes data (red line 1);
// these wrap the generated client so the views never touch transport details.

export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: async () => (await client.listProjects({})).projects,
  })
}

export function useProjectRuns(projectId: string | undefined) {
  return useQuery({
    queryKey: ['runs', projectId],
    enabled: Boolean(projectId),
    queryFn: async () => (await client.listProjectRuns({ projectId: projectId ?? '' })).runs,
  })
}

// A run that is still active (queued/running/awaiting a human) keeps polling so the
// board advances on its own -- a fresh run shows the Gate card when it pauses, a
// paused run shows the result once the human resolves it. Terminal runs poll nothing.
export const ACTIVE_POLL_MS = 2_000

// `paused` is a declared status but the reducer never emits it yet (M3 controllability);
// include it here if that changes.
const ACTIVE_STATUSES = new Set(['queued', 'running', 'awaiting_human'])

export function activePollInterval(status: string | undefined): number | false {
  return status !== undefined && ACTIVE_STATUSES.has(status) ? ACTIVE_POLL_MS : false
}

// Live run detail. `atEvent` (Replay) asks the server to fold only the first
// `atEvent` events so the board reflects that step; the timeline stays full. Only
// the live view polls.
export function useRun(runId: string | undefined, atEvent?: number | null) {
  const replaying = atEvent != null
  return useQuery({
    queryKey: ['run', runId, atEvent ?? null],
    enabled: Boolean(runId),
    // Keep the previous board visible while stepping (no empty flash, and the
    // timeline length stays stable for the stepper's bounds). Scoped to the same
    // run: navigating to another run must not flash the previous run's board.
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === runId ? previousData : undefined,
    queryFn: async () =>
      (await client.getRun({ runId: runId ?? '', ...(atEvent != null ? { atEvent } : {}) }))
        .runDetail,
    refetchInterval: (query) =>
      replaying ? false : activePollInterval(query.state.data?.run?.status),
  })
}

// Writing a Hint is non-blocking (the server appends a HINT event and the run keeps
// going). Refetch the run so the new hint appears in the Inspector right away.
export function useAddHint(runId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (text: string) => {
      if (!runId) throw new Error('cannot add a hint without a run id')
      return client.addHint({ runId, text })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', runId] }),
  })
}

// Project settings ([worker] + [capability.model]). UpdateSettings treats the whole
// worker block as authoritative, so callers must round-trip the loaded Settings (a
// partial patch with empty scalars would be rejected by the server).
export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: async () => (await client.getSettings({})).settings,
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (settings: Settings) => (await client.updateSettings({ settings })).settings,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export interface CreateRunInput {
  projectId: string
  sourceText: string
  goal: string
  title?: string
  auto?: boolean
  maxSteps?: number
  maxWall?: string
  maxCost?: number
}

// Starting a run spins up a background engine on the server; the returned Run is
// already readable (its status depends on HITL). Refresh the run/project lists after.
export function useCreateRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: CreateRunInput) => {
      const response = await client.createRun({
        projectId: input.projectId,
        sourceType: 'text',
        sourceText: input.sourceText,
        goal: input.goal,
        analysis: 'provenance',
        ...(input.title ? { title: input.title } : {}),
        ...(input.auto !== undefined ? { auto: input.auto } : {}),
        ...(input.maxSteps !== undefined ? { maxSteps: input.maxSteps } : {}),
        ...(input.maxWall ? { maxWall: input.maxWall } : {}),
        ...(input.maxCost !== undefined ? { maxCost: input.maxCost } : {}),
      })
      return response.run
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export interface GateSubmission {
  gate: string
  decision: string
  text?: string
  targets?: string[]
}

// Resolving a HITL gate (Gate A/B): the server writes HUMAN_INPUT and resumes (or
// stops) the run. Refetch so `awaiting_human` clears once the server accepts it.
export function useSubmitHumanInput(runId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (submission: GateSubmission) => {
      if (!runId) throw new Error('cannot submit a gate decision without a run id')
      return client.submitHumanInput({
        runId,
        gate: submission.gate,
        decision: submission.decision,
        text: submission.text ?? '',
        targets: submission.targets ?? [],
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', runId] }),
  })
}
