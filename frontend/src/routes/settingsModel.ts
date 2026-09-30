import { create } from '@bufbuild/protobuf'

import {
  LlmSettingsSchema,
  PromptSettingsSchema,
  SettingsSchema,
  WorkerBudgetSchema,
  WorkerSettingsSchema,
  type Settings,
} from '@/gen/originweave/v1/originweave_pb'

// The server treats UpdateSettings' worker block as authoritative (every scalar is
// required), so the form round-trips the whole Settings message it loaded via
// GetSettings. Editing happens on a string draft (input-friendly) and is parsed back
// into proto on submit. Keeping this model out of the component keeps the render pure.

export const PROVIDERS = ['local', 'pi'] as const
export const EXECUTIONS = ['container', 'in-process'] as const
export const CONTAINER_SCOPES = ['per-run', 'per-call'] as const
export const HEARTBEAT_ON_TIMEOUT = ['release', 'fail'] as const
export const TOOLS = ['search', 'read', 'grep', 'find', 'ls', 'bash', 'edit', 'write'] as const
// Output-language suggestions for the input helper (goal/title); "" follows the document.
export const LANGUAGES = ['', 'zh-CN', 'zh-TW', 'en', 'ja'] as const
const LANGUAGE_RE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/
const DURATION_RE = /^[1-9][0-9]*(ms|s|m|h|d)$/
const DURATION_UNITS: Record<string, number> = { ms: 0.001, s: 1, m: 60, h: 3600, d: 86400 }

function durationSeconds(text: string): number | null {
  const match = DURATION_RE.exec(text.trim())
  if (!match) return null
  // The only capture group is the unit; the leading integer is the full match.
  const unit = match[1]!
  const amount = Number.parseInt(match[0], 10)
  return amount * (DURATION_UNITS[unit] ?? Number.NaN)
}

export interface Draft {
  provider: string
  execution: string
  image: string
  containerScope: string
  maxConcurrency: string
  llmProvider: string
  llmModel: string
  llmBaseUrl: string
  tools: string[]
  heartbeatInterval: string
  heartbeatTimeout: string
  heartbeatOnTimeout: string
  maxSteps: string
  maxWall: string
  maxCost: string
  language: string
}

export const EMPTY_DRAFT: Draft = {
  provider: 'pi',
  execution: 'container',
  image: 'originweave-runtime:latest',
  containerScope: 'per-run',
  maxConcurrency: '1',
  llmProvider: 'openai',
  llmModel: '',
  llmBaseUrl: '',
  tools: [],
  heartbeatInterval: '15s',
  heartbeatTimeout: '5m',
  heartbeatOnTimeout: 'release',
  maxSteps: '60',
  maxWall: '10m',
  maxCost: '2',
  language: '',
}

export function toDraft(settings: Settings): Draft {
  const worker = settings.worker
  const llm = worker?.llm
  const budget = worker?.budget
  return {
    provider: worker?.provider || EMPTY_DRAFT.provider,
    execution: worker?.execution || EMPTY_DRAFT.execution,
    image: worker?.image || EMPTY_DRAFT.image,
    containerScope: worker?.containerScope || EMPTY_DRAFT.containerScope,
    maxConcurrency: String(worker?.maxConcurrency ?? 1),
    llmProvider: llm?.provider || 'openai',
    llmModel: llm?.model ?? '',
    llmBaseUrl: llm?.baseUrl ?? '',
    tools: [...(worker?.tools ?? [])],
    heartbeatInterval: worker?.heartbeatInterval || EMPTY_DRAFT.heartbeatInterval,
    heartbeatTimeout: worker?.heartbeatTimeout || EMPTY_DRAFT.heartbeatTimeout,
    heartbeatOnTimeout: worker?.heartbeatOnTimeout || EMPTY_DRAFT.heartbeatOnTimeout,
    maxSteps: String(budget?.maxSteps ?? 60),
    maxWall: budget?.maxWall || EMPTY_DRAFT.maxWall,
    maxCost: String(budget?.maxCost ?? 2),
    language: settings.prompt?.language ?? '',
  }
}

// Client-side mirror of the server's Config.validate, so obvious mistakes surface without
// a round-trip; the server remains the authority.
export function validateDraft(draft: Draft): string {
  if (!draft.llmModel.trim()) return 'model 不能为空'
  if (draft.execution === 'container' && !draft.image.trim()) return 'runtime image 不能为空'
  if (
    draft.containerScope === 'per-run' &&
    (draft.provider !== 'pi' || draft.execution !== 'container')
  ) {
    return '每次 run 复用容器仅适用于 Pi 的 container 执行'
  }
  for (const [label, value] of [
    ['heartbeat interval', draft.heartbeatInterval],
    ['heartbeat timeout', draft.heartbeatTimeout],
    ['max_wall', draft.maxWall],
  ] as const) {
    if (!DURATION_RE.test(value.trim())) {
      return `${label} 需为「正整数 + ms|s|m|h|d」`
    }
  }
  const interval = durationSeconds(draft.heartbeatInterval)
  const timeout = durationSeconds(draft.heartbeatTimeout)
  if (interval !== null && timeout !== null && interval >= timeout) {
    return 'heartbeat interval 必须 < heartbeat timeout'
  }
  const concurrency = Number(draft.maxConcurrency)
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 16) {
    return 'max_concurrency 需为 1..16 的整数'
  }
  const steps = Number(draft.maxSteps)
  if (!Number.isInteger(steps) || steps < 1) return 'max_steps 需为 > 0 的整数'
  const cost = Number(draft.maxCost)
  if (!Number.isFinite(cost) || cost < 0) return 'max_cost 需为 >= 0 的数字'
  if (draft.language.trim() && !LANGUAGE_RE.test(draft.language.trim())) {
    return '语言需为 BCP-47 形（如 zh-CN），或留空跟随文档'
  }
  return ''
}

export function draftToMessage(draft: Draft): Settings {
  return create(SettingsSchema, {
    worker: create(WorkerSettingsSchema, {
      llm: create(LlmSettingsSchema, {
        provider: draft.llmProvider.trim(),
        model: draft.llmModel.trim(),
        baseUrl: draft.llmBaseUrl.trim(),
      }),
      provider: draft.provider,
      execution: draft.execution,
      image: draft.image.trim(),
      containerScope: draft.containerScope,
      maxConcurrency: Number(draft.maxConcurrency),
      tools: [...draft.tools],
      heartbeatInterval: draft.heartbeatInterval.trim(),
      heartbeatTimeout: draft.heartbeatTimeout.trim(),
      heartbeatOnTimeout: draft.heartbeatOnTimeout,
      budget: create(WorkerBudgetSchema, {
        maxSteps: Number(draft.maxSteps),
        maxWall: draft.maxWall.trim(),
        maxCost: Number(draft.maxCost),
      }),
    }),
    prompt: create(PromptSettingsSchema, { language: draft.language.trim() }),
  })
}
