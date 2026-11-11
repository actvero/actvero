import type { ModelPricingEntry } from '@newapi/features/model-pricing/api'
import type { PricingValues } from '@newapi/features/model-pricing/pricing'
import type { ReferenceModel } from '@/features/model-catalog/reference-models'

export type ReferencePricingDraft = {
  expectedVersion: string
  pricing: PricingValues
}

const lanes = [
  ['input', '输入', 'p'],
  ['output', '输出', 'c'],
  ['cache_read', '缓存读取', 'cr'],
  ['cache_write', '缓存写入', 'cc'],
] as const

export function referencePricing(
  reference: ReferenceModel,
  entry?: ModelPricingEntry
) {
  const quote = reference.price
  const raw = reference.quote_snapshot?.raw_cost
  const rates = lanes.flatMap(([key, label, token]) => {
    const value = key === 'cache_write' ? raw?.cache_write : quote?.[key]
    return typeof value === 'string' || typeof value === 'number'
      ? [{ key, label, token, value: String(value) }]
      : []
  })
  const unsupported =
    Object.keys(raw ?? {}).some(
      (key) => !lanes.some(([lane]) => lane === key)
    ) || reference.quote_items?.some((item) => item.status === 'invalid')
  const splitCache =
    entry?.cache_write_mode === 'claude_ttl' ||
    entry?.cache_write_mode === 'openai_ttl'
  const valid =
    quote?.currency === 'USD' &&
    quote.unit === 1000000 &&
    quote.metric === 'tokens' &&
    rates.some((rate) => rate.key === 'input') &&
    rates.some((rate) => rate.key === 'output') &&
    rates.every((rate) => /^\d{1,10}(?:\.\d{1,12})?$/.test(rate.value))
  if (
    !entry ||
    !valid ||
    unsupported ||
    (splitCache && rates.some((rate) => rate.key === 'cache_write')) ||
    (!reference.price_importable &&
      !rates.some((rate) => rate.key === 'cache_write'))
  )
    return { rates, draft: null }

  const expression = `tier("base", ${rates.map(({ token, value }) => `${token} * ${value}`).join(' + ')})`
  const draft: ReferencePricingDraft = {
    expectedVersion: entry.version,
    pricing: {
      'billing_setting.plugin_billing_expr':
        entry.configured['billing_setting.plugin_billing_expr'],
      'billing_setting.billing_mode': 'tiered_expr',
      'billing_setting.billing_expr': expression,
    },
  }
  return { rates, draft }
}
