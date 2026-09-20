import { QueryClient } from '@tanstack/react-query'

// One query client per app. Board data is event-derived and cheap to refetch, so a
// short stale time is enough; individual queries opt into polling when they need it
// (e.g. a run that is awaiting human input).
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  })
}
