import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { useOrganization } from '@/features/auth/session'
import type { ModelValues } from './model-form'
import { referenceProvider } from './reference-import'
import { importModel } from './reference-models'

/** Public metadata is advisory. Match both provider and model, and never import prices here. */
export function MetadataSuggestion() {
  const form = useFormContext<ModelValues>()
  const reference = useWatch({ control: form.control, name: 'reference' })
  const { organization } = useOrganization()
  const [appliedKey, setAppliedKey] = useState('')
  const provider = referenceProvider(reference?.provider ?? '')
  const modelId = reference?.model_id ?? ''
  const key = `${provider}/${modelId}`
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-metadata-suggestion',
      provider,
      modelId,
    ],
    enabled: !!provider && !!modelId,
    queryFn: ({ signal }) =>
      api<Schema['ReferencePage']>(
        `/llm/reference-models?${new URLSearchParams({ provider, q: modelId.slice(0, 100), preferred_provider: provider, preferred_model: modelId })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
    staleTime: 60_000,
  })
  if (!provider || !modelId) return null
  const matches =
    query.data?.items?.filter(
      (item) => item.provider === provider && item.model_id === modelId
    ) ?? []
  const match = matches.length === 1 ? matches[0] : null
  return (
    <div className='rounded-md border bg-muted/30 p-3 text-sm'>
      {query.isPending ? (
        <p role='status'>正在匹配公开参数资料，可继续填写…</p>
      ) : query.isError ? (
        <div className='flex flex-wrap items-center gap-2'>
          <p>公开资料暂不可用，已填写内容不受影响。</p>
          <Button
            type='button'
            variant='link'
            size='sm'
            onClick={() => void query.refetch()}
          >
            重试读取资料
          </Button>
        </div>
      ) : match ? (
        <>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span>
              找到相同来源的资料：{match.provider} / {match.model_id}
            </span>
            <Button
              type='button'
              size='sm'
              variant='outline'
              disabled={appliedKey === key}
              onClick={() => {
                const next = importModel(form.getValues(), match, false)
                for (const field of [
                  'vendor',
                  'context_window',
                  'max_output',
                  'capabilities',
                  'reasoning',
                  'icon_key',
                  'reference',
                ] as const)
                  form.setValue(field, next[field], {
                    shouldDirty: true,
                    shouldValidate: true,
                  })
                setAppliedKey(key)
              }}
            >
              {appliedKey === key ? '已补全空白参数' : '补全空白参数'}
            </Button>
          </div>
          <p className='mt-1 text-xs text-muted-foreground'>
            {query.data?.stale ? '当前是缓存资料。' : ''}
            仅补全空白项，价格另行确认；公开能力不代表此渠道已通过调用测试。
          </p>
        </>
      ) : (
        <p className='text-muted-foreground'>
          未找到相同供应商和模型 ID
          的资料。可手动填写，或通过“从公开资料补全”查找并核对其他来源。
        </p>
      )}
    </div>
  )
}
