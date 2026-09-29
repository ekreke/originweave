// Console presentation helpers, kept pure so they are unit-testable without React.

// Server-derived in-flight phase (Run.activity, dashboard.md §2) -> console label. The
// console polls the light GetRunGraph projection, so this string is what tells the
// operator a run is thinking between graph changes. An unknown phase renders nothing.
const ACTIVITY_LABELS: Record<string, string> = {
  bootstrapping: '初始化中',
  reasoning: '推理中',
  validating: '校验中',
  dispatching: '派发中',
  executing: '执行中',
}

export function activityLabel(activity: string | undefined): string {
  if (!activity) return ''
  return Object.hasOwn(ACTIVITY_LABELS, activity) ? ACTIVITY_LABELS[activity] : ''
}
