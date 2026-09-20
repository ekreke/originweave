import { create, type JsonObject } from '@bufbuild/protobuf'

import {
  BudgetSchema,
  EdgeSchema,
  EventSchema,
  EvidenceSchema,
  FactSchema,
  HintSchema,
  IntentCountsSchema,
  IntentSchema,
  LlmSettingsSchema,
  ProjectSchema,
  RunDetailSchema,
  RunSchema,
  SessionSchema,
  SessionStepSchema,
  SettingsSchema,
  StepsSchema,
  Vec2Schema,
  WorkerBudgetSchema,
  WorkerSettingsSchema,
  type Edge,
  type Event,
  type Evidence,
  type Fact,
  type Hint,
  type Intent,
  type Project,
  type Run,
  type RunDetail,
  type Session,
  type SessionStep,
  type Settings,
  type WorkerBudget,
  type WorkerSettings,
} from '@/gen/originweave/v1/originweave_pb'

// Deterministic proto fixtures for the presentation layer. They stand in for the
// server's RunDetail payload in tests only; the app itself never uses mock data.

export function vec2(x = 0, y = 0) {
  return create(Vec2Schema, { x, y })
}

export function counts(open = 0, done = 0) {
  return create(IntentCountsSchema, { open, done })
}

export function steps(current = 0, total = 0) {
  return create(StepsSchema, { current, total })
}

export function budget(tokens = 0n, cost = 0, elapsed = '0s') {
  return create(BudgetSchema, { tokens, cost, elapsed })
}

export function evidence(overrides: Partial<Evidence> = {}): Evidence {
  return create(EvidenceSchema, {
    id: 'ev1',
    quote: 'verbatim quote from the source',
    sourceTitle: 'GitHub Labs',
    url: 'https://example.com/source',
    locator: 'p.1',
    ...overrides,
  })
}

export function fact(overrides: Partial<Fact> = {}): Fact {
  return create(FactSchema, {
    id: 'f0',
    label: 'a fact',
    subtitle: '',
    kind: 'fact',
    role: 'none',
    status: 'open',
    confidence: 0,
    note: '',
    position: vec2(),
    evidence: [],
    ...overrides,
  })
}

export function intent(overrides: Partial<Intent> = {}): Intent {
  return create(IntentSchema, {
    id: 'i0',
    type: 'explore',
    status: 'open',
    from: 'origin',
    question: '',
    producedFacts: [],
    createdAt: '2026-09-19T00:00:00Z',
    ...overrides,
  })
}

export function hint(overrides: Partial<Hint> = {}): Hint {
  return create(HintSchema, {
    id: 'h0',
    text: 'a hint',
    author: 'human',
    createdAt: '2026-09-19T00:00:00Z',
    ...overrides,
  })
}

export function edge(overrides: Partial<Edge> = {}): Edge {
  return create(EdgeSchema, {
    id: 'e0',
    source: 'a',
    target: 'b',
    relation: 'main-chain',
    note: '',
    ...overrides,
  })
}

export function event(overrides: Partial<Event> = {}): Event {
  return create(EventSchema, {
    id: '1',
    at: '2026-09-19T00:00:00Z',
    type: 'PROJECT',
    message: '',
    tone: 'info',
    payload: {},
    ...overrides,
  })
}

export function run(overrides: Partial<Run> = {}): Run {
  return create(RunSchema, {
    id: 'run_001',
    projectId: 'copilot-productivity',
    title: 'a run',
    sourceType: 'text',
    analysis: 'provenance',
    status: 'running',
    goal: '',
    facts: 0,
    deviations: 0,
    entities: 0,
    relations: 0,
    intents: counts(),
    confidence: 0,
    steps: steps(),
    budget: budget(),
    createdAt: '',
    updatedAt: '',
    ...overrides,
  })
}

export function project(overrides: Partial<Project> = {}): Project {
  return create(ProjectSchema, {
    id: 'p1',
    name: 'A project',
    description: '',
    runCount: 0,
    updatedAt: '',
    accent: '',
    ...overrides,
  })
}

export function workerBudget(overrides: Partial<WorkerBudget> = {}): WorkerBudget {
  return create(WorkerBudgetSchema, { maxSteps: 60, maxWall: '10m', maxCost: 2, ...overrides })
}

export function workerSettings(overrides: Partial<WorkerSettings> = {}): WorkerSettings {
  return create(WorkerSettingsSchema, {
    llm: create(LlmSettingsSchema, {
      provider: 'openai',
      model: 'deepseek-v4.1-flash',
      baseUrl: '',
    }),
    provider: 'pi',
    maxConcurrency: 1,
    tools: [],
    heartbeatInterval: '15s',
    heartbeatTimeout: '5m',
    heartbeatOnTimeout: 'release',
    budget: workerBudget(),
    ...overrides,
  })
}

export function settings(overrides: Partial<Settings> = {}): Settings {
  return create(SettingsSchema, { worker: workerSettings(), ...overrides })
}

export function sessionStep(overrides: Partial<SessionStep> = {}): SessionStep {
  return create(SessionStepSchema, { seq: 1, kind: 'turn-start', name: '', text: '', ...overrides })
}

