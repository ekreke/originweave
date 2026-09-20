import { create } from '@bufbuild/protobuf'
import { Code, ConnectError } from '@connectrpc/connect'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RunDetailSchema } from '@/gen/originweave/v1/originweave_pb'
import { App } from '@/App'
import { sampleProjects, sampleRunDetail, sampleRuns } from '@/test/fixtures'
import { AppProviders } from '@/test/providers'

const mocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listProjectRuns: vi.fn(),
  getRun: vi.fn(),
  addHint: vi.fn(),
  submitHumanInput: vi.fn(),
  createRun: vi.fn(),
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
  mocks.addHint.mockReset().mockResolvedValue({ hint: undefined })
  mocks.submitHumanInput.mockReset().mockResolvedValue({ run: { id: 'run_009' } })
  mocks.createRun.mockReset().mockResolvedValue({ run: { id: 'run_009' } })
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

  it('drives the Inspector from a graph node selection', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    fireEvent.click(await screen.findByTestId('fact-node-f1'))

    const inspector = within(screen.getByLabelText('inspector'))
    expect(inspector.getByText('verbatim quote from the source')).toBeInTheDocument()
  })

  it('drives the Inspector from a FACTS row selection', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('Copilot 提升 55% 生产率')

    fireEvent.click(screen.getByRole('tab', { name: 'FACTS' }))
    fireEvent.click(screen.getByText('Copilot 提升 55% 生产率'))

    const inspector = within(screen.getByLabelText('inspector'))
    expect(inspector.getByText('verbatim quote from the source')).toBeInTheDocument()
    // The selected row is highlighted.
    const row = within(screen.getByRole('table')).getByText('Copilot 提升 55% 生产率').closest('tr')
    expect(row).toHaveClass('selected-row')
  })

  it('drives the Inspector from an INTENTS row selection', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('Copilot 提升 55% 生产率')

    fireEvent.click(screen.getByRole('tab', { name: 'INTENTS' }))
    fireEvent.click(screen.getByText('拆解核心论点'))

    const inspector = within(screen.getByLabelText('inspector'))
    expect(inspector.getByText('claimed by')).toBeInTheDocument()
    expect(inspector.getByText('worker-1')).toBeInTheDocument()
  })

  it('submits a hint through AddHint', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('Copilot 提升 55% 生产率')

    fireEvent.change(screen.getByLabelText('hint input'), { target: { value: 'check it' } })
    fireEvent.click(screen.getByRole('button', { name: '提交' }))

    await waitFor(() =>
      expect(mocks.addHint).toHaveBeenCalledWith({ runId: 'run_009', text: 'check it' }),
    )
  })
})

describe('hitl gate', () => {
  it('submits a decision with the pending gate', async () => {
    renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('确认核心论点？')

    fireEvent.click(screen.getByRole('button', { name: 'approve' }))

    await waitFor(() =>
      expect(mocks.submitHumanInput).toHaveBeenCalledWith({
        runId: 'run_009',
        gate: 'confirm-claim',
        decision: 'approve',
        text: '',
        targets: [],
      }),
    )
  })

  it('shows an inline error when the decision is rejected', async () => {
    mocks.submitHumanInput.mockRejectedValue(new Error('gate not supported'))
    renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('确认核心论点？')

    fireEvent.click(screen.getByRole('button', { name: 'reject' }))

    expect(await screen.findByText('gate not supported')).toBeInTheDocument()
  })
})

