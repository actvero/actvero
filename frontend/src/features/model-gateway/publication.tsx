import { useEffect, useId, useState } from 'react'
import { FormProvider, useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import type { Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { MemberPicker } from '@/components/member-picker'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ChatPolicyFields } from '@/features/model-catalog/chat-policy-fields'
import { chatPolicyInput } from '@/features/model-catalog/chat-policy-form'
import { gateway, useGateway, useGatewayRefresh } from './api'
import { parameterSchema, parameterValues } from './terminal-parameter-form'
import {
  usePublicationPreview,
  type PublicationDraft,
} from './use-publication-preview'

type Automatic = {
  status: string
  reason?: string
  context_window?: number
  max_output?: number
  reasoning_options?: Schema['PublicationInput']['reasoning_options']
  capabilities?: Partial<Schema['ModelCapabilities']>
  input_modalities?: string[]
  output_modalities?: string[]
  chat_policy?: Schema['ChatPolicy']
  source?: { provider?: string; url?: string; verified_at?: string }
}
type Policy = Partial<Schema['PublicationInput']> & { automatic?: Automatic }
type AccessControls = {
  section?: 'parameters' | 'access'
  onParameters?: () => void
  onPricing?: () => void
  onDirtyChange?: (dirty: boolean) => void
  onSavingChange?: (saving: boolean) => void
}
const audiences = [
  { value: 'administrators', label: '仅管理员' },
  { value: 'organization', label: '全体成员' },
  { value: 'selected', label: '指定成员' },
]
const effortLabels: Record<string, string> = {
  none: '关闭',
  minimal: '最低',
  low: '低',
  medium: '中',
  high: '高',
  xhigh: '很高',
  max: '最高',
}
const modalityLabels: Record<string, string> = { text: '文本', image: '图片' }
const declarationLabels: Record<string, string> = {
  supported: '支持',
  unsupported: '不支持',
}

export function ModelPublication({
  model,
  ...controls
}: { model: string } & AccessControls) {
  const query = useGateway<Policy>(
    '/publication?model=' + encodeURIComponent(model)
  )
  if (query.isPending) return <LoadingState />
  if (query.error)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  const saved = query.data
  return (
    <PublicationForm
      key={JSON.stringify([
        model,
        saved.kind ?? 'chat',
        saved.enabled ?? false,
        saved.audience ?? 'administrators',
        saved.member_ids ?? [],
        saved.chat_policy,
      ])}
      model={model}
      saved={saved}
      {...controls}
    />
  )
}

function PublicationForm({
  model,
  saved,
  section = 'access',
  onParameters,
  onPricing,
  onDirtyChange,
  onSavingChange,
}: { model: string; saved: Policy } & AccessControls) {
  const id = useId()
  const { csrf } = useOrganization()
  const refresh = useGatewayRefresh()
  const [enabled, setEnabled] = useState(saved.enabled ?? false)
  const [audience, setAudience] = useState(saved.audience ?? 'administrators')
  const [members, setMembers] = useState(saved.member_ids ?? [])
  const kind = saved.kind ?? 'chat'
  const formValues = parameterValues({
    ...(saved.capability_mode !== 'manual' &&
    saved.automatic?.status === 'resolved'
      ? saved.automatic
      : {}),
    ...saved,
  })
  const form = useForm({
    resolver: zodResolver(parameterSchema),
    defaultValues: formValues,
    values: formValues,
    resetOptions: { keepDirtyValues: true },
  })
  const mode = saved.capability_mode ?? 'manual'
  const policyDirty = !!form.formState.dirtyFields.chat_policy
  // Access-only edits preserve the stored mode and operation settings exactly.
  const draft: PublicationDraft = {
    model_name: model,
    version: saved.version ?? 0,
    name: saved.name ?? model,
    enabled,
    audience,
    member_ids: audience === 'selected' ? members : [],
    kind,
    capability_mode: saved.capability_mode ?? 'manual',
    context_window: saved.context_window,
    max_output: saved.max_output,
    capabilities: saved.capabilities,
    reasoning_options: saved.reasoning_options,
    chat_policy: policyDirty
      ? chatPolicyInput(form.getValues('chat_policy'))
      : saved.chat_policy,
    retrieval: saved.retrieval,
    image: saved.image,
    speech: saved.speech,
    transcription: saved.transcription,
  }
  const checks = usePublicationPreview(draft)
  const dirty =
    policyDirty ||
    enabled !== (saved.enabled ?? false) ||
    audience !== (saved.audience ?? 'administrators') ||
    (audience === 'selected' &&
      [...members].sort().join(',') !==
        [...(saved.member_ids ?? [])].sort().join(','))
  const save = useMutation({
    mutationFn: () => gateway('/publication', 'PUT', draft, csrf),
    onSuccess: async () => {
      await refresh()
      toast.success('使用设置已保存')
    },
  })
  useEffect(() => {
    onDirtyChange?.(dirty)
    return () => onDirtyChange?.(false)
  }, [dirty, onDirtyChange])
  useEffect(() => {
    onSavingChange?.(save.isPending)
    return () => onSavingChange?.(false)
  }, [save.isPending, onSavingChange])
  const status = checks.query.data?.configuration
  const problems =
    status?.checks.filter((check) => check.status !== 'ready') ?? []
  const detected = status?.automatic?.status
    ? (status.automatic as Automatic)
    : saved.automatic
  const automatic: Automatic | undefined =
    mode === 'manual'
      ? {
          status: 'resolved',
          context_window: draft.context_window ?? undefined,
          max_output: draft.max_output ?? undefined,
          capabilities: draft.capabilities,
          reasoning_options: draft.reasoning_options,
          chat_policy: draft.chat_policy as Schema['ChatPolicy'],
          input_modalities:
            draft.capabilities?.vision === 'supported'
              ? ['text', 'image']
              : ['text'],
          output_modalities: ['text'],
        }
      : detected
  const capabilities = automatic?.capabilities ?? status?.capabilities
  const policy = automatic?.chat_policy ?? status?.chat_policy
  const limits = [
    automatic?.context_window &&
      `上下文 ${automatic.context_window.toLocaleString()} Token`,
    automatic?.max_output &&
      `最大输出 ${automatic.max_output.toLocaleString()} Token`,
  ].filter(Boolean)
  const defaults = [
    policy?.default_max_output &&
      `默认输出 ${policy.default_max_output.toLocaleString()} Token`,
    policy?.default_reasoning_effort &&
      `默认推理 ${effortLabels[policy.default_reasoning_effort] ?? policy.default_reasoning_effort}`,
  ].filter(Boolean)
  const declarations = (
    [
      ['tools', '工具调用'],
      ['structured_output', '结构化输出'],
    ] as const
  ).flatMap(([key, label]) => {
    const declaration = declarationLabels[capabilities?.[key] ?? 'unknown']
    return declaration ? [`${label}：${declaration}`] : []
  })
  const efforts = automatic?.reasoning_options
    ?.flatMap((option) => (option.type === 'effort' ? option.values : []))
    .map((value) => (value === null ? '默认' : (effortLabels[value] ?? value)))
  const hasParameters = Boolean(
    limits.length ||
    defaults.length ||
    declarations.length ||
    efforts?.length ||
    capabilities?.vision === 'supported'
  )
  return (
    <FormProvider {...form}>
      <form
        className='mx-auto flex w-full max-w-3xl flex-col gap-6 py-6'
        onSubmit={form.handleSubmit(
          () => save.mutate(),
          () => onParameters?.()
        )}
      >
        {section === 'access' && (
          <FieldGroup>
            <Field orientation='horizontal' className='justify-between'>
              <FieldLabel htmlFor={`${id}-enabled`}>开放使用</FieldLabel>
              <Switch
                id={`${id}-enabled`}
                aria-label='开放使用'
                checked={enabled}
                onCheckedChange={setEnabled}
              />
            </Field>
            <FieldSet>
              <FieldLegend variant='label' id={`${id}-audience`}>
                使用范围
              </FieldLegend>
              <RadioGroup
                aria-labelledby={`${id}-audience`}
                value={audience}
                onValueChange={setAudience}
                className='gap-3 sm:grid-cols-3'
              >
                {audiences.map((option) => (
                  <Field
                    key={option.value}
                    orientation='horizontal'
                    className='rounded-md border px-3 py-3'
                  >
                    <RadioGroupItem
                      id={`${id}-${option.value}`}
                      value={option.value}
                    />
                    <FieldLabel
                      htmlFor={`${id}-${option.value}`}
                      className='cursor-pointer'
                    >
                      {option.label}
                    </FieldLabel>
                  </Field>
                ))}
              </RadioGroup>
            </FieldSet>
            {audience === 'selected' && (
              <MemberPicker
                value={members}
                onChange={setMembers}
                includeAdministrators
                selectionLabel='选择可使用模型的成员'
              />
            )}
          </FieldGroup>
        )}
        {kind === 'chat' && (section === 'access' || mode === 'auto') && (
          <div className='flex flex-col gap-2 border-t pt-4 text-sm'>
            <div className='flex items-center gap-2'>
              <span className='font-medium'>模型参数</span>
              {section === 'access' && onParameters && (
                <Button
                  type='button'
                  size='sm'
                  variant='link'
                  onClick={onParameters}
                >
                  完善模型资料
                </Button>
              )}
            </div>
            {automatic?.status === 'resolved' && hasParameters ? (
              <div className='text-muted-foreground'>
                {!!limits.length && <p>{limits.join(' · ')}</p>}
                {!!defaults.length && <p>{defaults.join(' · ')}</p>}
                <p>
                  输入：
                  {automatic.input_modalities
                    ?.map((value) => modalityLabels[value] ?? value)
                    .join('、') || '未识别'}{' '}
                  · 输出：
                  {automatic.output_modalities
                    ?.map((value) => modalityLabels[value] ?? value)
                    .join('、') || '未识别'}
                </p>
                {!!declarations.length && <p>{declarations.join(' · ')}</p>}
                {!!efforts?.length && <p>推理档位：{efforts.join('、')}</p>}
                <p className='mt-1 text-xs'>
                  当前对话通道未接入音频、视频输入。
                </p>
                {automatic.source?.url && (
                  <p className='text-xs'>
                    <a
                      href={automatic.source.url}
                      target='_blank'
                      rel='noreferrer'
                      className='underline underline-offset-4'
                    >
                      供应商能力资料
                    </a>
                    {' · 核对日期 '}
                    {automatic.source.verified_at}
                  </p>
                )}
              </div>
            ) : (
              <p className='text-muted-foreground'>暂无模型参数</p>
            )}
          </div>
        )}
        {checks.pending || checks.query.isFetching || checks.query.isPending ? (
          <p role='status' className='text-sm text-muted-foreground'>
            正在检查接入配置…
          </p>
        ) : checks.query.error ? (
          <RequestError
            error={checks.query.error}
            retry={() => void checks.query.refetch()}
          />
        ) : problems.length ? (
          <Alert>
            <AlertTitle>接入配置待完善</AlertTitle>
            <AlertDescription>
              <ul className='flex w-full flex-col gap-2'>
                {problems.map((check) => (
                  <li
                    key={check.key}
                    className='flex flex-wrap items-center justify-between gap-2'
                  >
                    <span>{check.message}</span>
                    {check.action === 'pricing' && onPricing ? (
                      <Button
                        type='button'
                        variant='link'
                        size='sm'
                        onClick={onPricing}
                      >
                        配置价格
                      </Button>
                    ) : check.action === 'parameters' &&
                      onParameters &&
                      section !== 'parameters' ? (
                      <Button
                        type='button'
                        variant='link'
                        size='sm'
                        onClick={onParameters}
                      >
                        完善模型资料
                      </Button>
                    ) : check.action === 'channels' ||
                      check.action === 'quota' ? (
                      <Button asChild variant='link' size='sm'>
                        <a
                          href={
                            check.action === 'channels'
                              ? '/model-channels'
                              : '/quota-policies'
                          }
                          target='_blank'
                          rel='noreferrer'
                        >
                          {check.action === 'channels'
                            ? '配置渠道'
                            : '额度设置'}
                        </a>
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : (
          <p className='flex items-center gap-2 text-sm text-muted-foreground'>
            <CheckCircle2 className='size-4 text-success' />
            接入配置已就绪
          </p>
        )}
        <ChatPolicyFields disabled={save.isPending} />
        {save.error && <RequestError error={save.error} />}
        <div className='sticky bottom-0 flex flex-wrap items-center justify-end gap-3 border-t bg-background py-4'>
          <Button
            disabled={
              save.isPending ||
              (enabled &&
                (checks.pending || checks.query.isFetching || !status?.ready))
            }
          >
            {save.isPending
              ? '保存中…'
              : section === 'parameters'
                ? '保存使用设置'
                : enabled
                  ? saved.enabled
                    ? '保存使用设置'
                    : '保存并开放'
                  : saved.enabled
                    ? '保存并关闭访问'
                    : '保存为未开放'}
          </Button>
        </div>
      </form>
    </FormProvider>
  )
}
