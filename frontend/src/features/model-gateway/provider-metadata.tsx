import { useState } from 'react'
import { useFormContext } from 'react-hook-form'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { gateway } from './api'
import type { ParameterValues, Parameters } from './terminal-parameter-form'

export type MetadataSource = { id: number; name: string; type: number }
type ProviderPreview = {
  profile: Partial<Parameters> & { source: Record<string, string> }
  description: string
  model: string
  prices: Array<{
    range_name?: string
    prices?: Array<{
      type?: string
      price_name?: string
      price: string
      price_unit?: string
    }>
  }>
}

export function ProviderMetadata({
  model,
  reference,
  sources,
  onSource,
  onDescription,
  onPricing,
}: {
  model: string
  reference: string
  sources: MetadataSource[]
  onSource: (source: Record<string, string>) => void
  onDescription?: (description: string) => void
  onPricing?: () => void
}) {
  const candidates = sources.filter((source) => source.type === 17)
  const [channel, setChannel] = useState(String(candidates[0]?.id ?? ''))
  const [workspace, setWorkspace] = useState('')
  const { csrf } = useOrganization()
  const form = useFormContext<ParameterValues>()
  const query = useMutation({
    mutationFn: () =>
      gateway<ProviderPreview>(
        '/parameters/discover',
        'POST',
        {
          model_name: model,
          channel_id: Number(channel),
          reference_model: reference,
          workspace_id: workspace,
        },
        csrf
      ),
  })
  if (!candidates.length) return null
  return (
    <FieldSet>
      <FieldLegend variant='label'>供应商资料</FieldLegend>
      <FieldGroup className='grid gap-4 sm:grid-cols-2'>
        <Field>
          <FieldLabel htmlFor='metadata-channel'>资料来源渠道</FieldLabel>
          <Select value={channel} onValueChange={setChannel}>
            <SelectTrigger id='metadata-channel' className='w-full'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {candidates.map((source) => (
                  <SelectItem key={source.id} value={String(source.id)}>
                    {source.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel htmlFor='metadata-workspace'>
            业务空间 ID（可选）
          </FieldLabel>
          <Input
            id='metadata-workspace'
            value={workspace}
            onChange={(event) => setWorkspace(event.target.value)}
            maxLength={64}
            placeholder='北京地域业务空间 ID'
          />
        </Field>
      </FieldGroup>
      <Button
        type='button'
        variant='outline'
        disabled={query.isPending || !channel}
        onClick={() => query.mutate()}
      >
        {query.isPending ? '获取中…' : '获取供应商资料'}
      </Button>
      {query.error && <RequestError error={query.error} />}
      {query.data && (
        <FieldGroup>
          <FieldDescription>
            已获取 {query.data.model}；上下文{' '}
            {query.data.profile.context_window?.toLocaleString() ?? '未知'}
            ，最大输出{' '}
            {query.data.profile.max_output?.toLocaleString() ?? '未知'} Token。
          </FieldDescription>
          <Button
            type='button'
            variant='outline'
            onClick={() => {
              const p = query.data.profile
              for (const key of ['context_window', 'max_output'] as const)
                if (!form.getValues(key) && p[key])
                  form.setValue(key, String(p[key]), {
                    shouldDirty: true,
                    shouldValidate: true,
                  })
              for (const [key, value] of Object.entries(p.capabilities ?? {})) {
                const name =
                  `capabilities.${key}` as `capabilities.${keyof ParameterValues['capabilities']}`
                if (form.getValues(name) === 'unknown' && value !== 'unknown')
                  form.setValue(name, value, {
                    shouldDirty: true,
                    shouldValidate: true,
                  })
              }
              form.setValue('capability_mode', 'manual', { shouldDirty: true })
              onSource(p.source)
              onDescription?.(query.data.description)
            }}
          >
            带入缺失参数和说明
          </Button>
          {!!query.data.prices.length && (
            <FieldSet>
              <FieldLegend variant='label'>供应商报价参考</FieldLegend>
              <ul className='flex flex-col gap-1 text-sm text-muted-foreground'>
                {query.data.prices.slice(0, 20).flatMap((range, index) =>
                  (range.prices ?? []).slice(0, 10).map((price, offset) => (
                    <li key={`${index}-${offset}`}>
                      {String(range.range_name ?? '')} ·{' '}
                      {String(price.price_name ?? price.type ?? '单价')}：
                      {String(price.price)} /{' '}
                      {String(price.price_unit ?? '供应商计价单位')}
                    </li>
                  ))
                )}
              </ul>
              <FieldDescription>参考报价，保存定价后生效。</FieldDescription>
              {onPricing && (
                <Button type='button' variant='link' onClick={onPricing}>
                  配置模型定价
                </Button>
              )}
            </FieldSet>
          )}
        </FieldGroup>
      )}
    </FieldSet>
  )
}