export function session(overrides: Partial<Session> = {}): Session {
  return create(SessionSchema, {
    id: 'sess_001',
    runId: 'run_009',
    worker: 'worker-1',
    task: 'Explore',
    model: 'test-model',
    input: { task: 'Explore' } satisfies JsonObject,
    output: '{"facts": []}',
    steps: [
      sessionStep({ seq: 1, kind: 'turn-start' }),
      sessionStep({ seq: 2, kind: 'tool-call', name: 'search', text: 'q', ok: true }),
    ],
    startedAt: '2026-09-19T00:00:00Z',
    endedAt: '2026-09-19T00:00:01Z',
    ...overrides,
  })
}

// A representative provenance DAG: origin/goal anchors, a main claim with
// evidence, a citation and source, a deviation, plus intents covering all status
// variants and edges covering every relation type.
export function sampleRunDetail(): RunDetail {
  const origin = fact({
    id: 'origin',
    kind: 'origin',
    label: '资料 A',
    status: 'verified',
    position: vec2(0, 0),
  })
  const goal = fact({
    id: 'goal',
    kind: 'goal',
    label: '核验目标',
    status: 'verified',
    position: vec2(0, -160),
  })
  const f1 = fact({
    id: 'f1',
    kind: 'fact',
    role: 'main-claim',
    label: 'Copilot 提升 55% 生产率',
    status: 'verified',
    confidence: 0.9,
    position: vec2(0, 160),
    evidence: [evidence({ id: 'ev1' })],
  })
  const c1 = fact({
    id: 'c1',
    kind: 'citation',
    label: '引用来源',
    status: 'open',
    position: vec2(0, 320),
  })
  const s1 = fact({
    id: 's1',
    kind: 'source',
    label: 'GitHub 实验室',
    status: 'verified',
    position: vec2(0, 480),
  })
  const d1 = fact({
    id: 'd1',
    kind: 'deviation',
    label: '以偏概全',
    status: 'flagged',
    confidence: 0.6,
    position: vec2(320, 160),
  })

  const i1 = intent({
    id: 'i1',
    type: 'decompose',
    status: 'done',
    from: 'f1',
    question: '拆解核心论点',
    producedFacts: ['f1'],
    claimedBy: 'worker-1',
  })
  const i2 = intent({
    id: 'i2',
    type: 'explore',
    status: 'open',
    from: 'f1',
    question: '55% 来自哪里？',
  })
  const i3 = intent({
    id: 'i3',
    type: 'verify',
    status: 'dropped',
    from: 'f1',
    question: '重复问题',
    duplicateOf: 'i2',
  })
  const i4 = intent({
    id: 'i4',
    type: 'explore',
    status: 'awaiting_human',
    from: 'c1',
    question: '等待人工裁决',
  })

  return create(RunDetailSchema, {
    run: run({
      id: 'run_009',
      title: 'Copilot 生产力核验',
      status: 'awaiting_human',
      goal: '判定 55% 是否忠实于一手研究',
      facts: 4,
      deviations: 1,
      intents: counts(2, 1),
      steps: steps(3, 8),
    }),
    origin,
    goal,
    facts: [f1, c1, s1, d1],
    intents: [i1, i2, i3, i4],
    edges: [
      edge({ id: 'e1', source: 'origin', target: 'f1', relation: 'main-chain' }),
      edge({ id: 'e2', source: 'goal', target: 'f1', relation: 'goal-derived' }),
      edge({ id: 'e3', source: 'f1', target: 'c1', relation: 'dependency' }),
      edge({ id: 'e4', source: 'f1', target: 'd1', relation: 'decomposes' }),
      edge({ id: 'e5', source: 'f1', target: 'i2', relation: 'spawns' }),
      edge({ id: 'e6', source: 'i2', target: 'c1', relation: 'resolves' }),
    ],
    events: [
      event({ id: '1', type: 'PROJECT', message: 'run created', tone: 'info' }),
      event({ id: '2', type: 'REASON', message: 'reasoned about the claim', tone: 'success' }),
      event({
        id: '3',
        type: 'REQUEST_HUMAN',
        message: 'Gate A: confirm the claim',
        tone: 'warning',
      }),
      event({ id: '4', type: 'FAILED', message: 'worker crashed', tone: 'danger' }),
    ],
    waitingFor: { gate: 'confirm-claim', question: '确认核心论点？' },
    sourceText: 'Document A text.',
    hints: [hint({ id: 'h1', text: '优先核对原始 benchmark' })],
    sessions: [
      session({ id: 'sess_003', intentId: 'i2', task: 'Explore', worker: 'worker-1' }),
      session({
        id: 'sess_001',
        task: 'Bootstrap',
        worker: 'worker-2',
        input: { task: 'Bootstrap' },
        output: 'boot ok',
        steps: [sessionStep({ seq: 1, kind: 'turn-start' })],
      }),
    ],
  })
}

export function sampleProjects(): Project[] {
  return [
    project({ id: 'copilot-productivity', name: 'Copilot 生产力', runCount: 3 }),
    project({ id: 'sample', name: 'Sample', runCount: 1 }),
  ]
}

export function sampleRuns(): Run[] {
  return [
    run({
      id: 'run_009',
      title: 'Copilot 生产力核验',
      status: 'awaiting_human',
      facts: 4,
      deviations: 1,
      confidence: 0.72,
      steps: steps(3, 8),
    }),
    run({
      id: 'run_008',
      title: '已完成核验',
      status: 'completed',
      facts: 6,
      deviations: 2,
      confidence: 0.88,
      steps: steps(8, 8),
    }),
    run({
      id: 'run_007',
      title: '暂停中的核验',
      status: 'paused',
      facts: 2,
      confidence: 0.5,
      steps: steps(2, 6),
    }),
  ]
}
