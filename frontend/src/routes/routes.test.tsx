import { Code, ConnectError } from '@connectrpc/connect'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '@/App'
import { sampleProjects, sampleRunDetail, sampleRuns } from '@/test/fixtures'
import { AppProviders } from '@/test/providers'

const mocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listProjectRuns: vi.fn(),
  getRun: vi.fn(),
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
  mocks.listProjects.mockReset().mockResolvedValue({ projects: sampleProjects() })
  mocks.listProjectRuns.mockReset().mockResolvedValue({ runs: sampleRuns() })
  mocks.getRun.mockReset().mockResolvedValue({ runDetail: sampleRunDetail() })
})

describe('overview', () => {
  it('lists the projects returned by ListProjects', async () => {
    renderAt('/')
    const card = await screen.findByTestId('project-card-copilot-productivity')
    expect(card).toHaveTextContent('Copilot 生产力')
  })
})

describe('project', () => {
  it('lists the runs returned by ListProjectRuns', async () => {
    renderAt('/projects/copilot-productivity')
    expect(await screen.findByTestId('run-card-run_009')).toBeInTheDocument()
    expect(screen.getByTestId('run-card-run_009')).toHaveClass('run-card-alert')
  })
})

describe('console', () => {
  it('renders the RunDetail tabs from GetRun', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')

    expect(await screen.findByText('Copilot 提升 55% 生产率')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'INTENTS' }))
    expect(screen.getByText('55% 来自哪里？')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'EVENTS' }))
    expect(screen.getByText('Gate A: confirm the claim')).toBeInTheDocument()
  })

  it('shows the awaiting_human status and the gate question', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    expect(await screen.findByText('确认核心论点？')).toBeInTheDocument()
    expect(screen.getAllByText('awaiting_human').length).toBeGreaterThan(0)
  })

  it('passes the route params to the RPCs', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('Copilot 提升 55% 生产率')
    expect(mocks.listProjectRuns).toHaveBeenCalledWith({ projectId: 'copilot-productivity' })
    expect(mocks.getRun).toHaveBeenCalledWith({ runId: 'run_009' })
  })

  it('distinguishes a missing run from a connection error', async () => {
    mocks.getRun.mockRejectedValue(new ConnectError('no such run', Code.NotFound))
    renderAt('/projects/copilot-productivity/runs/run_404')
    expect(await screen.findByText(/找不到该 run/)).toBeInTheDocument()
  })

  it('shows an error panel when GetRun fails for another reason', async () => {
    mocks.getRun.mockRejectedValue(new Error('boom'))
    renderAt('/projects/copilot-productivity/runs/run_009')
    expect(await screen.findByText(/无法加载 run/)).toBeInTheDocument()
  })
})
