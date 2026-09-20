import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EventsTab } from '@/tabs/EventsTab'
import { FactsTab } from '@/tabs/FactsTab'
import { IntentsTab } from '@/tabs/IntentsTab'
import { sampleRunDetail } from '@/test/fixtures'

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
})
