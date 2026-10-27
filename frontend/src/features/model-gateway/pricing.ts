import type { PriceEntry, PriceValues } from './api'

const number = (v: unknown) => (typeof v === 'number' ? v : undefined)
export function tokenRates(pricing: PriceValues, unit: number) {
  const input = number(pricing.ModelRatio)
  const base = input === undefined ? undefined : (input * 1000000) / unit
  return {
    input: base,
    output:
      base === undefined || number(pricing.CompletionRatio) === undefined
        ? undefined
        : base * Number(pricing.CompletionRatio),
    cache:
      base === undefined || number(pricing.CacheRatio) === undefined
        ? undefined
        : base * Number(pricing.CacheRatio),
    write:
      base === undefined || number(pricing.CreateCacheRatio) === undefined
        ? undefined
        : base * Number(pricing.CreateCacheRatio),
  }
}
export function makePricing(
  entry: PriceEntry,
  mode: string,
  rates: Record<string, string>,
  fixed: string,
  expression: string,
  unit: number
): PriceValues {
  const result = { ...entry.configured }
  const finite = (text: string) => {
    const v = Number(text)
    if (!Number.isFinite(v) || v < 0) throw new Error('价格须为非负数字')
    return v
  }
  if (mode === 'expression') {
    result['billing_setting.billing_mode'] = 'tiered_expr'
    result['billing_setting.billing_expr'] = expression
    return result
  }
  result['billing_setting.billing_mode'] = 'ratio'
  delete result['billing_setting.billing_expr']
  if (mode === 'request') {
    if (!fixed.trim()) delete result.ModelPrice
    else result.ModelPrice = finite(fixed)
    return result
  }
  delete result.ModelPrice
  if (!rates.input.trim()) delete result.ModelRatio
  else result.ModelRatio = (finite(rates.input) * unit) / 1000000
  const base = rates.input.trim()
    ? finite(rates.input)
    : tokenRates(entry.effective, unit).input
  for (const [field, key] of [
    ['output', 'CompletionRatio'],
    ['cache', 'CacheRatio'],
    ['write', 'CreateCacheRatio'],
  ]) {
    if (!rates[field].trim()) {
      delete result[key]
      continue
    }
    const rate = finite(rates[field])
    if (base === undefined || (base === 0 && rate > 0))
      throw new Error(
        '请先填写非零输入价格；输入免费、输出收费时请使用表达式计价。'
      )
    result[key] = base === 0 ? 0 : rate / base
  }
  return result
}
