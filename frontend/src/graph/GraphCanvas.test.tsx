import { create } from '@bufbuild/protobuf'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RunDetailSchema } from '@/gen/originweave/v1/originweave_pb'
import { GraphCanvas } from '@/graph/GraphCanvas'
import { runDetailToGraph } from '@/graph/mapping'
import { fact, sampleRunDetail } from '@/test/fixtures'

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

  it('shows a truncated preview while keeping the full label in the title', () => {
    const longGoal = '核验目标：核对样本量、适用范围与统计口径。'.repeat(20)
    const detail = create(RunDetailSchema, {
      origin: fact({ id: 'origin', kind: 'origin' }),
      goal: fact({ id: 'goal', kind: 'goal', label: longGoal }),
    })
    const { nodes, edges } = runDetailToGraph(detail)
    render(<GraphCanvas nodes={nodes} edges={edges} />)

    const node = screen.getByTestId('fact-node-goal')
    expect(node).toHaveAttribute('title', longGoal)
    const label = node.querySelector('.node-label')?.textContent ?? ''
    expect(label.endsWith('…')).toBe(true)
    expect(label).not.toBe(longGoal)
  })
})
