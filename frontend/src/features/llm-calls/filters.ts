import { z } from 'zod'

export const sources = {
  member: '正式调用',
  access_key: '个人访问密钥',
  desktop: '桌面令牌',
  diagnostic: '管理员诊断',
  all: '全部来源',
} as const
export const results = {
  success: '成功',
  failed: '失败',
  interrupted: '中断',
  cancelled: '已取消',
  unknown: '未知',
} as const
export const settlements = {
  reserved: '预占中',
  review: '待核对',
  settled: '已结算',
  released: '已释放',
  not_applicable: '不适用',
} as const
export const operations = {
  chat: '对话',
  embedding: '向量',
  rerank: '重排',
  image_generation: '图片生成',
  speech: '语音合成',
  transcription: '语音转文字',
} as const

export type Filters = {
  channel_id?: string
  unknown_channel?: boolean
  fromLocal: string
  toLocal: string
  timezone: string
  member_id: string
  model_id: string
  operation: string
  source: keyof typeof sources
  result_status: string
  settlement_status: string
  call_id: string
  held: boolean
}

const uuid = z.uuid()
const dateLocal = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/
const minute = 60_000
const day = 24 * 60 * minute

export function civilAt(instant: number, zone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(instant)
  const value = (name: string) =>
    parts.find((part) => part.type === name)?.value ?? ''
  return `${value('year')}-${value('month')}-${value('day')}T${value('hour')}:${value('minute')}`
}

/** Rejects nonexistent and ambiguous local minutes instead of silently shifting the billing range. */
export function zonedMinuteToIso(local: string, zone: string) {
  if (!dateLocal.test(local)) return null
  try {
    const [date, time] = local.split('T')
    const [year, month, dayOfMonth] = date.split('-').map(Number)
    const [hour, minuteOfHour] = time.split(':').map(Number)
    const base = Date.UTC(year, month - 1, dayOfMonth, hour, minuteOfHour)
    const dateValue = new Date(base)
    if (
      dateValue.getUTCFullYear() !== year ||
      dateValue.getUTCMonth() !== month - 1 ||
      dateValue.getUTCDate() !== dayOfMonth ||
      dateValue.getUTCHours() !== hour ||
      dateValue.getUTCMinutes() !== minuteOfHour
    )
      return null
    const offsets = new Set<number>()
    for (const sample of [
      base - 2 * day,
      base - day,
      base,
      base + day,
      base + 2 * day,
    ]) {
      const civil = civilAt(sample, zone)
      const [sampleDate, sampleTime] = civil.split('T')
      const [sy, sm, sd] = sampleDate.split('-').map(Number)
      const [sh, smin] = sampleTime.split(':').map(Number)
      offsets.add(Date.UTC(sy, sm - 1, sd, sh, smin) - sample)
    }
    const matches = [...offsets]
      .map((offset) => base - offset)
      .filter((candidate) => civilAt(candidate, zone) === local)
    return matches.length === 1 ? new Date(matches[0]).toISOString() : null
  } catch {
    return null
  }
}

export function defaultFilters(): Filters {
  const to = new Date()
  const from = new Date(to.getTime() - 7 * day)
  return {
    fromLocal: from.toISOString().slice(0, 16),
    toLocal: to.toISOString().slice(0, 16),
    timezone: 'UTC',
    member_id: '',
    model_id: '',
    operation: '',
    source: 'member',
    result_status: '',
    settlement_status: '',
    call_id: '',
    held: false,
  }
}

export function filterSchema(summary = false) {
  return z
    .object({
      channel_id: z.string().optional(),
      unknown_channel: z.boolean().optional(),
      fromLocal: z.string(),
      toLocal: z.string(),
      timezone: z.string().min(1, '选择时区'),
      member_id: z.string(),
      model_id: z.string(),
      operation: z.string(),
      source: z.enum(['member', 'access_key', 'desktop', 'diagnostic', 'all']),
      result_status: z.string(),
      settlement_status: z.string(),
      call_id: z.string(),
      held: z.boolean(),
    })
    .superRefine((value, context) => {
      if (summary && (value.source === 'all' || value.held))
        context.addIssue({
          code: 'custom',
          path: ['source'],
          message: '统计请选择正式调用或管理员诊断',
        })
      if (value.channel_id && !uuid.safeParse(value.channel_id).success)
        context.addIssue({
          code: 'custom',
          path: ['channel_id'],
          message: '渠道编号无效',
        })
      if (value.channel_id && value.unknown_channel)
        context.addIssue({
          code: 'custom',
          path: ['channel_id'],
          message: '不能同时筛选指定与未知渠道',
        })
      if (value.call_id && !uuid.safeParse(value.call_id).success)
        context.addIssue({
          code: 'custom',
          path: ['call_id'],
          message: '填写完整调用 UUID',
        })
      if (summary && (!value.fromLocal || !value.toLocal)) {
        for (const field of ['fromLocal', 'toLocal'] as const)
          if (!value[field])
            context.addIssue({
              code: 'custom',
              path: [field],
              message: '统计必须选择时间范围',
            })
        return
      }
      if (!value.fromLocal && !value.toLocal) return
      if (!value.fromLocal || !value.toLocal) {
        context.addIssue({
          code: 'custom',
          path: [!value.fromLocal ? 'fromLocal' : 'toLocal'],
          message: '开始与结束时间需同时填写',
        })
        return
      }
      const from = zonedMinuteToIso(value.fromLocal, value.timezone)
      const to = zonedMinuteToIso(value.toLocal, value.timezone)
      if (!from)
        context.addIssue({
          code: 'custom',
          path: ['fromLocal'],
          message: '时间在该时区无效或有歧义，请改用明确时间或 UTC',
        })
      if (!to)
        context.addIssue({
          code: 'custom',
          path: ['toLocal'],
          message: '时间在该时区无效或有歧义，请改用明确时间或 UTC',
        })
      if (from && to && Date.parse(from) >= Date.parse(to))
        context.addIssue({
          code: 'custom',
          path: ['toLocal'],
          message: '结束时间必须晚于开始时间',
        })
      if (from && to && Date.parse(to) - Date.parse(from) > 90 * day)
        context.addIssue({
          code: 'custom',
          path: ['toLocal'],
          message: '时间范围最多 90 天',
        })
    })
}

export function queryFor(filters: Filters, page = 1, summary = false) {
  const params = new URLSearchParams()
  if (!filters.held && filters.fromLocal && filters.toLocal) {
    const from = zonedMinuteToIso(filters.fromLocal, filters.timezone)
    const to = zonedMinuteToIso(filters.toLocal, filters.timezone)
    if (!from || !to) throw new Error('时间范围无效')
    params.set('from', from)
    params.set('to', to)
  }
  params.set('timezone', filters.timezone)
  for (const key of ['member_id', 'model_id', 'operation'] as const)
    if (filters[key]) params.set(key, filters[key])
  if (!filters.held) {
    if (filters.result_status)
      params.set('result_status', filters.result_status)
    if (filters.settlement_status)
      params.set('settlement_status', filters.settlement_status)
  }
  params.set('source', filters.source)
  if (!filters.held && filters.channel_id)
    params.set('channel_id', filters.channel_id)
  if (!filters.held && filters.unknown_channel)
    params.set('unknown_channel', 'true')
  if (!summary) {
    if (filters.call_id && !filters.held) params.set('call_id', filters.call_id)
    if (filters.held) params.set('held', 'true')
    params.set('page', String(page))
  }
  return params.toString()
}
