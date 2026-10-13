import type { Schema } from '@/lib/api'
import {
  capabilities,
  priceValues,
  rates,
  type ModelValues,
  type PriceKey,
  type PriceValues,
} from './model-form'
import { importModel, type ReferenceModel } from './reference-models'

export type ImportOptions = {
  metadata: boolean
  basic: boolean
  limits: boolean
  capabilities: boolean
  overwrite: boolean
  price: boolean
  snapshot: boolean
  partialBudget?: boolean
  convertedPrice?: Schema['TokenPrice-Output']
  fxRate?: string
  fxDate?: string
  target: PriceKey
  fetchedAt?: string
}

export function referenceDraft(
  current: ModelValues,
  source: ReferenceModel,
  options: ImportOptions,
  preserveSlug: boolean
) {
  const result = structuredClone(current)
  if (options.metadata) {
    const imported = importModel(current, source, options.overwrite)
    if (options.basic) {
      result.name = imported.name
      result.slug = preserveSlug ? current.slug : imported.slug
      result.vendor = imported.vendor
      result.icon = imported.icon
      result.icon_key = imported.icon_key
    }
    if (options.limits) {
      result.context_window = imported.context_window
      result.max_output = imported.max_output
    }
    if (options.capabilities) {
      result.capabilities = imported.capabilities
      result.reasoning = imported.reasoning
    }
    if (options.basic || options.limits || options.capabilities)
      result.reference = imported.reference
  }
  if (options.snapshot && source.quote_snapshot) {
    const other = result.quote_snapshots.filter(
      (saved) =>
        saved.provider !== source.quote_snapshot?.provider ||
        saved.model_id !== source.quote_snapshot?.model_id
    )
    result.quote_snapshots = [...other, source.quote_snapshot]
  }
  if (
    options.price &&
    current.kind === 'chat' &&
    (source.price_importable ||
      (options.partialBudget && options.target === 'budget_price')) &&
    (!options.convertedPrice || (!!options.fxRate && !!options.fxDate)) &&
    source.price
  ) {
    const old = referencePrice(current, options.target)
    if (old) {
      const lead = `${options.partialBudget ? '内部预算简化价' : '公开参考（非实际结算价）'}：models.dev | `
      const fetchedNote = options.fetchedAt
        ? ` | 抓取于 ${options.fetchedAt}`
        : ''
      const conversionNote = options.convertedPrice
        ? ` | 汇率 1 ${source.price.currency} = ${options.fxRate} ${options.convertedPrice.currency}（${options.fxDate}）`
        : ''
      const reference = `${source.provider}/${source.model_id}`
      const maxReference =
        500 - lead.length - fetchedNote.length - conversionNote.length
      const visibleReference =
        reference.length <= maxReference
          ? reference
          : `${reference.slice(0, Math.max(0, maxReference - 1))}…`
      const price = {
        ...priceValues(options.convertedPrice ?? source.price),
        note: `${lead}${visibleReference}${fetchedNote}${conversionNote}`,
      }
      if (options.partialBudget) {
        price.cache_read = ''
        price.cache_write_5m = ''
        price.cache_write_1h = ''
      }
      if (options.target === 'budget_price') result.budget_price = price
      else result.bindings[Number(options.target.split('.')[1])].price = price
    }
  }
  return result
}

export function referencePrice(
  current: ModelValues,
  target: PriceKey
): PriceValues | undefined {
  return target === 'budget_price'
    ? current.budget_price
    : current.bindings[Number(target.split('.')[1])]?.price
}

export const declarationLabels: Record<string, string> = {
  supported: '支持',
  unsupported: '不支持',
  unknown: '未知',
}
export type ReferenceChange = { label: string; before: string; after: string }

