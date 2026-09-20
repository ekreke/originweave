import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { GraphCanvas } from '@/graph/GraphCanvas'
import { classifyEdges, runGraphToFlow } from '@/graph/mapping'
import { factSummary, sampleRunGraph } from '@/test/fixtures'
import { create } from '@bufbuild/protobuf'
import { RunGraphSchema } from '@/gen/originweave/v1/originweave_pb'

describe('GraphCanvas', () => {
  it('renders an empty canvas without data', () => {
    render(<GraphCanvas />)
    const canvas = screen.getByTestId('graph-canvas')
    expect(canvas.querySelector('.react-flow')).not.toBeNull()
  })

  it('renders fact and intent nodes mapped from a RunGraph', () => {
    const { nodes, edges } = runGraphToFlow(sampleRunGraph())
    render(<GraphCanvas nodes={nodes} edges={edges} />)
    expect(screen.getByTestId('fact-node-f1')).toBeInTheDocument()
    expect(screen.getByTestId('intent-node-i2')).toBeInTheDocument()
    expect(screen.getByTestId('intent-node-i3')).toHaveClass('intent-dropped')
  })

  it('shows the node id and kind in the card header', () => {
    const { nodes, edges } = runGraphToFlow(sampleRunGraph())
    render(<GraphCanvas nodes={nodes} edges={edges} />)
    const node = screen.getByTestId('fact-node-f1')
    expect(node.querySelector('.node-id')?.textContent).toBe('f1')
    expect(node.querySelector('.node-kind')?.textContent).toBe('fact')
  })

  it('reports node selection', () => {
    const onSelect = vi.fn()
    const { nodes, edges } = runGraphToFlow(sampleRunGraph())
    render(<GraphCanvas nodes={nodes} edges={edges} onSelect={onSelect} />)
    fireEvent.click(screen.getByTestId('fact-node-f1'))
    expect(onSelect).toHaveBeenCalledWith('f1')
  })

  it('reports keyboard node selection (Enter/Space on the focused card)', () => {
    const onSelect = vi.fn()
    const { nodes, edges } = runGraphToFlow(sampleRunGraph())
    render(<GraphCanvas nodes={nodes} edges={edges} onSelect={onSelect} />)

    fireEvent.keyDown(screen.getByTestId('fact-node-f1'), { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith('f1')

    fireEvent.keyDown(screen.getByTestId('intent-node-i1'), { key: ' ' })
    expect(onSelect).toHaveBeenCalledWith('i1')
  })

  it('marks the selected node and dims unrelated edges', () => {
    const { nodes, edges } = runGraphToFlow(sampleRunGraph())
    render(<GraphCanvas nodes={nodes} edges={edges} selectedId="f1" />)

    expect(screen.getByTestId('fact-node-f1')).toHaveClass('selected')
    const classified = classifyEdges(edges, 'f1')
    expect(classified.filter((edge) => edge.className === 'edge-active').length).toBeGreaterThan(0)
    expect(classified.filter((edge) => edge.className === 'edge-dim').length).toBeGreaterThan(0)
    // The incident set is exactly the edges touching f1.
    const incident = edges.filter((edge) => edge.source === 'f1' || edge.target === 'f1')
    expect(
      classified
        .filter((edge) => edge.className === 'edge-active')
        .every((edge) => incident.some((i) => i.id === edge.id)),
    ).toBe(true)
  })

  it('emphasises the frozen main-chain when nothing is selected', () => {
    const { edges } = runGraphToFlow(sampleRunGraph())
    const classified = classifyEdges(edges, null)
    const main = classified.filter((edge) => edge.data?.relation === 'main-chain')
    expect(main.length).toBeGreaterThan(0)
    expect(main.every((edge) => edge.className === 'edge-main')).toBe(true)
    expect(
      classified
        .filter((edge) => edge.data?.relation !== 'main-chain')
        .every((edge) => edge.className === undefined),
    ).toBe(true)
  })

  it('renders the kind/relation legend', () => {
    const { nodes, edges } = runGraphToFlow(sampleRunGraph())
    render(<GraphCanvas nodes={nodes} edges={edges} />)
    const legend = within(screen.getByLabelText('graph legend'))
    expect(legend.getByText('main-chain')).toBeInTheDocument()
    expect(legend.getByText('citation')).toBeInTheDocument()
    expect(legend.getByText('dependency')).toBeInTheDocument()
  })

  it('shows a truncated preview while keeping the full label in the title', () => {
    const longGoal = '核验目标：核对样本量、适用范围与统计口径。'.repeat(20)
    const detail = create(RunGraphSchema, {
      origin: factSummary({ id: 'origin', kind: 'origin' }),
      goal: factSummary({ id: 'goal', kind: 'goal', label: longGoal }),
    })
    const { nodes, edges } = runGraphToFlow(detail)
    render(<GraphCanvas nodes={nodes} edges={edges} />)

    const node = screen.getByTestId('fact-node-goal')
    expect(node).toHaveAttribute('title', longGoal)
    const label = node.querySelector('.node-label')?.textContent ?? ''
    expect(label.endsWith('…')).toBe(true)
    expect(label).not.toBe(longGoal)
  })
})
