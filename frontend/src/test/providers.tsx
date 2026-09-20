import { useState, type ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { createQueryClient } from '@/api/queryClient'
import { ThemeProvider } from '@/theme/ThemeProvider'

// Test-only wrapper: a fresh QueryClient per render (no cross-test cache) plus the
// router and theme the app expects. Production wires these in main.tsx.
export function AppProviders({ children, path = '/' }: { children: ReactNode; path?: string }) {
  const [queryClient] = useState(() => {
    const client = createQueryClient()
    // No retries in tests: error states surface immediately.
    client.setDefaultOptions({ queries: { retry: false } })
    return client
  })
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