describe('replay stepper', () => {
  it('walks from live to the last step and back to live', async () => {
    const { container } = renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('Copilot 提升 55% 生产率')

    const forward = screen.getByRole('button', { name: 'replay forward' })
    const label = () => container.querySelector('.replay-step')?.textContent

    expect(label()).toBe('live')
    fireEvent.click(forward)
    // Stepping asks the server to fold the board to the first event.
    await waitFor(() => expect(mocks.getRun).toHaveBeenCalledWith({ runId: 'run_009', atEvent: 1 }))
    await waitFor(() => expect(label()).toBe('1/4'))
    fireEvent.click(forward)
    fireEvent.click(forward)
    fireEvent.click(forward)
    await waitFor(() => expect(label()).toBe('4/4'))
    fireEvent.click(forward)
    expect(label()).toBe('live')
  })

  it('renders the folded board returned by GetRun(at_event)', async () => {
    const full = sampleRunDetail()
    // Step 1 = only PROJECT: the anchors exist, the derived nodes do not.
    const folded = create(RunDetailSchema, {
      run: full.run,
      origin: full.origin,
      goal: full.goal,
      facts: [],
      intents: [],
      edges: [],
      events: full.events,
    })
    mocks.getRun.mockImplementation(async (request: { atEvent?: number }) =>
      request.atEvent === 1 ? { runDetail: folded } : { runDetail: full },
    )

    renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('Copilot 提升 55% 生产率')

    fireEvent.click(screen.getByRole('button', { name: 'replay forward' }))

    await waitFor(() => expect(screen.queryByTestId('fact-node-f1')).not.toBeInTheDocument())
    expect(screen.getByTestId('fact-node-origin')).toBeInTheDocument()
  })

  it('disables the gate and hint write while replaying', async () => {
    const { container } = renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('确认核心论点？')
    expect(screen.getByRole('button', { name: 'approve' })).toBeEnabled()

    fireEvent.click(container.querySelector('button[aria-label="replay back"]')!)

    expect(await screen.findByLabelText('hint input')).toBeDisabled()
    expect(await screen.findByRole('button', { name: 'approve' })).toBeDisabled()
  })
})

describe('run header badges', () => {
  it('shows the run status and budget summary', async () => {
    const { container } = renderAt('/projects/copilot-productivity/runs/run_009')
    await screen.findByText('确认核心论点？')

    const budget = container.querySelector('.run-meta .budget')?.textContent ?? ''
    expect(budget).toContain('steps 3/8')
    expect(budget).toContain('intents 2/1')
    expect(budget).toContain('tok 0')
    expect(budget).toContain('cost 0.00')
    expect(container.querySelector('.run-meta .status-badge')?.textContent).toBe('awaiting_human')
  })
})

describe('new run', () => {
  it('submits CreateRun and navigates to the console', async () => {
    renderAt('/projects/copilot-productivity/runs/new')

    fireEvent.change(screen.getByLabelText('source text'), { target: { value: 'doc A' } })
    fireEvent.change(screen.getByLabelText('goal'), { target: { value: 'judge the claim' } })
    fireEvent.click(screen.getByRole('button', { name: '创建并进入审阅台' }))

    await waitFor(() =>
      expect(mocks.createRun).toHaveBeenCalledWith(
        expect.objectContaining({
          projectId: 'copilot-productivity',
          sourceType: 'text',
          sourceText: 'doc A',
          goal: 'judge the claim',
          analysis: 'provenance',
        }),
      ),
    )
    // Navigation lands on the console, which loads the (new) run.
    expect(await screen.findByText('确认核心论点？')).toBeInTheDocument()
  })

  it('keeps submit disabled until source text and goal are provided', () => {
    renderAt('/projects/copilot-productivity/runs/new')

    expect(screen.getByRole('button', { name: '创建并进入审阅台' })).toBeDisabled()
    expect(mocks.createRun).not.toHaveBeenCalled()
  })

  it('shows an inline error when CreateRun fails', async () => {
    mocks.createRun.mockRejectedValue(new Error('project not found'))
    renderAt('/projects/copilot-productivity/runs/new')

    fireEvent.change(screen.getByLabelText('source text'), { target: { value: 'doc A' } })
    fireEvent.change(screen.getByLabelText('goal'), { target: { value: 'g' } })
    fireEvent.click(screen.getByRole('button', { name: '创建并进入审阅台' }))

    expect(await screen.findByText('project not found')).toBeInTheDocument()
  })
})
