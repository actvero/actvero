import { useEffect, useId, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import type { Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
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
import { gateway, useGateway, useGatewayRefresh } from './api'
import {
  usePublicationPreview,
  type PublicationDraft,
} from './use-publication-preview'

type Automatic = {
  status: string
  reason?: string
  context_window?: number
  max_output?: number
  reasoning_options?: Schema['ReasoningEffort'][]
  capabilities?: Partial<Schema['ModelCapabilities']>
  input_modalities?: string[]
  output_modalities?: string[]
  chat_policy?: Schema['ChatPolicy']
  source?: { provider?: string; url?: string; verified_at?: string }
}
type Policy = Partial<Schema['PublicationInput']> & { automatic?: Automatic }
type AccessControls = {
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
  unknown: '未识别',
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
  return (
    <PublicationForm
      key={`${model}:${query.data.version ?? 0}`}
      model={model}
      saved={query.data}
      {...controls}
    />
  )
}

function PublicationForm({
  model,
  saved,
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
  // Access edits retain existing operation settings. Chat controls resolve from the live mapping.
  const draft: PublicationDraft = {
    model_name: model,
    version: saved.version ?? 0,
    name: saved.name ?? model,
    enabled,
    audience,
    member_ids: audience === 'selected' ? members : [],
    kind,
    capability_mode:
      kind === 'chat' ? 'auto' : (saved.capability_mode ?? 'auto'),
    context_window: saved.context_window,
    max_output: saved.max_output,
    capabilities: saved.capabilities,
    reasoning_options: saved.reasoning_options,
    chat_policy: saved.chat_policy,
    retrieval: saved.retrieval,
    image: saved.image,
    speech: saved.speech,
    transcription: saved.transcription,
  }
  const checks = usePublicationPreview(draft)
  const dirty =
    enabled !== (saved.enabled ?? false) ||
    audience !== (saved.audience ?? 'administrators') ||
    (audience === 'selected' &&
      [...members].sort().join(',') !==
        [...(saved.member_ids ?? [])].sort().join(','))
  const save = useMutation({
    mutationFn: () => gateway('/publication', 'PUT', draft, csrf),
    onSuccess: async () => {
      await refresh()
      toast.success('访问设置已保存')
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
  const automatic = status?.automatic?.status
    ? (status.automatic as Automatic)
    : saved.automatic
  const capabilities = automatic?.capabilities ?? status?.capabilities
  const policy = automatic?.chat_policy ?? status?.chat_policy
  return (
    <form
      className='mx-auto flex w-full max-w-3xl flex-col gap-6 py-6'
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate()
      }}
    >
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
      {kind === 'chat' && (
        <div className='flex flex-col gap-2 border-t pt-4 text-sm'>
          <div className='flex items-center gap-2'>
            <span className='font-medium'>模型参数</span>
            <Badge variant='secondary'>自动识别</Badge>
          </div>
          {automatic?.status === 'resolved' ? (
            <div className='text-muted-foreground'>
              <p>
                上下文 {automatic.context_window?.toLocaleString()} · 最大输出{' '}
                {automatic.max_output?.toLocaleString()} Token
              </p>
              <p>
                默认输出{' '}
                {policy?.default_max_output?.toLocaleString() ?? '未指定'} Token
                · 默认推理{' '}
                {policy?.default_reasoning_effort
                  ? (effortLabels[policy.default_reasoning_effort] ??
                    policy.default_reasoning_effort)
                  : automatic.reasoning_options?.length
                    ? '供应商默认'
                    : '无'}
              </p>
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
              <p>
                {[
                  ['tools', '工具调用'],
                  ['streaming', '流式输出'],
                  ['structured_output', '结构化输出'],
                ]
                  .map(
                    ([key, label]) =>
                      `${label}：${declarationLabels[capabilities?.[key as keyof Schema['ModelCapabilities']] ?? 'unknown']}`
                  )
                  .join(' · ')}
              </p>
              <p>
                推理档位：
                {automatic.reasoning_options
                  ?.flatMap((option) => option.values)
                  .map((value) =>
                    value === null
                      ? '默认'
                      : (effortLabels[String(value)] ?? String(value))
                  )
                  .join('、') || '无'}
              </p>
              <p className='mt-1 text-xs'>当前对话通道未接入音频、视频输入。</p>
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
            <p className='text-muted-foreground'>
              参数尚未识别，暂不能开放使用。
            </p>
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
                        {check.action === 'channels' ? '配置渠道' : '额度设置'}
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
      {save.error && <RequestError error={save.error} />}
      <div className='sticky bottom-0 flex justify-end border-t bg-background py-4'>
        <Button
          disabled={
            save.isPending ||
            (enabled &&
              (checks.pending || checks.query.isFetching || !status?.ready))
          }
        >
          {save.isPending
            ? '保存中…'
            : enabled
              ? saved.enabled
                ? '保存访问设置'
                : '保存并开放'
              : saved.enabled
                ? '保存并关闭访问'
                : '保存为未开放'}
        </Button>
      </div>
    </form>
  )
}
