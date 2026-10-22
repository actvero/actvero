import { z } from 'zod'
import type { Schema } from '@/lib/api'
import {
  imageSizes,
  imageQualities,
} from '@/features/model-channels/image-test-schema'
import {
  chatPolicySchema,
  chatPolicyValues,
  chatPolicyInput,
} from './chat-policy-form'

export const kinds = {
  chat: '对话',
  embedding: '向量',
  rerank: '重排',
  image_generation: '图片生成',
  speech: '语音合成',
  transcription: '语音转文字',
} as const
export const metrics = {
  tokens: 'Token',
  characters: '字符',
  search_units: '搜索单位',
  images: '张',
  seconds: '秒',
} as const

export const rates = [
  ['input', '输入'],
  ['output', '输出'],
  ['cache_read', '缓存读取'],
  ['cache_write_5m', '缓存写入（5 分钟）'],
  ['cache_write_1h', '缓存写入（1 小时）'],
] as const
export const capabilities = [
  ['streaming', '流式输出'],
  ['tools', '工具调用'],
  ['structured_output', '结构化输出'],
  ['vision', '图片输入'],
  ['reasoning', '思考模式'],
] as const
export const effortLevels = [
  'none',
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
  'default',
  'omit',
] as const
export const effortLabels: Record<string, string> = {
  none: '关闭（none）',
  minimal: '最低',
  low: '低',
  medium: '中',
  high: '高',
  xhigh: '更高',
  max: '最高',
  default: '上游默认',
  omit: '省略参数',
}
export const currencies = ['USD', 'CNY', 'EUR', 'GBP', 'JPY', 'HKD'] as const
export const pointStates = {
  no_price: '尚未配置模型价格',
  unconfigured: '尚未设置积分换算',
  currency_mismatch: '计价币种不一致，无法换算积分',
}
export type Model = Schema['CatalogView']
export type PriceKey = 'budget_price' | `bindings.${number}.price`

// Decimal-point movement only; prices never pass through binary floating point.
export function shiftDecimal(value: string, places: number): string {
  if (!/^\d+(\.\d+)?$/.test(value)) return value
  const [whole, fraction = ''] = value.split('.')
  const digits = whole + fraction
  const point = whole.length + places
  const result =
    point <= 0
      ? '0.' + '0'.repeat(-point) + digits
      : point >= digits.length
        ? digits + '0'.repeat(point - digits.length)
        : digits.slice(0, point) + '.' + digits.slice(point)
  return result
    .replace(/^0+(?=\d)/, '')
    .replace(/(\.\d*?)0+$/, '$1')
    .replace(/\.$/, '')
}
export const priceSchema = z
  .object({
    enabled: z.boolean(),
    metric: z.enum([
      'tokens',
      'characters',
      'search_units',
      'images',
      'seconds',
    ]),
    currency: z.string(),
    unit: z.enum(['1', '1000', '1000000']),
    input: z.string(),
    output: z.string(),
    cache_read: z.string(),
    cache_write_5m: z.string(),
    cache_write_1h: z.string(),
    note: z.string(),
  })
  .superRefine((value, ctx) => {
    if (!value.enabled) return
    if (value.note.length > 500)
      ctx.addIssue({
        code: 'custom',
        path: ['note'],
        message: '备注最多 500 个字符',
      })
    if (!(currencies as readonly string[]).includes(value.currency))
      ctx.addIssue({
        code: 'custom',
        path: ['currency'],
        message: '请选择币种',
      })
    for (const [key] of rates) {
      const raw = value[key]
      if (!raw && key !== 'input') continue
      const normalized = shiftDecimal(raw, value.unit === '1000' ? 3 : 0)
      if (
        !/^\d{1,10}(\.\d{1,15})?$/.test(raw) ||
        Number(normalized) > 1e9 ||
        (normalized.split('.')[1]?.length ?? 0) > 12
      )
        ctx.addIssue({
          code: 'custom',
          path: [key],
          message: '填写非负单价，规范化后最多 12 位小数、上限 10 亿',
        })
    }
  })
