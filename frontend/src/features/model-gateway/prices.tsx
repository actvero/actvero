import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { FieldGroup } from '@/components/ui/field'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  gateway,
  useGateway,
  useGatewayRefresh,
  type PriceEntry,
  type Prices,
  type PriceValues,
} from './api'
import { makePricing, tokenRates } from './pricing'
import { AreaField, ChoiceField, TextField } from './shared'

export function ModelPrices({ model }: { model: string }) {
  const query = useGateway<Prices>('/prices?model=' + encodeURIComponent(model))
  if (query.isPending) return <LoadingState />
  if (query.error)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  const entry = query.data.entries.find((e) => e.model_name === model) ?? {
    model_name: model,
    version: query.data.empty_version,
    configured: {},
    effective: {},
    billing_details: {},
  }
  return (
    <PriceForm
      key={entry.version}
      entry={entry}
      unit={query.data.quota_per_unit}
    />
  )
}
const tokenFields = [
  ['input', '输入'],
  ['output', '输出'],
  ['cache', '缓存读取'],
  ['write', '缓存写入'],
] as const
function PriceForm({ entry, unit }: { entry: PriceEntry; unit: number }) {
  const { csrf } = useOrganization()
  const refresh = useGatewayRefresh()
  const effective = tokenRates(entry.effective, unit)
  const configured = tokenRates(
    { ...entry.effective, ...entry.configured },
    unit
  )
  const [mode, setMode] = useState(
    entry.effective['billing_setting.billing_mode'] === 'tiered_expr'
      ? 'expression'
      : entry.effective.ModelPrice !== undefined
        ? 'request'
        : 'tokens'
  )
  const [rates, setRates] = useState<Record<string, string>>({
    input:
      entry.configured.ModelRatio !== undefined
        ? String(configured.input ?? '')
        : '',
    output:
      entry.configured.CompletionRatio !== undefined
        ? String(configured.output ?? '')
        : '',
    cache:
      entry.configured.CacheRatio !== undefined
        ? String(configured.cache ?? '')
        : '',
    write:
      entry.configured.CreateCacheRatio !== undefined
        ? String(configured.write ?? '')
        : '',
  })
  const [fixed, setFixed] = useState(String(entry.configured.ModelPrice ?? ''))
  const [expression, setExpression] = useState(
    String(entry.effective['billing_setting.billing_expr'] ?? '')
  )
  const [preview, setPreview] = useState<PriceValues | null>(null)
  const save = useMutation({
    mutationFn: async (action: 'preview' | 'save' | 'reset') => {
      const pricing =
        action === 'reset'
          ? {}
          : makePricing(entry, mode, rates, fixed, expression, unit)
      if (action === 'preview') {
        const r = await gateway<{ effective: PriceValues }>(
          '/prices/preview',
          'POST',
          { model_name: entry.model_name, pricing },
          csrf
        )
        setPreview(r.effective)
        return
      }
      await gateway(
        '/prices',
        'PUT',
        {
          model_name: entry.model_name,
          expected_version: entry.version,
          pricing,
          reset: action === 'reset',
        },
        csrf
      )
      await refresh()
      toast.success('价格已保存')
    },
  })
  const shown = preview ?? entry.effective
  const shownRates = tokenRates(shown, unit)
  return (
    <form
      className='flex flex-col gap-5 pt-4'
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate('save')
      }}
    >
      <FieldGroup>
        <ChoiceField
          label='计价方式'
          value={mode}
          onChange={(v) => {
            setMode(v)
            setPreview(null)
          }}
          options={[
            { value: 'tokens', label: '按 Token' },
            { value: 'request', label: '按次' },
            { value: 'expression', label: '表达式 / 阶梯计价' },
          ]}
        />
        {mode === 'tokens' ? (
          <div className='grid gap-4 sm:grid-cols-2'>
            {tokenFields.map(([key, label]) => (
              <TextField
                key={key}
                label={`${label}（美元 / 百万 Token）`}
                type='number'
                min='0'
                step='any'
                value={rates[key]}
                placeholder={
                  effective[key] === undefined
                    ? '未配置'
                    : `继承：${effective[key]}`
                }
                onChange={(e) => {
                  setRates({ ...rates, [key]: e.target.value })
                  setPreview(null)
                }}
              />
            ))}
          </div>
        ) : mode === 'request' ? (
          <TextField
            label='单价（美元 / 次）'
            type='number'
            min='0'
            step='any'
            value={fixed}
            placeholder={
              entry.effective.ModelPrice === undefined
                ? '未配置'
                : `继承：${entry.effective.ModelPrice}`
            }
            onChange={(e) => {
              setFixed(e.target.value)
              setPreview(null)
            }}
          />
        ) : (
          <AreaField
            label='计价表达式'
            value={expression}
            onChange={(e) => {
              setExpression(e.target.value)
              setPreview(null)
            }}
            rows={7}
            className='font-mono text-xs'
          />
        )}
      </FieldGroup>
      <p className='text-xs text-muted-foreground'>
        留空使用网关默认价格，0
        表示免费。以上为基础价格，实际计费还会应用分组倍率。
      </p>
      <div className='rounded-md border bg-muted/30 p-4'>
        <p className='mb-3 text-sm font-medium'>
          {preview ? '保存后的价格预览' : '当前生效价格'}
        </p>
        {shown['billing_setting.billing_mode'] === 'tiered_expr' ? (
          <p className='font-mono text-xs break-all'>
            {String(shown['billing_setting.billing_expr'] ?? '表达式未配置')}
          </p>
        ) : shown.ModelPrice !== undefined ? (
          <p className='text-sm'>{String(shown.ModelPrice)} 美元 / 次</p>
        ) : (
          <div className='grid grid-cols-2 gap-3 text-sm sm:grid-cols-4'>
            {tokenFields.map(([key, label]) => (
              <div key={key}>
                <p className='text-muted-foreground'>{label}</p>
                <p className='font-medium'>
                  {shownRates[key] === undefined
                    ? '未配置'
                    : `$${Number(shownRates[key]?.toPrecision(8))} / M`}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
      {save.error && <RequestError error={save.error} />}
      <div className='flex justify-end gap-2'>
        <Button
          type='button'
          variant='outline'
          disabled={save.isPending}
          onClick={() => save.mutate('preview')}
        >
          预览价格
        </Button>
        <Button disabled={save.isPending}>
          {save.isPending ? '正在处理…' : '保存价格'}
        </Button>
      </div>
    </form>
  )
}
