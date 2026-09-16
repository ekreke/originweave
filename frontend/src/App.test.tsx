import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { App } from '@/App'
import { ThemeProvider } from '@/theme/ThemeProvider'

function renderAt(path: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </ThemeProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('app shell', () => {
  it('renders the brand and primary navigation', () => {
    renderAt('/')
    expect(screen.getByTestId('brand')).toHaveTextContent('originweave')
    expect(screen.getByRole('navigation', { name: 'main' })).toBeInTheDocument()
  })

  it('renders the three-column console with tabs and an empty graph canvas', () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    expect(screen.getByLabelText('run list')).toBeInTheDocument()
    expect(screen.getByLabelText('inspector')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'GRAPH' })).toHaveAttribute('aria-selected', 'true')
    const canvas = screen.getByTestId('graph-canvas')
    expect(canvas).toBeInTheDocument()
    expect(canvas.querySelector('.react-flow')).not.toBeNull()
  })

  it('switches tabs and toggles the theme', () => {
    renderAt('/projects/copilot-productivity/runs/run_009')

    fireEvent.click(screen.getByRole('tab', { name: 'FACTS' }))
    expect(screen.getByText(/暂无事实节点/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Theme/ }))
    expect(document.documentElement).toHaveClass('dark')
  })
})