const declaration = z.enum(['unknown', 'supported', 'unsupported'])
const limit = z
  .string()
  .refine(
    (v) => !v || (/^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 100000000),
    '填写 1 至 100000000 的整数'
  )
const integer = (min: number, max: number) =>
  z
    .string()
    .refine(
      (v) => /^\d+$/.test(v) && Number(v) >= min && Number(v) <= max,
      `填写 ${min} 至 ${max} 的整数`
    )
export const modelSchema = z
  .object({
    chat_policy: chatPolicySchema,
    kind: z.enum([
      'chat',
      'embedding',
      'rerank',
      'image_generation',
      'speech',
      'transcription',
    ]),
    transcription: z.object({
      max_duration_seconds: integer(1, 120),
      timestamps: z.boolean(),
    }),
    speech: z.object({
      voice: z
        .string()
        .regex(/^([A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99})?$/, '填写有效音色 ID'),
      response_format: z.literal('wav'),
      max_input_characters: integer(1, 1000),
    }),
    image: z.object({
      size: z.union([z.literal(''), z.enum(imageSizes)]),
      quality: z.union([z.literal(''), z.enum(imageQualities)]),
      max_prompt_characters: integer(1, 2000),
    }),
    operation_enabled: z.boolean(),
    retrieval: z.object({
      max_search_units: limit,
      dimensions: limit,
      dimension_options: z.string().refine(
        (v) =>
          !v ||
          v
            .split(/[,，\s]+/)
            .filter(Boolean)
            .every(
              (d) => /^\d+$/.test(d) && Number(d) >= 1 && Number(d) <= 65536
            ),
        '填写 1 至 65536 的维度，逗号分隔'
      ),
      embedding_space: z.string().trim().max(200),
      max_batch_size: z
        .string()
        .refine(
          (v) => /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 128,
          '填写 1 至 128'
        ),
      max_input_characters: z
        .string()
        .refine(
          (v) => /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 200000,
          '填写 1 至 200000'
        ),
    }),
    routing: z.object({
      mode: z.enum(['fixed', 'auto']),
      fallback: z.boolean(),
      max_attempts: integer(1, 10),
      connect_timeout_seconds: integer(1, 120),
      first_response_timeout_seconds: integer(3, 3600),
      stream_idle_timeout_seconds: integer(3, 3600),
      total_timeout_seconds: integer(3, 86400),
      retry_uncertain: z.boolean(),
      failure_threshold: integer(1, 10),
      cooldown_seconds: integer(5, 3600),
      model_revision: z.string().trim().max(200),
    }),
    access: z.object({
      enabled: z.boolean(),
      audience: z.enum(['administrators', 'organization', 'selected']),
      member_ids: z.array(z.string()),
      channel_id: z.string(),
      upstream_id: z.string(),
    }),
    name: z.string().trim().min(1, '请填写模型名称').max(100),
    display_order: integer(0, 1000000),
    quote_snapshots: z.array(z.custom<Schema['QuoteSnapshot']>()).max(10),
    slug: z
      .string()
      .trim()
      .regex(
        /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$/,
        '使用字母、数字及 . _ : / @ + -，最多 200 字符'
      ),
    vendor: z.string().trim().max(100),
    description: z.string().trim().max(2000),
    icon: z.string().max(350000),
    icon_key: z.string(),
    reference: z
      .object({
        provider: z.string(),
        model_id: z.string(),
        channel_id: z.string().nullable().optional(),
      })
      .nullable(),
    reasoning: z.object({
      toggle: z.boolean(),
      effort: z.boolean(),
      budget: z.boolean(),
      levels: z.array(z.enum(effortLevels)),
      min: z.string(),
      max: z.string(),
    }),
    context_window: limit,
    max_output: limit,
    capabilities: z.object({
      streaming: declaration,
      tools: declaration,
      structured_output: declaration,
      vision: declaration,
      reasoning: declaration,
    }),
    budget_price: priceSchema,
    bindings: z
      .array(
        z.object({
          binding_id: z.string().uuid().nullish(),
          channel_id: z.string(),
          upstream_id: z.string(),
          price: priceSchema,
          enabled: z.boolean(),
          priority: integer(0, 1000),
          weight: integer(1, 10000),
          compatibility_key: z.string().trim().max(200),
          chat_options: z.object({
            limits: z
              .object({
                context_window: z
                  .number()
                  .int()
                  .positive()
                  .nullable()
                  .optional(),
                max_output: z.number().int().positive().nullable().optional(),
                reasoning_efforts: z
                  .array(
                    z.enum([
                      'none',
                      'minimal',
                      'low',
                      'medium',
                      'high',
                      'xhigh',
                      'max',
                      'default',
                    ])
                  )
                  .nullable()
                  .optional(),
                parameters: z
                  .array(
                    z.enum([
                      'temperature',
                      'top_p',
                      'reasoning_effort',
                      'thinking',
                    ])
                  )
                  .nullable()
                  .optional(),
              })
              .optional(),

            reasoning_format: z.enum([
              'openai',
              'thinking',
              'thinking_budget',
              'enable_thinking',
            ]),
            output_parameter: z.enum(['max_tokens', 'max_completion_tokens']),
          }),
        })
      )
      .max(50),
  })
  .superRefine((value, ctx) => {
    if (
      value.kind === 'transcription' &&
      value.access.enabled &&
      value.operation_enabled &&
      !value.budget_price.enabled
    )
      ctx.addIssue({
        code: 'custom',
        path: ['budget_price', 'enabled'],
        message: '请配置每秒价格',
      })
    if (
      value.kind === 'speech' &&
      value.access.enabled &&
      value.operation_enabled
    ) {
      if (!value.speech.voice)
        ctx.addIssue({
          code: 'custom',
          path: ['speech', 'voice'],
          message: '请配置音色',
        })
      if (!value.budget_price.enabled)
        ctx.addIssue({
          code: 'custom',
          path: ['budget_price', 'enabled'],
          message: '请配置输入字符价格',
        })
    }
    if (
      value.kind === 'image_generation' &&
      value.access.enabled &&
      value.operation_enabled &&
      !value.budget_price.enabled
    )
      ctx.addIssue({
        code: 'custom',
        path: ['budget_price', 'enabled'],
        message: '开放图片生成前请配置每张积分计价',
      })
    if (value.kind === 'chat') {
      for (const [field, bound] of [
        ['default_context_window', 'context_window'],
        ['default_max_output', 'max_output'],
      ] as const) {
        if (
          value.chat_policy[field] &&
          (!value[bound] ||
            Number(value.chat_policy[field]) > Number(value[bound]))
        )
          ctx.addIssue({
            code: 'custom',
            path: ['chat_policy', field],
            message: '默认值不能超过模型上限',
          })
      }
      const effort = value.chat_policy.default_reasoning_effort
      if (
        effort !== 'omit' &&
        (value.capabilities.reasoning !== 'supported' ||
          !value.reasoning.effort ||
          !value.reasoning.levels.includes(effort))
      )
        ctx.addIssue({
          code: 'custom',
          path: ['chat_policy', 'default_reasoning_effort'],
          message: '默认强度不在允许选项中',
        })
      if (
        value.chat_policy.default_context_window &&
        Number(value.chat_policy.default_max_output || value.max_output) >=
          Number(value.chat_policy.default_context_window)
      )
        ctx.addIssue({
          code: 'custom',
          path: ['chat_policy', 'default_context_window'],
          message: '上下文须为输入和输出保留空间',
        })
      for (const [i, price] of [
        value.budget_price,
        ...value.bindings.map((b) => b.price),
      ].entries())
        if (price.enabled && !price.output)
          ctx.addIssue({
            code: 'custom',
            path:
              i === 0
                ? ['budget_price', 'output']
                : ['bindings', i - 1, 'price', 'output'],
            message: '填写输出单价',
          })
    }
    if (value.access.audience === 'selected' && !value.access.member_ids.length)
      ctx.addIssue({
        code: 'custom',
        path: ['access', 'member_ids'],
        message: '至少选择一名成员',
      })
    if (
      value.access.enabled &&
      value.operation_enabled &&
      value.routing.mode === 'fixed' &&
      !value.access.channel_id
    )
      ctx.addIssue({
        code: 'custom',
        path: ['access', 'channel_id'],
        message: '请选择调用渠道',
      })
    if (
      value.kind === 'chat' &&
      value.access.enabled &&
      value.operation_enabled
    ) {
      for (const key of ['context_window', 'max_output'] as const)
        if (!value[key])
          ctx.addIssue({
            code: 'custom',
            path: [key],
            message: '启用前请填写此项',
          })
    }
    if (
      value.kind === 'embedding' &&
      value.access.enabled &&
      value.operation_enabled
    ) {
      for (const key of ['dimensions', 'embedding_space'] as const)
        if (!value.retrieval[key])
          ctx.addIssue({
            code: 'custom',
            path: ['retrieval', key],
            message: '启用前请填写此项',
          })
    }
    if (
      value.kind === 'embedding' &&
      value.retrieval.dimensions &&
      Number(value.retrieval.dimensions) > 65536
    )
      ctx.addIssue({
        code: 'custom',
        path: ['retrieval', 'dimensions'],
        message: '维度不能超过 65536',
      })
    const dimensions = value.retrieval.dimension_options
      .split(/[,，\s]+/)
      .filter(Boolean)
      .map(Number)
    if (
      dimensions.length &&
      (!dimensions.includes(Number(value.retrieval.dimensions)) ||
        new Set(dimensions).size !== dimensions.length)
    )
      ctx.addIssue({
        code: 'custom',
        path: ['retrieval', 'dimension_options'],
        message: '可选维度须包含默认维度且不能重复',
      })
    if (value.kind === 'chat' && value.capabilities.reasoning === 'supported') {
      if (value.reasoning.effort && !value.reasoning.levels.length)
        ctx.addIssue({
          code: 'custom',
          path: ['reasoning', 'levels'],
          message: '至少选择一种强度',
        })
      if (value.reasoning.budget) {
        for (const key of ['min', 'max'] as const) {
          const raw = value.reasoning[key]
          if (
            raw &&
            (!/^-?\d+$/.test(raw) ||
              Number(raw) < (key === 'min' ? -1 : 0) ||
              Number(raw) > 100000000)
          )
            ctx.addIssue({
              code: 'custom',
              path: ['reasoning', key],
              message:
                key === 'min'
                  ? '填写 -1 至 100000000 的整数'
                  : '填写 0 至 100000000 的整数',
            })
        }
        if (
          value.reasoning.min &&
          value.reasoning.max &&
          Number(value.reasoning.min) > Number(value.reasoning.max)
        )
          ctx.addIssue({
            code: 'custom',
            path: ['reasoning', 'max'],
            message: '上限不能小于下限',
          })
      }
    }
    if (
      value.context_window &&
      value.max_output &&
      Number(value.max_output) > Number(value.context_window)
    )
      ctx.addIssue({
        code: 'custom',
        path: ['max_output'],
        message: '最大输出不能大于上下文上限',
      })
  })
