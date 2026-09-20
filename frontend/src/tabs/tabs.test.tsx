import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EventsTab } from '@/tabs/EventsTab'
import { FactsTab } from '@/tabs/FactsTab'
import { IntentsTab } from '@/tabs/IntentsTab'
import { event, sampleRunDetail } from '@/test/fixtures'

const detail = sampleRunDetail()

describe('presentation tabs', () => {
  it('keeps the empty states without data', () => {
    render(
      <>
        <FactsTab />
        <IntentsTab />
        <EventsTab />
      </>,
    )
    expect(screen.getByText(/暂无事实节点/)).toBeInTheDocument()
    expect(screen.getByText(/暂无 Intent/)).toBeInTheDocument()
    expect(screen.getByText(/暂无事件/)).toBeInTheDocument()
  })

  it('renders the facts table with evidence counts', () => {
    render(<FactsTab facts={detail.facts} />)
    expect(screen.getByText('f1')).toBeInTheDocument()
    expect(screen.getByText('main-claim')).toBeInTheDocument()
    expect(screen.getByText('0.90')).toBeInTheDocument()
  })

  it('renders intents with status and duplicate markers', () => {
    const { container } = render(<IntentsTab intents={detail.intents} />)
    expect(screen.getByText('i2')).toBeInTheDocument()
    expect(screen.getByText(/dup of i2/)).toBeInTheDocument()
    expect(screen.getAllByText('dropped').length).toBeGreaterThan(0)
    expect(container.querySelector('.row-dropped')).not.toBeNull()
  })

  it('renders events coloured by tone', () => {
    const { container } = render(<EventsTab events={detail.events} />)
    expect(screen.getByText('REQUEST_HUMAN')).toBeInTheDocument()
    expect(container.querySelector('.tone-danger')).not.toBeNull()
  })

  it('truncates and highlights the current event while replaying', () => {
    const { container } = render(<EventsTab events={detail.events} step={1} />)

    const rows = container.querySelectorAll('.event-row')
    expect(rows).toHaveLength(2)
    expect(rows[1]).toHaveClass('event-current')
    expect(screen.getByText(`2/${detail.events.length}`)).toBeInTheDocument()
  })

  it('filters the timeline by worker', () => {
    const events = [
      event({ id: '1', type: 'SESSION', payload: { worker: 'worker-1' }, message: 'w1 session' }),
      event({ id: '2', type: 'SESSION', payload: { worker: 'worker-2' }, message: 'w2 session' }),
    ]
    const { container } = render(<EventsTab events={events} />)
    expect(container.querySelectorAll('.event-row')).toHaveLength(2)

    fireEvent.change(screen.getByLabelText('worker filter'), { target: { value: 'worker-1' } })

    expect(container.querySelectorAll('.event-row')).toHaveLength(1)
    expect(screen.getByText('w1 session')).toBeInTheDocument()
    expect(screen.queryByText('w2 session')).not.toBeInTheDocument()
  })

  it('clamps a worker filter that has no events in view', () => {
    const first = [
      event({ id: '1', type: 'SESSION', payload: { worker: 'worker-1' }, message: 'w1' }),
    ]
    const { rerender, container } = render(<EventsTab events={first} />)
    fireEvent.change(screen.getByLabelText('worker filter'), { target: { value: 'worker-1' } })
    expect(container.querySelectorAll('.event-row')).toHaveLength(1)

    const second = [
      event({ id: '2', type: 'SESSION', payload: { worker: 'worker-2' }, message: 'w2' }),
    ]
    rerender(<EventsTab events={second} />)

    expect(screen.getByLabelText('worker filter')).toHaveValue('all')
    expect(container.querySelectorAll('.event-row')).toHaveLength(1)
    expect(screen.getByText('w2')).toBeInTheDocument()
  })

  it('keeps the replay cursor on the sliced event under a worker filter', () => {
    const events = [
      event({ id: '1', type: 'SESSION', payload: { worker: 'worker-1' } }),
      event({ id: '2', type: 'SESSION', payload: { worker: 'worker-2' } }),
      event({ id: '3', type: 'SESSION', payload: { worker: 'worker-1' } }),
    ]
    const { container } = render(<EventsTab events={events} step={1} />)

    fireEvent.change(screen.getByLabelText('worker filter'), { target: { value: 'worker-1' } })

    // The cursor (event 2) is filtered out; it must not jump onto event 1.
    const rows = container.querySelectorAll('.event-row')
    expect(rows).toHaveLength(1)
    expect(rows[0]).not.toHaveClass('event-current')
  })
})
