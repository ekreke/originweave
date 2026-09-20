import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Inspector } from '@/layout/Inspector'
import { RunList } from '@/layout/RunList'
import { hint, sampleRunDetail, sampleRuns } from '@/test/fixtures'

const detail = sampleRunDetail()

describe('Inspector', () => {
  it('keeps the empty state without a selection', () => {
    render(<Inspector />)
    expect(screen.getByText(/无选中项/)).toBeInTheDocument()
  })

  it('shows a fact with its verbatim evidence', () => {
    render(
      <Inspector selection={{ type: 'fact', fact: detail.facts[0]! }} intents={detail.intents} />,
    )
    expect(screen.getByText('f1')).toBeInTheDocument()
    expect(screen.getByText('verbatim quote from the source')).toBeInTheDocument()
    expect(screen.getByText('GitHub Labs')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Intents' })).toBeInTheDocument()
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
    expect(onDecision).toHaveBeenCalledWith('reject')
  })

  it('submits a hint through the Hints input and clears it', async () => {
    const onAddHint = vi.fn()
    render(<Inspector onAddHint={onAddHint} />)

    const input = screen.getByLabelText('hint input')
    fireEvent.change(input, { target: { value: 'check the source' } })
    fireEvent.click(screen.getByRole('button', { name: '提交' }))

    expect(onAddHint).toHaveBeenCalledWith('check the source')
    await waitFor(() => expect(input).toHaveValue(''))
  })

  it('renders the hints and disables the input without a handler', () => {
    render(<Inspector hints={[hint({ id: 'h1', text: '优先核对原始 benchmark' })]} />)
    expect(screen.getByText('优先核对原始 benchmark')).toBeInTheDocument()
    expect(screen.getByLabelText('hint input')).toBeDisabled()
  })

  it('ignores Enter while an IME composition is in progress', () => {
    const onAddHint = vi.fn()
    render(<Inspector onAddHint={onAddHint} />)

    const input = screen.getByLabelText('hint input')
    fireEvent.change(input, { target: { value: '拼音' } })
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })

    expect(onAddHint).not.toHaveBeenCalled()
  })

  it('keeps the hint text when the write fails', async () => {
    const onAddHint = vi.fn().mockRejectedValue(new Error('boom'))
    render(<Inspector onAddHint={onAddHint} />)

    const input = screen.getByLabelText('hint input')
    fireEvent.change(input, { target: { value: 'keep me' } })
    fireEvent.click(screen.getByRole('button', { name: '提交' }))

    await waitFor(() => expect(onAddHint).toHaveBeenCalledWith('keep me'))
    await waitFor(() => expect(input).toHaveValue('keep me'))
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
})
