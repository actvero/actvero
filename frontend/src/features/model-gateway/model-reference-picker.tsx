import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  useCanEditModelPricing,
  useModelPricing,
} from '@newapi/features/model-pricing/api'
import { toast } from 'sonner'
import { messageOf } from '@/lib/api'
import { Separator } from '@/components/ui/separator'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ReferenceCreate } from '@/features/model-catalog/reference-create'
import type { ReferenceModel } from '@/features/model-catalog/reference-models'
import { planParameterFill } from './parameter-reference'
import { ParameterReferencePreview } from './parameter-reference-preview'
import {
  referencePricing,
  type ReferencePricingDraft,
} from './reference-pricing'
import type { ParameterValues } from './terminal-parameter-form'

export function ModelReferencePicker({
  model,
  initialSearch,
  current,
  saved,
  close,
  restoreFocus,
  pricingDirty,
  onParameters,
  onPricing,
  onOverwriteParameters,
  onOverwritePricing,
}: {
  model: string
  initialSearch: string
  current: ParameterValues
  saved?: ParameterValues
  close: () => void
  restoreFocus?: () => void
  pricingDirty?: boolean
  onParameters: (
    changes: Partial<ParameterValues>,
    reference: ReferenceModel
  ) => void
  onPricing?: (draft: ReferencePricingDraft) => void
  onOverwriteParameters: (
    changes: Partial<ParameterValues>,
    reference: ReferenceModel
  ) => Promise<void>
  onOverwritePricing?: (draft: ReferencePricingDraft) => Promise<void>
}) {
  const queryClient = useQueryClient()
  const { organization } = useOrganization()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error>()
  const canEditPricing = useCanEditModelPricing()
  const priceQuery = useModelPricing([model], !!onPricing)
  const currentPrice = priceQuery.data?.entries.find(
    (entry) => entry.model_name === model
  )
  const effective = currentPrice?.effective
  const hasPrice =
    effective &&
    (effective.ModelRatio !== undefined ||
      effective.ModelPrice !== undefined ||
      !!effective['billing_setting.billing_expr'] ||
      pricingDirty)
  const currentRule =
    effective?.['billing_setting.billing_mode'] === 'tiered_expr'
      ? effective['billing_setting.billing_expr']
      : effective?.ModelPrice !== undefined
        ? `每次 USD ${effective.ModelPrice}`
        : typeof effective?.ModelRatio === 'number'
          ? `输入 USD ${effective.ModelRatio * 2} / 百万 Token${typeof effective.CompletionRatio === 'number' ? `，输出 USD ${effective.ModelRatio * 2 * effective.CompletionRatio} / 百万 Token` : ''}`
          : '未配置'

  async function persistOverwrite(
    plan: ReturnType<typeof planParameterFill>,
    reference: ReferenceModel,
    price: ReferencePricingDraft | null
  ) {
    if (pending) return
    setPending(true)
    setError(undefined)
    let parametersSaved = false
    let savingPrice = false
    try {
      if (plan.count) {
        await onOverwriteParameters(plan.changes, reference)
        parametersSaved = true
      }
      if (price && onOverwritePricing) {
        savingPrice = true
        await onOverwritePricing(price)
      }
      toast.success('已覆盖并保存远程资料')
      close()
    } catch (failure) {
      const context = savingPrice
        ? parametersSaved
          ? '模型参数已保存，定价保存失败。'
          : '定价保存失败。'
        : '模型参数保存失败。'
      setError(new Error(context + messageOf(failure)))
      if (savingPrice) await priceQuery.refetch()
    } finally {
      setPending(false)
      if (parametersSaved || savingPrice) {
        void queryClient.invalidateQueries({
          queryKey: ['model-gateway', organization.tenant_id],
          predicate: ({ queryKey }) =>
            [
              'publication-preview',
              'publication-status',
              '/publication?model=' + encodeURIComponent(model),
            ].includes(String(queryKey[2])),
        })
      }
    }
  }

  return (
    <ReferenceCreate
      initialSearch={initialSearch}
      returnLabel={model}
      close={close}
      restoreFocus={restoreFocus}
      pending={pending}
      footer={
        error ? (
          <RequestError error={error} />
        ) : pending ? (
          <span role='status'>正在保存远程资料…</span>
        ) : saved ? (
          '填入写入草稿，覆盖后直接生效。'
        ) : (
          '应用到草稿，保存后生效。'
        )
      }
      preview={(reference) => {
        const fill = planParameterFill(current, reference)
        const overwrite = planParameterFill(saved ?? current, reference, true)
        const quote = referencePricing(reference, currentPrice)
        const priceDraft =
          onPricing && canEditPricing && !priceQuery.isError
            ? quote.draft
            : null
        const fillPrice = hasPrice ? null : priceDraft
        const pricePending = onPricing && canEditPricing && priceQuery.isPending
        const apply = (
          plan: typeof fill,
          price: ReferencePricingDraft | null
        ) => {
          if (plan.count) onParameters(plan.changes, reference)
          if (price) onPricing?.(price)
          close()
        }
        return {
          actions: [
            {
              label: '覆盖已有值',
              variant: 'outline',
              enabled:
                !pricePending &&
                (saved
                  ? overwrite.count > 0 || !!priceDraft
                  : overwrite.rows.some((row) => row.action === '覆盖')),
              apply: () => {
                if (saved)
                  void persistOverwrite(overwrite, reference, priceDraft)
                else apply(overwrite, priceDraft)
              },
            },
            {
              label: '填入空白',
              enabled: !pricePending && (fill.count > 0 || !!fillPrice),
              apply: () => apply(fill, fillPrice),
            },
          ],
          content: (
            <div className='flex min-w-0 flex-col gap-4'>
              <ParameterReferencePreview
                reference={reference}
                fillRows={fill.rows}
                overwriteRows={overwrite.rows}
              />
              {onPricing && (
                <div className='flex flex-col gap-2 text-sm'>
                  <Separator className='mb-1' />
                  <h3 className='font-medium'>参考报价 · USD / 百万 Token</h3>
                  {quote.rates.length > 0 ? (
                    <dl className='grid grid-cols-2 gap-2'>
                      {quote.rates.map(({ key, label, value }) => (
                        <div key={key}>
                          <dt className='text-muted-foreground'>{label}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className='text-muted-foreground'>
                      供应商未提供可识别的 Token 单价。
                    </p>
                  )}
                  {canEditPricing && priceQuery.isError ? (
                    <RequestError
                      error={priceQuery.error}
                      retry={() => void priceQuery.refetch()}
                    />
                  ) : !canEditPricing ? (
                    <p className='text-muted-foreground'>
                      当前账号可查看报价，定价需由有权限的管理员维护。
                    </p>
                  ) : priceQuery.isPending ? (
                    <p role='status' className='text-muted-foreground'>
                      正在读取当前定价…
                    </p>
                  ) : !currentPrice ? (
                    <p className='text-muted-foreground'>
                      保存模型资料后可应用定价。
                    </p>
                  ) : (
                    <>
                      <p className='break-all text-muted-foreground'>
                        当前定价 {currentRule}
                      </p>
                      {!quote.draft && quote.rates.length > 0 && (
                        <p className='text-muted-foreground'>
                          这份报价的计量或计价条件需要在定价页核对。
                        </p>
                      )}
                      {pricingDirty && priceDraft && (
                        <p className='text-muted-foreground'>
                          覆盖会替换尚未保存的定价草稿。
                        </p>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          ),
        }
      }}
    />
  )
}
