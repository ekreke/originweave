import { useQuery } from '@tanstack/react-query'

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

// A run awaiting a human decision keeps polling so the Gate/Continue state appears
// without a manual refresh; every other status polls nothing.
export const AWAITING_POLL_MS = 2_000

export function awaitingPollInterval(status: string | undefined): number | false {
  return status === 'awaiting_human' ? AWAITING_POLL_MS : false
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['run', runId],
    enabled: Boolean(runId),
    queryFn: async () => (await client.getRun({ runId: runId ?? '' })).runDetail,
    refetchInterval: (query) => awaitingPollInterval(query.state.data?.run?.status),
  })
}
