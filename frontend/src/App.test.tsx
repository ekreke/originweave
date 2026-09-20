import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '@/App'
import { AppProviders } from '@/test/providers'
import { sampleRunGraph } from '@/test/fixtures'

const mocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listProjectRuns: vi.fn(),
  getRun: vi.fn(),
  getRunGraph: vi.fn(),
  getFactDetail: vi.fn(),
  listEvents: vi.fn(),
  listSessions: vi.fn(),
}))

vi.mock('@/api/client', () => ({ client: mocks }))

function renderAt(path: string) {
  return render(
    <AppProviders path={path}>
      <App />
    </AppProviders>,
  )
}

beforeEach(() => {
  mocks.listProjects.mockReset().mockResolvedValue({ projects: [] })
  mocks.listProjectRuns.mockReset().mockResolvedValue({ runs: [] })
  mocks.getRun.mockReset().mockResolvedValue({})
  mocks.getRunGraph.mockReset().mockResolvedValue({ graph: sampleRunGraph() })
  mocks.getFactDetail.mockReset().mockResolvedValue({})
  mocks.listEvents.mockReset().mockResolvedValue({ events: [] })
  mocks.listSessions.mockReset().mockResolvedValue({ sessions: [] })
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

  it('shows OFFLINE when ListProjects fails', async () => {
    mocks.listProjects.mockRejectedValue(new Error('server down'))
    renderAt('/')
    expect(await screen.findByText('OFFLINE')).toBeInTheDocument()
    expect(screen.getByText(/无法连接 server/)).toBeInTheDocument()
  })
})
