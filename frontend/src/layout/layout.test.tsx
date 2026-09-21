import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { Inspector } from '@/layout/Inspector'
import { RunList } from '@/layout/RunList'
import { hint, run, sampleRunDetail, sampleRunGraph, sampleRuns } from '@/test/fixtures'

const detail = sampleRunDetail()
const graph = sampleRunGraph()

describe('Inspector', () => {
  it('keeps the empty state without a selection', () => {
    render(<Inspector />)
    expect(screen.getByText(/无选中项/)).toBeInTheDocument()
  })

  it('shows a fact summary, its stat tiles and the on-demand evidence', () => {
    render(
      <Inspector
        run={detail.run}
        selection={{ type: 'fact', fact: graph.facts[0]! }}
        factDetail={detail.facts[0]!}
        intents={detail.intents}
      />,
    )
    expect(screen.getByText('f1')).toBeInTheDocument()
    // The verbatim evidence arrives through the on-demand GetFactDetail RPC.
    expect(screen.getByText('verbatim quote from the source')).toBeInTheDocument()
    expect(screen.getByText('GitHub Labs')).toBeInTheDocument()
    // Run-level stat tiles replace the old intent counts section.
    expect(screen.getByText('FACTS')).toBeInTheDocument()
    expect(screen.getByText('INTENTS')).toBeInTheDocument()
    expect(screen.getByText('OPEN')).toBeInTheDocument()
    expect(screen.getByText('HINTS')).toBeInTheDocument()
  })

  it('shows the loading state while the fact detail is in flight', () => {
    render(<Inspector selection={{ type: 'fact', fact: graph.facts[0]! }} factLoading />)
    expect(screen.getByText('加载详情…')).toBeInTheDocument()
    expect(screen.queryByText('verbatim quote from the source')).not.toBeInTheDocument()
  })

  it('shows the fact detail error inline', () => {
    render(<Inspector selection={{ type: 'fact', fact: graph.facts[0]! }} factError="boom" />)
    expect(screen.getByText('boom')).toBeInTheDocument()
  })

  it('shows the awaiting intent detail', () => {
    render(<Inspector selection={{ type: 'intent', intent: detail.intents[3]! }} />)
    expect(screen.getByText('等待人工裁决')).toBeInTheDocument()
    expect(screen.getByText('awaiting_human')).toBeInTheDocument()
  })

  it('renders the gate card and only fires decisions when wired', () => {
    const onDecision = vi.fn()
    const { rerender } = render(<Inspector waitingFor={detail.waitingFor} />)
    expect(screen.getByText('确认核心论点？')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'approve' })).toBeDisabled()

    rerender(<Inspector waitingFor={detail.waitingFor} onDecision={onDecision} />)
    fireEvent.click(screen.getByRole('button', { name: 'reject' }))
    expect(onDecision).toHaveBeenCalledWith('reject', '')
  })

  it('passes the gate note with the decision', () => {
    const onDecision = vi.fn()
    render(<Inspector waitingFor={detail.waitingFor} onDecision={onDecision} />)

    fireEvent.change(screen.getByLabelText('gate note'), {
      target: { value: 'use the 2022 study' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'edit' }))

    expect(onDecision).toHaveBeenCalledWith('edit', 'use the 2022 study')
  })

  it('disables the gate buttons while pending and shows the error', () => {
    const onDecision = vi.fn()
    const { rerender } = render(
      <Inspector waitingFor={detail.waitingFor} onDecision={onDecision} decisionPending />,
    )
    expect(screen.getByRole('button', { name: 'approve' })).toBeDisabled()

    rerender(
      <Inspector waitingFor={detail.waitingFor} onDecision={onDecision} decisionError="boom" />,
    )
    expect(screen.getByText('boom')).toBeInTheDocument()
  })

  it('submits a hint through the Hints input and clears it', async () => {
    const onAddHint = vi.fn().mockResolvedValue(undefined)
    render(<Inspector onAddHint={onAddHint} />)

    const input = screen.getByLabelText('hint input')
    fireEvent.change(input, { target: { value: 'check the source' } })
    fireEvent.click(screen.getByRole('button', { name: '提交' }))

    expect(onAddHint).toHaveBeenCalledWith('check the source')
    await waitFor(() => expect(input).toHaveValue(''))
  })

  it('keeps the hint text when the write fails', async () => {
    const onAddHint = vi.fn().mockRejectedValue(new Error('read-only view'))
    render(<Inspector onAddHint={onAddHint} />)

    const input = screen.getByLabelText('hint input')
    fireEvent.change(input, { target: { value: 'retry me' } })
    fireEvent.click(screen.getByRole('button', { name: '提交' }))

    expect(await screen.findByText('read-only view')).toBeInTheDocument()
    expect(input).toHaveValue('retry me')
  })

  it('renders the hints and disables the input without a handler', () => {
    render(<Inspector hints={[hint({ id: 'h1', text: '优先核对原始 benchmark' })]} />)
    expect(screen.getByText('优先核对原始 benchmark')).toBeInTheDocument()
    expect(screen.getByLabelText('hint input')).toBeDisabled()
  })

  it('shows the session of the selected intent with raw input, output and steps', () => {
    render(
      <Inspector
        selection={{ type: 'intent', intent: detail.intents[1]! }}
        sessions={detail.sessions}
      />,
    )
    expect(screen.getByRole('heading', { name: '会话' })).toBeInTheDocument()
    expect(screen.getByText('sess_003')).toBeInTheDocument()
    expect(screen.getAllByText('原始输出').length).toBeGreaterThan(0)
    expect(screen.getByText('{"facts": []}')).toBeInTheDocument()
    // The step chain renders with its tool name.
    expect(screen.getByText('tool-call')).toBeInTheDocument()
    expect(screen.getByText('search')).toBeInTheDocument()
  })

  it('lists the task sessions that have no intent', () => {
    render(<Inspector sessions={detail.sessions} />)
    expect(screen.getByRole('heading', { name: '任务会话' })).toBeInTheDocument()
    expect(screen.getByText('sess_001')).toBeInTheDocument()
  })

  it('omits the session section without sessions', () => {
    render(<Inspector selection={{ type: 'intent', intent: detail.intents[1]! }} />)
    expect(screen.queryByRole('heading', { name: '会话' })).not.toBeInTheDocument()
  })

  it('reveals a failed run reason behind a toggle', () => {
    render(
      <Inspector
        run={run({ status: 'failed', statusReason: 'worker container returned 500: boom' })}
      />,
    )
    // The reason stays hidden until asked for; the badge alone is not a diagnosis.
    expect(screen.queryByText('worker container returned 500: boom')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '失败原因' }))
    expect(screen.getByText('worker container returned 500: boom')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(screen.queryByText('worker container returned 500: boom')).not.toBeInTheDocument()
  })

  it('labels a stopped run reason as 终止原因', () => {
    render(<Inspector run={run({ status: 'stopped', statusReason: 'budget max_steps=60' })} />)
    expect(screen.getByRole('button', { name: '终止原因' })).toBeInTheDocument()
  })

  it('collapses the reason again when switching to another run', () => {
    const first = run({ id: 'run_a', status: 'failed', statusReason: 'boom' })
    const { rerender } = render(<Inspector run={first} />)
    fireEvent.click(screen.getByRole('button', { name: '失败原因' }))
    expect(screen.getByText('boom')).toBeInTheDocument()

    rerender(<Inspector run={run({ id: 'run_b', status: 'failed', statusReason: 'other' })} />)

    expect(screen.queryByText('other')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '失败原因' })).toBeInTheDocument()
  })

  it('hides the reason toggle without a terminal reason', () => {
    render(<Inspector run={run({ status: 'running' })} />)
    expect(screen.queryByRole('button', { name: '失败原因' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '终止原因' })).not.toBeInTheDocument()
  })
})

