import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Inspector } from '@/layout/Inspector'
import { RunList } from '@/layout/RunList'
import { sampleRunDetail, sampleRuns } from '@/test/fixtures'

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
