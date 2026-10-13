import { readCallSearch, type CallSearch } from './search'

export const metricLabels = {
  calls: '调用数',
  points: '已结算积分',
  input_tokens: '输入 Token',
  output_tokens: '输出 Token',
  cache_read_tokens: '缓存读取 Token',
  cache_write_5m_tokens: '5分钟缓存写入 Token',
  cache_write_1h_tokens: '1小时缓存写入 Token',
  input_characters: '字符',
  search_units: '搜索单位',
  image_count: '图片张数',
  audio_duration_ms: '音频毫秒',
} as const
export type Metric = keyof typeof metricLabels
export type Display = {
  tab: 'models' | 'flow' | 'members'
  granularity: 'auto' | 'hour' | 'day'
  metric: Metric
  chart: 'bar' | 'area' | 'table'
  top: number
  rank: 'calls' | 'points' | 'input_tokens' | 'output_tokens'
  selected_members: string
}
export type DashboardSearch = CallSearch & Partial<Display>
export const defaults: Display = {
  tab: 'models',
  granularity: 'auto',
  metric: 'calls',
  chart: 'bar',
  top: 10,
  rank: 'calls',
  selected_members: '',
}
export function readDashboardSearch(
  raw: Record<string, unknown>
): DashboardSearch {
  const result: DashboardSearch = readCallSearch(raw)
  for (const key of [
    'tab',
    'granularity',
    'metric',
    'chart',
    'rank',
  ] as const) {
    const choices = {
      tab: ['models', 'flow', 'members'],
      granularity: ['auto', 'hour', 'day'],
      metric: Object.keys(metricLabels),
      chart: ['bar', 'area', 'table'],
      rank: ['calls', 'points', 'input_tokens', 'output_tokens'],
    }[key]
    if (typeof raw[key] === 'string' && choices.includes(raw[key]))
      Object.assign(result, { [key]: raw[key] })
  }
  if ([5, 10, 20, 50].includes(Number(raw.top))) result.top = Number(raw.top)
  if (typeof raw.selected_members === 'string')
    result.selected_members = raw.selected_members
      .split(',')
      .filter((id) => /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(id))
      .slice(0, 5)
      .join(',')
  return result
}
export type Preferences = Pick<
  Display,
  'granularity' | 'metric' | 'chart' | 'top'
> & { days: number }
export const preferenceDefaults: Preferences = { ...defaults, days: 7 }
export function readPreferences(key: string): Preferences {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || '{}') as Record<
      string,
      unknown
    >
    const parsed = readDashboardSearch(raw)
    return {
      granularity: parsed.granularity ?? 'auto',
      metric: parsed.metric ?? 'calls',
      chart: parsed.chart ?? 'bar',
      top: parsed.top ?? 10,
      days: [1, 7, 30].includes(Number(raw.days)) ? Number(raw.days) : 7,
    }
  } catch {
    return preferenceDefaults
  }
}
