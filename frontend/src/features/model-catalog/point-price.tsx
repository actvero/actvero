import { useDeferredValue } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  metrics,
  forKind,
  priceInput,
  priceSchema,
  rates,
  pointStates,
  type ModelValues,
} from './model-form'
import { PointConversionButton } from './point-conversion'

export function PointPricePreview() {
  const form = useFormContext<ModelValues>()
  const raw = useWatch({ control: form.control, name: 'budget_price' })
  const kind = useWatch({ control: form.control, name: 'kind' })
  const price = forKind(raw, kind)
  const visibleRates = kind === 'chat' ? rates : rates.slice(0, 1)
  const { csrf, organization } = useOrganization()
  const parsed = priceSchema.safeParse(
    kind === 'chat'
      ? price
      : {
          ...price,
          output: '',
          cache_read: '',
          cache_write_5m: '',
          cache_write_1h: '',
        }
  )
  const data = parsed.success && price.enabled ? priceInput(parsed.data) : null
  const body = useDeferredValue(JSON.stringify(data))
  // CSRF is not part of cache identity; these requests contain only public pricing inputs.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'llm-point-prices',
      body,
    ],
    enabled: data !== null && body === JSON.stringify(data),
    queryFn: ({ signal }) =>
      api<Schema['PointPrice']>(
        '/llm/point-prices/preview',
        'POST',
        JSON.parse(body),
        csrf,
        signal
      ),
  })
  if (!data)
    return (
      <p className='text-sm text-muted-foreground'>
        填写有效的币种和单价后查看积分。
      </p>
    )
  const result = query.data
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <span className='font-medium'>
          积分 /{' '}
          {price.metric === 'images'
            ? '每张'
            : price.metric === 'seconds'
              ? '每秒'
              : `每百万 ${metrics[price.metric]}`}
        </span>
        <PointConversionButton />
      </div>
      {query.isPending || query.isFetching || body !== JSON.stringify(data) ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : result?.status === 'ready' ? (
        <>
          <p className='text-sm text-muted-foreground'>
            1 {result.conversion?.currency} ={' '}
            {result.conversion?.points_per_currency} 积分
          </p>
          <dl className='grid gap-4 sm:grid-cols-2'>
            {visibleRates.map(([key, label]) => (
              <div key={key} className='flex flex-col gap-1'>
                <dt className='text-sm text-muted-foreground'>
                  {price.metric === 'images' ? '每张' : label}
                </dt>
                <dd className='break-all'>
                  {result.rates?.[key] == null
                    ? '未配置'
                    : `${result.rates?.[key]} 积分`}
                </dd>
              </div>
            ))}
          </dl>
        </>
      ) : (
        result && (
          <p role='status' className='text-sm text-muted-foreground'>
            {pointStates[result.status]}
          </p>
        )
      )}
    </div>
  )
}
