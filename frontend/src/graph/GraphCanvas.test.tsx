import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { GraphCanvas } from '@/graph/GraphCanvas'
import { runDetailToGraph } from '@/graph/mapping'
import { sampleRunDetail } from '@/test/fixtures'

describe('GraphCanvas', () => {
  it('renders an empty canvas without data', () => {
    render(<GraphCanvas />)
    const canvas = screen.getByTestId('graph-canvas')
    expect(canvas.querySelector('.react-flow')).not.toBeNull()
  })

  it('renders fact and intent nodes mapped from a RunDetail', () => {
    const { nodes, edges } = runDetailToGraph(sampleRunDetail())
    render(<GraphCanvas nodes={nodes} edges={edges} />)
    expect(screen.getByTestId('fact-node-f1')).toBeInTheDocument()
    expect(screen.getByTestId('intent-node-i2')).toBeInTheDocument()
    expect(screen.getByTestId('intent-node-i3')).toHaveClass('intent-dropped')
  })

  it('reports node selection', () => {
    const onSelect = vi.fn()
    const { nodes, edges } = runDetailToGraph(sampleRunDetail())
    render(<GraphCanvas nodes={nodes} edges={edges} onSelect={onSelect} />)
    fireEvent.click(screen.getByTestId('fact-node-f1'))
    expect(onSelect).toHaveBeenCalledWith('f1')
  })
})
