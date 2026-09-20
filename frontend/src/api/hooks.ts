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

export interface CreateProjectInput {
  id: string
  name: string
  description?: string
  accent?: string
}

// Creating a project is the only way to start a run (CreateRun needs one to exist).
// A duplicate id is rejected by the server (ALREADY_EXISTS), not silently reused.
export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: CreateProjectInput) => {
      const response = await client.createProject({
        id: input.id,
        name: input.name,
        ...(input.description ? { description: input.description } : {}),
        ...(input.accent ? { accent: input.accent } : {}),
      })
      return response.project
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
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

// Live run graph (light projection, dashboard.md §4). The console polls this --
// not the full RunDetail -- so evidence quotes / session IO / event payloads stay
// off the hot path. `atEvent` (Replay) folds the board server-side; only the live
// view polls.
export function useRunGraph(runId: string | undefined, atEvent?: number | null) {
  const replaying = atEvent != null
  return useQuery({
    queryKey: ['run-graph', runId, atEvent ?? null],
    enabled: Boolean(runId),
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === runId ? previousData : undefined,
    queryFn: async () =>
      (await client.getRunGraph({ runId: runId ?? '', ...(atEvent != null ? { atEvent } : {}) }))
        .graph,
    refetchInterval: (query) =>
      replaying ? false : activePollInterval(query.state.data?.run?.status),
  })
}

// Full Fact (note + verbatim evidence) for the Inspector, fetched only when a node
// is selected. Replayed boards are historical and deterministic, so their details
// cache forever; a live board may still upsert facts, so its details refetch.
export function useFactDetail(
  runId: string | undefined,
  factId: string | undefined,
  atEvent?: number | null,
) {
  const replaying = atEvent != null
  return useQuery({
    queryKey: ['fact', runId, factId, atEvent ?? null],
    enabled: Boolean(runId && factId),
    staleTime: replaying ? Infinity : 0,
    queryFn: async () =>
      (
        await client.getFactDetail({
          runId: runId ?? '',
          factId: factId ?? '',
          ...(atEvent != null ? { atEvent } : {}),
        })
      ).fact,
  })
}

// Event timeline for the EVENTS tab; `enabled` gates it behind the tab being
// active so a polled console does not drag the (payload-heavy) log along. Polling
// additionally stops while replaying: a folded slice never changes.
export function useRunEvents(
  runId: string | undefined,
  atEvent?: number | null,
  enabled = true,
  active = false,
) {
  return useQuery({
    queryKey: ['run-events', runId, atEvent ?? null],
    enabled: Boolean(runId) && enabled,
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === runId ? previousData : undefined,
    queryFn: async () =>
      (await client.listEvents({ runId: runId ?? '', ...(atEvent != null ? { atEvent } : {}) }))
        .events,
    refetchInterval: active && atEvent == null ? ACTIVE_POLL_MS : false,
  })
}

// Worker session snapshots (raw input/output) for the Inspector. Not polled: they
// are fetched on mount / selection and refreshed after gate & hint writes.
export function useRunSessions(runId: string | undefined) {
  return useQuery({
    queryKey: ['sessions', runId],
    enabled: Boolean(runId),
    staleTime: 10_000,
    queryFn: async () => (await client.listSessions({ runId: runId ?? '' })).sessions,
  })
}

// Writing a Hint is non-blocking (the server appends a HINT event and the run keeps
// going). Refetch the graph (hints live there), events and sessions so the new
// hint shows up right away.
export function useAddHint(runId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (text: string) => {
      if (!runId) throw new Error('cannot add a hint without a run id')
      return client.addHint({ runId, text })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['run-graph', runId] })
      void queryClient.invalidateQueries({ queryKey: ['run-events', runId] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', runId] })
    },
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
// stops) the run. Refetch the graph/events/sessions so `awaiting_human` clears and
// the resumed activity shows up right away.
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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['run-graph', runId] })
      void queryClient.invalidateQueries({ queryKey: ['run-events', runId] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', runId] })
      // A live-selected fact may have been upserted by the resumed run.
      void queryClient.invalidateQueries({ queryKey: ['fact', runId] })
    },
  })
}