export type ModelValues = z.infer<typeof modelSchema>
export type PriceValues = ModelValues['budget_price']
export function priceValues(
  price?: Schema['TokenPrice-Output'] | null
): PriceValues {
  return {
    enabled: !!price,
    metric: price?.metric ?? 'tokens',
    currency: price?.currency ?? '',
    unit: price?.unit === 1 ? '1' : '1000000',
    input: price?.input ?? '',
    output: price?.output ?? '',
    cache_read: price?.cache_read ?? '',
    cache_write_5m: price?.cache_write_5m ?? '',
    cache_write_1h: price?.cache_write_1h ?? '',
    note: price?.note ?? '',
  }
}
export function priceInput(
  value: PriceValues
): Schema['TokenPrice-Input'] | null {
  if (!value.enabled) return null
  return {
    currency: value.currency as Schema['TokenPrice-Input']['currency'],
    metric: value.metric,
    unit: Number(value.unit) as 1 | 1000 | 1000000,
    input: value.input,
    output: value.output || null,
    cache_read: value.cache_read || null,
    cache_write_5m: value.cache_write_5m || null,
    cache_write_1h: value.cache_write_1h || null,
    note: value.note,
  }
}
export function reasoningValues(
  options: Schema['CatalogInput']['reasoning_options'] = []
): ModelValues['reasoning'] {
  const effort = options.find((o) => o.type === 'effort')
  const budget = options.find((o) => o.type === 'budget_tokens')
  return {
    toggle: options.some((o) => o.type === 'toggle'),
    effort: !!effort,
    budget: !!budget,
    levels: effort?.values.map((v) => v ?? 'omit') ?? [],
    min: budget?.min?.toString() ?? '',
    max: budget?.max?.toString() ?? '',
  }
}
export function values(model?: Model): ModelValues {
  return {
    kind: model?.kind ?? 'chat',
    chat_policy: chatPolicyValues(model?.chat_policy),
    transcription: {
      max_duration_seconds: String(
        model?.transcription?.max_duration_seconds ?? 120
      ),
      timestamps: model?.transcription?.timestamps ?? false,
    },
    speech: {
      voice: model?.speech?.voice ?? '',
      response_format: 'wav',
      max_input_characters: String(model?.speech?.max_input_characters ?? 1000),
    },
    image: {
      size: model?.image?.size ?? '',
      quality: model?.image?.quality ?? '',
      max_prompt_characters: String(
        model?.image?.max_prompt_characters ?? 2000
      ),
    },
    operation_enabled: !!model,
    retrieval: {
      max_search_units: model?.retrieval?.max_search_units?.toString() ?? '',
      dimensions: model?.retrieval?.dimensions?.toString() ?? '',
      dimension_options: model?.retrieval?.dimension_options?.join(', ') ?? '',
      embedding_space: model?.retrieval?.embedding_space ?? '',
      max_batch_size: (model?.retrieval?.max_batch_size ?? 32).toString(),
      max_input_characters: (
        model?.retrieval?.max_input_characters ?? 20000
      ).toString(),
    },
    routing: {
      mode: model?.routing?.mode ?? 'fixed',
      fallback: model?.routing?.fallback ?? false,
      max_attempts: String(model?.routing?.max_attempts ?? 3),
      connect_timeout_seconds: String(
        model?.routing?.connect_timeout_seconds ?? 10
      ),
      first_response_timeout_seconds: String(
        model?.routing?.first_response_timeout_seconds ?? 180
      ),
      stream_idle_timeout_seconds: String(
        model?.routing?.stream_idle_timeout_seconds ?? 180
      ),
      total_timeout_seconds: String(
        model?.routing?.total_timeout_seconds ?? 1800
      ),
      retry_uncertain: model?.routing?.retry_uncertain ?? false,
      failure_threshold: String(model?.routing?.failure_threshold ?? 3),
      cooldown_seconds: String(model?.routing?.cooldown_seconds ?? 30),
      model_revision: model?.routing?.model_revision ?? '',
    },
    access: {
      enabled: model?.access?.enabled ?? false,
      audience: model?.access?.audience ?? 'administrators',
      member_ids: model?.access?.member_ids ?? [],
      channel_id: model?.access?.channel_id ?? '',
      upstream_id: model?.access?.upstream_id ?? '',
    },
    name: model?.name ?? '',
    display_order: String(
      (model as (Model & { display_order?: number }) | undefined)
        ?.display_order ?? 0
    ),
    quote_snapshots:
      (
        model as
          | (Model & { quote_snapshots?: Schema['QuoteSnapshot'][] })
          | undefined
      )?.quote_snapshots ?? [],
    slug: model?.slug ?? '',
    vendor: model?.vendor ?? '',
    description: model?.description ?? '',
    icon: model?.icon ?? '',
    icon_key: model?.icon_key ?? '',
    reference: model?.reference ?? null,
    reasoning: reasoningValues(model?.reasoning_options),
    context_window: model?.context_window?.toString() ?? '',
    max_output: model?.max_output?.toString() ?? '',
    capabilities: {
      streaming: model?.capabilities?.streaming ?? 'unknown',
      tools: model?.capabilities?.tools ?? 'unknown',
      structured_output: model?.capabilities?.structured_output ?? 'unknown',
      vision: model?.capabilities?.vision ?? 'unknown',
      reasoning: model?.capabilities?.reasoning ?? 'unknown',
    },
    budget_price: priceValues(model?.budget_price),
    bindings: (model?.bindings ?? []).map((b) => ({
      ...b,
      enabled: b.enabled ?? true,
      priority: String(b.priority ?? 0),
      weight: String(b.weight ?? 100),
      compatibility_key: b.compatibility_key ?? '',
      price: priceValues(b.price),
      chat_options: {
        limits: b.chat_options?.limits,
        reasoning_format: b.chat_options?.reasoning_format ?? 'openai',
        output_parameter:
          b.chat_options?.output_parameter ?? 'max_completion_tokens',
      },
    })),
  }
}
export function modelInput(value: ModelValues): Schema['CatalogInput'] {
  const { reasoning, operation_enabled: _operationEnabled, ...fields } = value
  const options: NonNullable<Schema['CatalogInput']['reasoning_options']> = []
  if (value.kind === 'chat' && value.capabilities.reasoning === 'supported') {
    if (reasoning.toggle) options.push({ type: 'toggle' })
    if (reasoning.effort)
      options.push({
        type: 'effort',
        values: reasoning.levels.map((v) => (v === 'omit' ? null : v)),
      })
    if (reasoning.budget)
      options.push({
        type: 'budget_tokens',
        min: reasoning.min ? Number(reasoning.min) : null,
        max: reasoning.max ? Number(reasoning.max) : null,
      })
  }
  return {
    ...fields,
    display_order: Number(value.display_order),
    chat_policy: chatPolicyInput(value.chat_policy),
    transcription: {
      ...value.transcription,
      max_duration_seconds: Number(value.transcription.max_duration_seconds),
    },
    speech: {
      ...value.speech,
      max_input_characters: Number(value.speech.max_input_characters),
    },
    image: {
      size: value.image.size || null,
      quality: value.image.quality || null,
      max_prompt_characters: Number(value.image.max_prompt_characters),
    },
    retrieval: {
      ...value.retrieval,
      max_search_units: value.retrieval.max_search_units
        ? Number(value.retrieval.max_search_units)
        : null,
      dimensions: value.retrieval.dimensions
        ? Number(value.retrieval.dimensions)
        : null,
      dimension_options: value.retrieval.dimension_options
        .split(/[,，\s]+/)
        .filter(Boolean)
        .map(Number),
      max_batch_size: Number(value.retrieval.max_batch_size),
      max_input_characters: Number(value.retrieval.max_input_characters),
    },
    access: {
      ...value.access,
      enabled: value.access.enabled,
      channel_id: value.access.channel_id || null,
    },
    routing: {
      ...value.routing,
      mode: value.routing.mode,
      model_revision:
        value.routing.mode === 'auto' &&
        value.kind !== 'embedding' &&
        !value.routing.model_revision
          ? value.slug
          : value.routing.model_revision,
      max_attempts: Number(value.routing.max_attempts),
      connect_timeout_seconds: Number(value.routing.connect_timeout_seconds),
      first_response_timeout_seconds: Number(
        value.routing.first_response_timeout_seconds
      ),
      stream_idle_timeout_seconds: Number(
        value.routing.stream_idle_timeout_seconds
      ),
      total_timeout_seconds: Number(value.routing.total_timeout_seconds),
      failure_threshold: Number(value.routing.failure_threshold),
      cooldown_seconds: Number(value.routing.cooldown_seconds),
    },
    reasoning_options: options,
    context_window: value.context_window ? Number(value.context_window) : null,
    max_output: value.max_output ? Number(value.max_output) : null,
    budget_price: priceInput(forKind(value.budget_price, value.kind)),
    bindings: value.bindings.map((b) => ({
      ...b,
      priority: Number(b.priority),
      weight: Number(b.weight),
      price: priceInput(forKind(b.price, value.kind)),
    })),
  }
}