export function referenceChanges(
  current: ModelValues,
  candidate: ModelValues,
  options: ImportOptions
): ReferenceChange[] {
  const rows: [string, string, string][] = [
    ['展示名称', current.name, candidate.name],
    ['技术名称', current.slug, candidate.slug],
    ['开发方', current.vendor, candidate.vendor],
    [
      '图标',
      current.icon_key || (current.icon ? '自定义' : ''),
      candidate.icon_key || (candidate.icon ? '自定义' : ''),
    ],
    ['上下文上限', current.context_window, candidate.context_window],
    ['最大输出', current.max_output, candidate.max_output],
    ...capabilities.map(([key, label]): [string, string, string] => [
      label,
      declarationLabels[current.capabilities[key]],
      declarationLabels[candidate.capabilities[key]],
    ]),
    ['思考参数', reasoningLabel(current), reasoningLabel(candidate)],
    [
      '资料来源',
      current.reference
        ? `${current.reference.provider} / ${current.reference.model_id}`
        : '',
      candidate.reference
        ? `${candidate.reference.provider} / ${candidate.reference.model_id}`
        : '',
    ],
    [
      '资料关联渠道',
      current.reference?.channel_id || '',
      candidate.reference?.channel_id || '',
    ],
  ]
  if (options.snapshot) {
    const last = candidate.quote_snapshots[candidate.quote_snapshots.length - 1]
    const label = `${last?.provider ?? ''} / ${last?.model_id ?? ''}`
    const previous = current.quote_snapshots.find(
      (item) => `${item.provider} / ${item.model_id}` === label
    )
    const next = candidate.quote_snapshots.find(
      (item) => `${item.provider} / ${item.model_id}` === label
    )
    if (next && JSON.stringify(previous) !== JSON.stringify(next))
      rows.push([
        '参考报价快照',
        previous ? `已有 ${label} 报价` : '未保存',
        `${previous ? '更新' : '新增'} ${label} · ${next.currency} / ${next.unit} ${next.metric} · ${Object.keys(next.raw_cost ?? {}).length} 项；不改变生效价格`,
      ])
  }
  if (options.price) {
    const before = referencePrice(current, options.target)
    const after = referencePrice(candidate, options.target)
    if (before && after)
      rows.push(
        ['价格备注', before.note, after.note],
        [
          '配置价格',
          before.enabled ? '开启' : '关闭',
          after.enabled ? '开启' : '关闭',
        ],
        ['币种', before.currency, after.currency],
        [
          '计价单位',
          `${before.unit} ${before.metric}`,
          `${after.unit} ${after.metric}`,
        ],
        ...rates.map(([key, label]): [string, string, string] => [
          label,
          before[key],
          after[key],
        ])
      )
  }
  return rows
    .filter(([, before, after]) => before !== after)
    .map(([label, before, after]) => ({
      label,
      before: before || '未配置',
      after: after || '清空（未提供）',
    }))
}

function reasoningLabel(model: ModelValues) {
  const r = model.reasoning
  return (
    [
      r.toggle && '开关',
      r.effort && `档位：${r.levels.join(' / ')}`,
      r.budget && `预算：${r.min || '未指定'} ~ ${r.max || '未指定'}`,
    ]
      .filter(Boolean)
      .join('；') || '未配置'
  )
}

// A provider ID is a catalogue namespace, not a model capability declaration.
export function referenceProvider(provider: string) {
  return (
    (
      {
        gemini: 'google',
        siliconcloud: 'siliconflow',
        zhipu: 'zhipuai',
        moonshot: 'moonshotai-cn',
        bailian: 'alibaba-cn',
      } as Record<string, string>
    )[provider] ?? provider
  )
}

export function isPlanChannel(channel: Schema['ChannelDetail']) {
  if (/plan/i.test(channel.provider)) return true
  const addresses = [
    channel.base_url,
    channel.connection?.service_root,
    channel.connection?.legacy_base_url,
  ]
  return addresses.some((address) => {
    try {
      return (
        !!address &&
        new URL(address).hostname === 'token-plan.maas.qianwenaiapi.com'
      )
    } catch {
      return false
    }
  })
}
