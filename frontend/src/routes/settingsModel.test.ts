import { describe, expect, it } from 'vitest'

import { EMPTY_DRAFT, draftToMessage, toDraft, validateDraft } from '@/routes/settingsModel'
import { settings } from '@/test/fixtures'

const VALID = { ...EMPTY_DRAFT, llmModel: 'deepseek-v4.1-flash' }

describe('toDraft', () => {
  it('maps the proto settings onto string fields', () => {
    const draft = toDraft(settings())
    expect(draft).toMatchObject({
      provider: 'pi',
      execution: 'container',
      image: 'originweave-runtime:latest',
      containerScope: 'per-run',
      maxConcurrency: '1',
      llmModel: 'deepseek-v4.1-flash',
      heartbeatInterval: '15s',
      heartbeatTimeout: '5m',
      heartbeatOnTimeout: 'release',
      maxSteps: '60',
      maxWall: '10m',
      maxCost: '2',
    })
  })
})

describe('draftToMessage', () => {
  it('builds the whole authoritative worker block', () => {
    const message = draftToMessage({
      ...VALID,
      tools: ['search', 'read'],
      maxConcurrency: '4',
      heartbeatInterval: '10s',
      heartbeatTimeout: '1m',
      heartbeatOnTimeout: 'fail',
      maxSteps: '7',
      maxWall: '3m',
      maxCost: '1.5',
    })
    const worker = message.worker
    expect(worker?.provider).toBe('pi')
    expect(worker?.execution).toBe('container')
    expect(worker?.image).toBe('originweave-runtime:latest')
    expect(worker?.containerScope).toBe('per-run')
    expect(worker?.maxConcurrency).toBe(4)
    expect(worker?.tools).toEqual(['search', 'read'])
    expect(worker?.heartbeatInterval).toBe('10s')
    expect(worker?.heartbeatTimeout).toBe('1m')
    expect(worker?.heartbeatOnTimeout).toBe('fail')
    expect(worker?.budget?.maxSteps).toBe(7)
    expect(worker?.budget?.maxWall).toBe('3m')
    expect(worker?.budget?.maxCost).toBe(1.5)
    expect(worker?.llm?.model).toBe('deepseek-v4.1-flash')
  })
})

describe('validateDraft', () => {
  it('accepts a valid draft', () => {
    expect(validateDraft(VALID)).toBe('')
  })

  it('requires a model', () => {
    expect(validateDraft({ ...VALID, llmModel: '  ' })).toBe('model 不能为空')
  })

  it('only permits per-run scope for Pi containers', () => {
    expect(validateDraft({ ...VALID, provider: 'local' })).toContain('仅适用于 Pi')
    expect(validateDraft({ ...VALID, execution: 'in-process' })).toContain('仅适用于 Pi')
  })

  it('requires a runtime image only for container execution', () => {
    expect(validateDraft({ ...VALID, image: '' })).toContain('runtime image')
    expect(
      validateDraft({ ...VALID, execution: 'in-process', containerScope: 'per-call', image: '' }),
    ).toBe('')
  })

  it('requires duration strings', () => {
    expect(validateDraft({ ...VALID, maxWall: 'soon' })).toContain('max_wall')
    expect(validateDraft({ ...VALID, heartbeatInterval: '0s' })).toContain('heartbeat interval')
  })

  it('requires interval < timeout', () => {
    expect(validateDraft({ ...VALID, heartbeatInterval: '5m', heartbeatTimeout: '1m' })).toBe(
      'heartbeat interval 必须 < heartbeat timeout',
    )
  })

  it('bounds concurrency, steps and cost', () => {
    expect(validateDraft({ ...VALID, maxConcurrency: '0' })).toContain('max_concurrency')
    expect(validateDraft({ ...VALID, maxConcurrency: '17' })).toContain('max_concurrency')
    expect(validateDraft({ ...VALID, maxSteps: '0' })).toContain('max_steps')
    expect(validateDraft({ ...VALID, maxCost: '-1' })).toContain('max_cost')
  })
})
