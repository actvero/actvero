import { useEffect, useRef, useState } from 'react'
import { FormProvider, useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { FieldDescription, FieldGroup } from '@/components/ui/field'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import type { ReferenceModel } from '@/features/model-catalog/reference-models'
import { gateway, useGateway } from './api'
import { ModelReferencePicker } from './model-reference-picker'
import type { ReferencePricingDraft } from './reference-pricing'
import {
  parameterInput,
  parameterSchema,
  parameterValues,
  type Parameters,
  type ParameterValues,
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
}

type EditorControls = {
  onChange: (state: ParameterDraftState) => void
  referenceOpen?: boolean
  closeReference?: () => void
  restoreReferenceFocus?: () => void
  pricingDirty?: boolean
  onReferencePricing?: (draft: ReferencePricingDraft) => void
  onReferenceOverwritePricing?: (draft: ReferencePricingDraft) => Promise<void>
}

const parametersPath = (model: string) =>
  '/parameters?include_reference=false&model=' + encodeURIComponent(model)

const editorValues = (saved: SavedParameters) =>
  parameterValues({
    ...saved,
    capability_mode: 'manual',
    chat_policy: undefined,
  })

const referenceSource = (reference: ReferenceModel) => ({
  provider: 'models.dev',
  model: reference.model_id,
  reference_provider: reference.provider,
})

export function ModelParameters({
  model,
  ...controls
}: { model: string } & EditorControls) {
  const query = useGateway<SavedParameters>(parametersPath(model), !!model)
  if (!model) return null
  if (query.isPending) return <LoadingState />
  if (query.error)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  return (
    <ParameterEditor
      key={model}
      model={model}
      saved={query.data}
      {...controls}
    />
  )
}

function ParameterEditor({
  model,
  saved,
  onChange,
  referenceOpen,
  closeReference,
  restoreReferenceFocus,
  pricingDirty,
  onReferencePricing,
  onReferenceOverwritePricing,
}: { model: string; saved: SavedParameters } & EditorControls) {
  const { csrf, organization } = useOrganization()
  const queryClient = useQueryClient()
  const [source, setSource] = useState(saved.source ?? {})
  const loadedVersion = useRef(saved.version ?? 0)
  const form = useForm({
    resolver: zodResolver(parameterSchema),
    mode: 'onChange',
    defaultValues: editorValues(saved),
  })
  const values = useWatch({ control: form.control })
  const dirty =
    form.formState.isDirty ||
    JSON.stringify(source) !== JSON.stringify(saved.source ?? {})
  const draft = {
    ...parameterInput(form.getValues()),
    version: saved.version ?? 0,
    reference_model: saved.reference_model ?? '',
    source,
  }
  delete (draft as Partial<Parameters>).chat_policy
  const serialized = JSON.stringify(draft)
  const valid = parameterSchema.safeParse(values).success
  useEffect(() => {
    const version = saved.version ?? 0
    if (version === loadedVersion.current) return
    loadedVersion.current = version
    form.reset(editorValues(saved))
    setSource(saved.source ?? {})
  }, [form, saved])
  useEffect(() => {
    onChange({ draft: JSON.parse(serialized), dirty, valid })
  }, [serialized, dirty, valid, onChange])

  function applyParameters(
    changes: Partial<ParameterValues>,
    reference: ReferenceModel
  ) {
    for (const key of [
      'context_window',
      'max_output',
      'capabilities',
      'reasoning',
    ] as const) {
      const value = changes[key]
      if (value !== undefined)
        form.setValue(key, value, { shouldDirty: true, shouldValidate: true })
    }
    setSource(referenceSource(reference))
  }

  async function overwriteParameters(
    changes: Partial<ParameterValues>,
    reference: ReferenceModel
  ) {
    const baseline = editorValues(saved)
    const imported = parameterSchema.safeParse({ ...baseline, ...changes })
    if (!imported.success) throw new Error('请核对预览中的模型参数。')
    const facts = parameterInput(imported.data)
    delete (facts as Partial<Parameters>).chat_policy
    const queryKey = [
      'model-gateway',
      organization.tenant_id,
      parametersPath(model),
    ]
    await queryClient.cancelQueries({ queryKey, exact: true })
    const result = await gateway<SavedParameters>(
      '/parameters?model=' + encodeURIComponent(model),
      'PUT',
      {
        ...facts,
        version: saved.version ?? 0,
        reference_model: saved.reference_model ?? '',
        source: referenceSource(reference),
      },
      csrf
    )
    const nextValues = editorValues(result)
    const previousDraft = form.getValues()
    const remainingDraft = Object.fromEntries(
      Object.entries(previousDraft).filter(
        ([key, value]) =>
          key !== 'capabilities' &&
          !(key in changes) &&
          JSON.stringify(value) !==
            JSON.stringify(baseline[key as keyof ParameterValues])
      )
    )
    const capabilities = { ...nextValues.capabilities }
    for (const key of Object.keys(
      capabilities
    ) as (keyof typeof capabilities)[]) {
      const before = baseline.capabilities[key]
      const importedValue = changes.capabilities?.[key] ?? before
      if (
        importedValue === before &&
        previousDraft.capabilities[key] !== before
      )
        capabilities[key] = previousDraft.capabilities[key]
    }
    loadedVersion.current = result.version ?? 0
    form.reset(nextValues)
    form.reset(
      { ...nextValues, ...remainingDraft, capabilities },
      { keepDefaultValues: true }
    )
    setSource(result.source ?? {})
    queryClient.setQueryData(queryKey, result)
  }

  return (
    <FormProvider {...form}>
      <FieldGroup>
        <TerminalParameters />
        {referenceOpen && closeReference && (
          <ModelReferencePicker
            model={model}
            initialSearch={source.model || model}
            current={form.getValues()}
            saved={
              onReferenceOverwritePricing ? editorValues(saved) : undefined
            }
            close={closeReference}
            restoreFocus={restoreReferenceFocus}
            pricingDirty={pricingDirty}
            onParameters={applyParameters}
            onPricing={onReferencePricing}
            onOverwriteParameters={overwriteParameters}
            onOverwritePricing={onReferenceOverwritePricing}
          />
        )}
        {(source.provider || saved.updated_at) && (
          <FieldDescription>
            {[
              source.provider
                ? [
                    `来源：${source.provider}`,
                    source.reference_provider,
                    source.model,
                  ]
                    .filter(Boolean)
                    .join(' / ')
                : '',
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
