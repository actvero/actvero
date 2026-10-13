import { z } from 'zod'
import type { Schema } from '@/lib/api'

const optionalInteger = z
  .string()
  .refine(
    (v) => !v || (/^\d+$/.test(v) && Number(v) > 0 && Number(v) <= 100000000),
    '填写有效的正整数'
  )
const optionalNumber = z
  .string()
  .refine(
    (v) =>
      !v || (Number.isFinite(Number(v)) && Number(v) >= 0 && Number(v) <= 2),
    '填写 0 至 2 的数字'
  )
const sampling = z
  .object({
    enabled: z.boolean(),
    default: optionalNumber,
    min: optionalNumber,
    max: optionalNumber,
    adjustable: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (!v.enabled) return
    if (
      !v.min ||
      !v.max ||
      Number(v.min) > Number(v.max) ||
      (v.default !== '' &&
        (Number(v.default) < Number(v.min) ||
          Number(v.default) > Number(v.max)))
    )
      ctx.addIssue({
        code: 'custom',
        path: ['default'],
        message: '默认值须位于有效范围内',
      })
  })
export const chatPolicySchema = z
  .object({
    default_context_window: optionalInteger,
    default_max_output: optionalInteger,
    context_adjustable: z.boolean(),
    output_adjustable: z.boolean(),
    default_reasoning_effort: z.enum([
      'omit',
      'none',
      'minimal',
      'low',
      'medium',
      'high',
      'xhigh',
      'max',
      'default',
    ]),
    reasoning_adjustable: z.boolean(),
    temperature: sampling,
    top_p: sampling,
  })
  .superRefine((v, ctx) => {
    if (v.top_p.enabled && Number(v.top_p.max) > 1)
      ctx.addIssue({
        code: 'custom',
        path: ['top_p', 'max'],
        message: 'top_p 上限不能超过 1',
      })
  })
export type ChatPolicyValues = z.infer<typeof chatPolicySchema>
export function chatPolicyValues(
  policy?: Schema['ChatPolicy']
): ChatPolicyValues {
  const sample = (
    v: Schema['SamplingRule'] | null | undefined,
    max: number
  ) => ({
    enabled: !!v,
    default: v?.default?.toString() ?? '',
    min: String(v?.min ?? 0),
    max: String(v?.max ?? max),
    adjustable: v?.adjustable ?? true,
  })
  return {
    default_context_window: policy?.default_context_window?.toString() ?? '',
    default_max_output: policy?.default_max_output?.toString() ?? '',
    context_adjustable: policy?.context_adjustable ?? true,
    output_adjustable: policy?.output_adjustable ?? true,
    default_reasoning_effort: policy?.default_reasoning_effort ?? 'omit',
    reasoning_adjustable: policy?.reasoning_adjustable ?? true,
    temperature: sample(policy?.temperature, 2),
    top_p: sample(policy?.top_p, 1),
  }
}
export function chatPolicyInput(v: ChatPolicyValues): Schema['ChatPolicy'] {
  const sample = (s: ChatPolicyValues['temperature']) =>
    s.enabled
      ? {
          default: s.default !== '' ? Number(s.default) : null,
          min: Number(s.min),
          max: Number(s.max),
          adjustable: s.adjustable,
        }
      : null
  return {
    default_context_window: v.default_context_window
      ? Number(v.default_context_window)
      : null,
    default_max_output: v.default_max_output
      ? Number(v.default_max_output)
      : null,
    context_adjustable: v.context_adjustable,
    output_adjustable: v.output_adjustable,
    default_reasoning_effort:
      v.default_reasoning_effort === 'omit' ? null : v.default_reasoning_effort,
    reasoning_adjustable: v.reasoning_adjustable,
    temperature: sample(v.temperature),
    top_p: sample(v.top_p),
  }
}
