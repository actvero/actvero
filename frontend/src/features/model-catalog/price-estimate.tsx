import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { api, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { CollapsibleSection } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  rates,
  forKind,
  pointStates,
  metrics,
  priceInput,
  type ModelValues,
  type PriceKey,
} from './model-form'

export function PriceEstimate({
  name,
  disabled,
}: {
  name: PriceKey
  disabled: boolean
}) {
  const form = useFormContext<ModelValues>()
  const raw = useWatch({ control: form.control, name })
  const kind = useWatch({ control: form.control, name: 'kind' })
  const price = forKind(raw, kind)
  const visibleRates = kind === 'chat' ? rates : rates.slice(0, 1)
  const { csrf } = useOrganization()
  const [usage, setUsage] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<{
    key: string
    data: Schema['PriceEstimateView']
  } | null>(null)
  const key = JSON.stringify([price, usage, kind])
  async function calculate() {
    if (!(await form.trigger(name))) return
    const tokens: Record<string, number> = {}
    for (const [item] of visibleRates) {
      const raw = usage[item] || '0'
      if (!/^\d+$/.test(raw) || Number(raw) > 1e12) {
        setError(new Error('用量须为 0 至 1000000000000 的整数'))
        return
      }
      tokens[item] = Number(raw)
    }
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const data = await api<Schema['PriceEstimateView']>(
        '/llm/prices/estimate',
        'POST',
        {
          price: priceInput(
            kind === 'chat'
              ? price
              : {
                  ...price,
                  output: '',
                  cache_read: '',
                  cache_write_5m: '',
                  cache_write_1h: '',
                }
          ),
          usage: tokens,
          include_points: name === 'budget_price',
        },
        csrf
      )
      setResult({ key, data })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <CollapsibleSection title='费用试算'>
      <div className='flex flex-col gap-4'>
        {kind === 'chat' && (
          <p className='text-sm text-muted-foreground'>
            输入不含缓存，输出包含推理 Token。各项用量不要重复填写。
          </p>
        )}
        <div className='grid gap-4 sm:grid-cols-6'>
          {visibleRates.map(([item, label]) => (
            <div
              key={item}
              className={cn(
                'flex min-w-0 flex-col gap-2',
                item === 'input' || item === 'output'
                  ? 'sm:col-span-3'
                  : 'sm:col-span-2'
              )}
            >
              <Label htmlFor={`usage-${item}`}>
                {price.metric === 'images'
                  ? '图片数量（张）'
                  : price.metric === 'search_units'
                    ? '搜索单位用量'
                    : `${label} ${metrics[price.metric]}`}{' '}
              </Label>
              <Input
                id={`usage-${item}`}
                value={usage[item] ?? ''}
                inputMode='numeric'
                placeholder='0'
                disabled={busy || disabled}
                onChange={(e) => {
                  setUsage({ ...usage, [item]: e.target.value })
                  setError(null)
                }}
              />
            </div>
          ))}
        </div>
        <Button
          type='button'
          variant='outline'
          disabled={disabled || busy}
          onClick={() => void calculate()}
        >
          {busy ? '计算中…' : '计算费用'}
        </Button>
        {!!error && <RequestError error={error} />}
        {result?.key === key && (
          <Alert>
            <AlertTitle>
              合计 {result.data.currency} {result.data.total}
            </AlertTitle>
            <AlertDescription>
              {result.data.points && (
                <span>
                  {result.data.points.status === 'ready'
                    ? `积分消耗：${result.data.points.total} 积分（换算版本 ${result.data.points.conversion?.version}）`
                    : pointStates[result.data.points.status]}
                </span>
              )}
              {result.data.items
                .filter((item) => item.tokens > 0)
                .map((item) => (
                  <span key={item.item}>
                    {rates.find(([id]) => id === item.item)?.[1]}：{item.tokens}{' '}
                    × {item.rate} / {price.unit === '1' ? '1' : '1M'} ={' '}
                    {item.amount}
                  </span>
                ))}
            </AlertDescription>
          </Alert>
        )}
      </div>
    </CollapsibleSection>
  )
}
