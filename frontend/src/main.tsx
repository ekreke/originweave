import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'

import '@xyflow/react/dist/style.css'
import '@/styles/tokens.css'
import '@/styles/base.css'
import '@/styles/presentation.css'

import { App } from '@/App'
import { createQueryClient } from '@/api/queryClient'
import { ThemeProvider } from '@/theme/ThemeProvider'

const container = document.getElementById('root')
if (!container) {
  throw new Error('#root element not found')
}

const queryClient = createQueryClient()

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
