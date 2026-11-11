import { useEffect, useState } from 'react'
import { FormProvider, useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Button } from '@/components/ui/button'
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { LoadingState, RequestError } from '@/components/request-state'
import { useGateway } from './api'
import { ProviderMetadata, type MetadataSource } from './provider-metadata'
import {
  parameterInput,
  parameterSchema,
  parameterValues,
  type Parameters,
} from './terminal-parameter-form'
import { TerminalParameters } from './terminal-parameters'

export type ParameterDraftState = {
  draft: Record<string, unknown>
  dirty: boolean
  valid: boolean
}
type SavedParameters = Partial<Parameters> & {
  version?: number
  reference_model?: string
  updated_at?: string
  source?: Record<string, string>
  sources?: MetadataSource[]
  automatic?: Partial<Parameters> & {
    status: string
    source?: Record<string, string>
    reason?: string
  }
}

export function ModelParameters({
  model,
  onChange,
  onDescription,
  onPricing,
}: {
  model: string
  onChange: (state: ParameterDraftState) => void
  onDescription?: (description: string) => void
  onPricing?: () => void
}) {
  const query = useGateway<SavedParameters>(
    '/parameters?model=' + encodeURIComponent(model),
    !!model
  )
  if (!model) return null
  if (query.isPending) return <LoadingState />
  if (query.error)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  return (
    <ParameterEditor
      key={`${model}:${query.data.version ?? 0}`}
      model={model}
      saved={query.data}
      onChange={onChange}
      onDescription={onDescription}
      onPricing={onPricing}
    />
  )
}

function ParameterEditor({
  model,
  saved,
  onChange,
  onDescription,
  onPricing,
}: {
  model: string
  saved: SavedParameters
  onChange: (state: ParameterDraftState) => void
  onDescription?: (description: string) => void
  onPricing?: () => void
}) {
  const [reference, setReference] = useState(saved.reference_model ?? '')
  const [source, setSource] = useState(saved.source ?? {})
  const form = useForm({
    resolver: zodResolver(parameterSchema),
    mode: 'onChange',
    defaultValues: parameterValues({
      ...((saved.version ?? 0) === 0 && saved.automatic?.status === 'resolved'
        ? saved.automatic
        : {}),
      ...saved,
      chat_policy: undefined,
    }),
  })
  const values = useWatch({ control: form.control })
  const dirty =
    form.formState.isDirty ||
    reference !== (saved.reference_model ?? '') ||
    JSON.stringify(source) !== JSON.stringify(saved.source ?? {})
  const draft = {
    ...parameterInput(form.getValues()),
    version: saved.version ?? 0,
    reference_model: reference,
    source,
  }
  delete (draft as Partial<Parameters>).chat_policy
  const serialized = JSON.stringify(draft)
  const valid = parameterSchema.safeParse(values).success
  useEffect(() => {
    onChange({ draft: JSON.parse(serialized), dirty, valid })
  }, [serialized, dirty, valid, onChange])
  return (
    <FormProvider {...form}>
      <FieldGroup>
        <ProviderMetadata
          model={model}
          reference={reference}
          sources={saved.sources ?? []}
          onSource={setSource}
          onDescription={onDescription}
          onPricing={onPricing}
        />
        <TerminalParameters
          resolved={saved.automatic?.status === 'resolved'}
          onPrefill={() => {
            if (saved.automatic?.status !== 'resolved') return
            setSource(saved.automatic.source ?? {})
            const next = parameterValues({
              ...saved.automatic,
              capability_mode: 'manual',
              chat_policy: undefined,
            })
            for (const key of Object.keys(next) as (keyof typeof next)[])
              form.setValue(key, next[key], {
                shouldDirty: true,
                shouldValidate: true,
              })
          }}
        />
        {values.capability_mode === 'auto' && (
          <FieldDescription>
            {saved.automatic?.status === 'resolved'
              ? `上下文 ${saved.automatic.context_window?.toLocaleString()} · 最大输出 ${saved.automatic.max_output?.toLocaleString()} Token`
              : saved.automatic?.status === 'conflict'
                ? '参数不一致'
                : saved.automatic?.status === 'unavailable'
                  ? '资料暂不可用'
                  : '未匹配到参数'}
          </FieldDescription>
        )}
        <Field>
          <FieldLabel htmlFor='parameter-reference-model'>
            参考模型 ID（可选）
          </FieldLabel>
          <Input
            id='parameter-reference-model'
            value={reference}
            maxLength={128}
            onChange={(event) => setReference(event.target.value)}
            placeholder='留空自动匹配'
          />
        </Field>
        {(source.provider || saved.updated_at) && (
          <FieldDescription>
            {[
              source.provider ? `来源：${source.provider}` : '',
              saved.updated_at
                ? `更新于 ${new Date(saved.updated_at).toLocaleString()}`
                : '',
            ]
              .filter(Boolean)
              .join(' · ')}
          </FieldDescription>
        )}
        {Object.keys(form.formState.errors).length > 0 && (
          <Button
            type='button'
            variant='link'
            onClick={() => void form.trigger()}
          >
            请核对上方参数
          </Button>
        )}
      </FieldGroup>
    </FormProvider>
  )
}