describe('RunList', () => {
  it('keeps the empty state without runs', () => {
    render(<RunList />)
    expect(screen.getByText(/尚无 run/)).toBeInTheDocument()
  })

  it('renders run cards and highlights awaiting_human', () => {
    render(<RunList runs={sampleRuns()} />)
    expect(screen.getByTestId('run-card-run_009')).toHaveClass('run-card-alert')
    expect(screen.getByTestId('run-card-run_008')).not.toHaveClass('run-card-alert')
    expect(screen.getByText('completed')).toBeInTheDocument()
  })

  it('highlights only the active run card', () => {
    render(<RunList runs={sampleRuns()} activeRunId="run_008" />)
    expect(screen.getByTestId('run-card-run_008')).toHaveClass('run-card-active')
    expect(screen.getByTestId('run-card-run_009')).not.toHaveClass('run-card-active')
  })

  it('links each card title to the run console when given a project', () => {
    render(
      <MemoryRouter>
        <RunList runs={sampleRuns()} projectId="p" />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: '已完成核验' })).toHaveAttribute(
      'href',
      '/projects/p/runs/run_008',
    )
  })

  it('renders a plain title without a project', () => {
    render(<RunList runs={sampleRuns()} />)
    expect(screen.queryByRole('link', { name: '已完成核验' })).not.toBeInTheDocument()
  })

  it('offers a retry link for a failed run when given a project', () => {
    render(
      <MemoryRouter>
        <RunList runs={[run({ id: 'run_bad', status: 'failed' })]} projectId="p" />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: '重试' })).toHaveAttribute(
      'href',
      '/projects/p/runs/new?from=run_bad',
    )
  })

  it('does not offer retry for active runs or without a project', () => {
    const { rerender } = render(
      <MemoryRouter>
        <RunList runs={[run({ id: 'run_ok', status: 'completed' })]} projectId="p" />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('link', { name: '重试' })).not.toBeInTheDocument()

    rerender(
      <MemoryRouter>
        <RunList runs={[run({ id: 'run_bad', status: 'stopped' })]} />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('link', { name: '重试' })).not.toBeInTheDocument()
  })

  it('offers retry for a stopped run too', () => {
    render(
      <MemoryRouter>
        <RunList runs={[run({ id: 'run_stop', status: 'stopped' })]} projectId="p" />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: '重试' })).toHaveAttribute(
      'href',
      '/projects/p/runs/new?from=run_stop',
    )
  })
})
