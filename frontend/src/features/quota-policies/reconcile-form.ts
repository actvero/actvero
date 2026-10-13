import { z } from 'zod'

export const quantityFields = [
  'input_tokens',
  'output_tokens',
  'cache_read_tokens',
  'cache_write_5m_tokens',
  'cache_write_1h_tokens',
  'input_characters',
  'search_units',
  'image_count',
  'audio_duration_ms',
] as const

export type QuantityField = (typeof quantityFields)[number]
export type Metric =
  | 'tokens'
  | 'characters'
  | 'search_units'
  | 'images'
  | 'seconds'

export const metricFields: Record<Metric, QuantityField[]> = {
  tokens: quantityFields.slice(0, 5),
  characters: ['input_characters'],
  search_units: ['search_units'],
  images: ['image_count'],
  seconds: ['audio_duration_ms'],
}

export const fieldNames: Record<QuantityField, string> = {
  input_tokens: '输入 Token',
  output_tokens: '输出 Token',
  cache_read_tokens: '缓存读取 Token',
  cache_write_5m_tokens: '缓存写入 5 分钟 Token',
  cache_write_1h_tokens: '缓存写入 1 小时 Token',
  input_characters: '计费字符数',
  search_units: '上游搜索单位',
  image_count: '确认交付张数',
  audio_duration_ms: '确认音频时长（毫秒）',
}

const baseSchema = z.object({
  action: z.enum(['settle', 'release']),
  reason: z.string().trim().min(1, '填写核对依据').max(500, '最多 500 字'),
  release_confirmed: z.boolean(),
  input_tokens: z.string(),
  output_tokens: z.string(),
  cache_read_tokens: z.string(),
  cache_write_5m_tokens: z.string(),
  cache_write_1h_tokens: z.string(),
  input_characters: z.string(),
  search_units: z.string(),
  image_count: z.string(),
  audio_duration_ms: z.string(),
})

export type ReconcileValues = z.infer<typeof baseSchema>

export const emptyReconcileValues: ReconcileValues = {
  action: 'settle',
  reason: '',
  release_confirmed: false,
  input_tokens: '',
  output_tokens: '',
  cache_read_tokens: '',
  cache_write_5m_tokens: '',
  cache_write_1h_tokens: '',
  input_characters: '',
  search_units: '',
  image_count: '',
  audio_duration_ms: '',
}

export function reconcileSchema(required: string[], metric: Metric) {
  return baseSchema.superRefine((values, context) => {
    if (values.action === 'release') {
      if (!values.release_confirmed)
        context.addIssue({
          code: 'custom',
          path: ['release_confirmed'],
          message: '请确认已核实没有使用量',
        })
      return
    }
    for (const field of metricFields[metric]) {
      const value = values[field]
      if (required.includes(field) && value === '')
        context.addIssue({
          code: 'custom',
          path: [field],
          message: '请填写确认的数量；确认为零时填写 0',
        })
      else if (
        value !== '' &&
        (!/^(0|[1-9]\d*)$/.test(value) ||
          Number(value) >
            (field === 'audio_duration_ms' ? 120000 : 1_000_000_000_000))
      )
        context.addIssue({
          code: 'custom',
          path: [field],
          message: '填写非负整数，不超过 1000000000000',
        })
    }
  })
}

export function reconcileBody(
  values: ReconcileValues,
  metric: Metric,
  version: number
) {
  const body: {
    version: number
    action: 'settle' | 'release'
    reason: string
    usage?: { metric: Metric } & Partial<Record<QuantityField, number>>
  } = { version, action: values.action, reason: values.reason.trim() }
  if (values.action === 'settle') {
    const usage: { metric: Metric } & Partial<Record<QuantityField, number>> = {
      metric,
    }
    for (const field of metricFields[metric]) {
      if (values[field] !== '') usage[field] = Number(values[field])
    }
    body.usage = usage
  }
  return body
}
