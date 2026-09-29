import { describe, expect, it } from 'vitest'

import { activityLabel } from '@/routes/consoleModel'

describe('activityLabel', () => {
  it('maps every server phase to a console label', () => {
    expect(activityLabel('bootstrapping')).toBe('初始化中')
    expect(activityLabel('reasoning')).toBe('推理中')
    expect(activityLabel('validating')).toBe('校验中')
    expect(activityLabel('dispatching')).toBe('派发中')
    expect(activityLabel('executing')).toBe('执行中')
  })

  it('renders nothing for an empty or unknown phase', () => {
    expect(activityLabel('')).toBe('')
    expect(activityLabel(undefined)).toBe('')
    expect(activityLabel('nonsense')).toBe('')
  })
})
