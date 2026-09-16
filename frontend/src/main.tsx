import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import '@xyflow/react/dist/style.css'
import '@/styles/tokens.css'
import '@/styles/base.css'

import { App } from '@/App'
import { ThemeProvider } from '@/theme/ThemeProvider'

const container = document.getElementById('root')
if (!container) {
  throw new Error('#root element not found')
}

createRoot(container).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