export function forKind(
  price: PriceValues,
  kind: ModelValues['kind']
): PriceValues {
  if (kind === 'speech')
    return {
      ...price,
      metric: 'characters',
      unit: price.unit === '1' ? '1000000' : price.unit,
      output: '',
      cache_read: '',
      cache_write_5m: '',
      cache_write_1h: '',
    }
  if (kind === 'image_generation' || kind === 'transcription')
    return {
      ...price,
      metric: kind === 'transcription' ? 'seconds' : 'images',
      unit: '1',
      output: '',
      cache_read: '',
      cache_write_5m: '',
      cache_write_1h: '',
    }
  return kind === 'chat'
    ? { ...price, metric: 'tokens' }
    : {
        ...price,
        output: '',
        cache_read: '',
        cache_write_5m: '',
        cache_write_1h: '',
      }
}

export const routeStates: Record<string, string> = {
  ready: '可调度',
  disabled: '已停用',
  unavailable: '渠道不可用',
  incompatible: '待确认兼容',
  unverified: '待测试',
  credential_error: '渠道凭据阻断',
  model_error: '上游模型不可用',
  binding_error: '绑定拒绝待判',
  cooldown: '冷却中',
  probing: '恢复测试中',
}

export type OperationKind = ModelValues['kind']
export function operationModel(model: Model, kind: OperationKind): Model {
  const operation = model.operations?.find((o) => o.kind === kind)
  if (!operation) return model
  return {
    ...model,
    ...operation,
    access: {
      enabled: model.access?.enabled ?? false,
      audience: model.access?.audience ?? 'administrators',
      ...model.access,
      channel_id: operation.channel_id,
      upstream_id: operation.upstream_id,
    },
    point_price: model.operation_point_prices?.[kind],
    binding_states: model.binding_states.filter((b) => b.operation === kind),
  }
}
export function operationDrafts(model?: Model): ModelValues[] {
  if (!model?.operations) return [values(model)]
  return model.operations.map((o) => ({
    ...values(operationModel(model, o.kind ?? 'chat')),
    operation_enabled: o.enabled ?? false,
  }))
}
export function shareModelFields(
  target: ModelValues,
  source: ModelValues
): ModelValues {
  return {
    ...target,
    name: source.name,
    slug: source.slug,
    display_order: source.display_order,
    quote_snapshots: source.quote_snapshots,
    vendor: source.vendor,
    description: source.description,
    icon: source.icon,
    icon_key: source.icon_key,
    reference: source.reference,
    access: {
      ...target.access,
      enabled: source.access.enabled,
      audience: source.access.audience,
      member_ids: source.access.member_ids,
    },
  }
}
export function operationsInput(
  drafts: ModelValues[]
): Schema['ModelOperation-Input'][] {
  return drafts.map((draft) => {
    const input = modelInput(draft)
    return {
      kind: input.kind,
      chat_policy: input.chat_policy,
      enabled: draft.operation_enabled,
      channel_id: input.access?.channel_id,
      upstream_id: input.access?.upstream_id ?? '',
      retrieval: input.retrieval,
      image: input.image,
      speech: input.speech,
      transcription: input.transcription,
      routing: input.routing,
      context_window: input.context_window,
      max_output: input.max_output,
      capabilities: input.capabilities,
      reasoning_options: input.reasoning_options,
      bindings: input.bindings,
      budget_price: input.budget_price,
    }
  })
}
