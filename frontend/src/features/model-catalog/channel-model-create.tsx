import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ChannelEditor } from '@/features/model-channels/channel-editor'
import {
  ChannelModelPicker,
  type ChannelModelSource,
} from './channel-model-picker'
import { ModelEditor } from './model-editor'
import {
  kinds,
  priceValues,
  values,
  type Model,
  type ModelValues,
  type OperationKind,
} from './model-form'
import { ModelImport } from './model-import'

export function ChannelModelCreate({
  close,
  saved,
  restoreFocus,
  initialChannel,
  initialUpstream,
}: {
  close: () => void
  saved: (model: Model) => void
  restoreFocus?: () => void
  initialChannel?: Schema['ChannelDetail']
  initialUpstream?: string
}) {
  const { organization } = useOrganization()
  const client = useQueryClient()
  const [channel, setChannel] = useState(initialChannel)
  const [editingChannel, setEditingChannel] = useState<
    Schema['ChannelDetail'] | 'new' | null
  >(null)
  const [source, setSource] = useState<ChannelModelSource | null>(
    initialChannel && initialUpstream
      ? { channel: initialChannel, upstream: initialUpstream }
      : null
  )
  const [pickerTouched, setPickerTouched] = useState(false)
  const [selectedKind, setSelectedKind] = useState<OperationKind | ''>('')
  const [draft, setDraft] = useState<ModelValues | null>(null)
  const [batch, setBatch] = useState(false)
  const [imported, setImported] = useState<Model | null>(null)
  const [discard, setDiscard] = useState(false)
  const hint = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-hint',
      source?.channel.id,
      source?.channel.version,
      source?.upstream,
    ],
    enabled: !!source,
    queryFn: ({ signal }) =>
      api<Schema['ModelHint']>(
        `/llm/channels/${source!.channel.id}/model-hint?${new URLSearchParams({ model_id: source!.upstream })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const kind =
    selectedKind ||
    hint.data?.kind ||
    (hint.data?.available_kinds.length === 1
      ? hint.data.available_kinds[0]
      : '')
  const unsupported = !!hint.data?.mode && !hint.data.kind
  const canContinue =
    source &&
    !hint.isFetching &&
    !hint.isError &&
    !unsupported &&
    kind &&
    hint.data?.available_kinds.includes(kind)
  function requestClose() {
    if (source || pickerTouched) setDiscard(true)
    else close()
  }
  if (imported)
    return (
      <ModelEditor
        model={imported}
        close={close}
        saved={saved}
        restoreFocus={restoreFocus}
      />
    )
  if (batch)
    return (
      <ModelImport
        initialSource={source?.channel ?? channel}
        close={() => setBatch(false)}
        configure={(model) => {
          setImported(model)
          setBatch(false)
        }}
      />
    )
  if (editingChannel)
    return (
      <ChannelEditor
        channel={editingChannel === 'new' ? undefined : editingChannel}
        close={() => setEditingChannel(null)}
        saved={(created) => {
          void client.invalidateQueries({
            queryKey: [
              'organization',
              organization.tenant_id,
              'model-channels',
            ],
          })
          setChannel(created)
          setSource(null)
          setSelectedKind('')
          setEditingChannel(null)
        }}
      />
    )
  if (draft)
    return (
      <ModelEditor
        initialValues={draft}
        initialNames={
          source ? { [source.channel.id]: source.channel.name } : {}
        }
        close={close}
        saved={saved}
        restoreFocus={restoreFocus}
      />
    )
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) requestClose()
      }}
    >
      <SheetContent
        className='w-full gap-0 sm:max-w-2xl'
        aria-describedby={undefined}
        onCloseAutoFocus={
          restoreFocus
            ? (event) => {
                event.preventDefault()
                restoreFocus()
              }
            : undefined
        }
      >
        <SheetHeader className='px-4 pr-12 sm:px-6'>
          <SheetTitle>添加模型</SheetTitle>
          <p className='text-sm text-muted-foreground'>
            1 选择来源 → 2 核对参数与价格 → 3 启用
          </p>
        </SheetHeader>
        <ConfirmDialog
          open={discard}
          onOpenChange={setDiscard}
          title='放弃模型草稿？'
          desc='未保存的模型资料、渠道和接口草稿会丢失。'
          cancelBtnText='继续配置'
          confirmText='放弃草稿'
          destructive
          handleConfirm={() => {
            setDiscard(false)
            close()
          }}
        />
        <Separator />
        <div className='flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4 sm:p-6'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <p className='text-sm text-muted-foreground'>
              从渠道选择模型，自动填写名称并关联调用来源。
            </p>
            <Button variant='outline' onClick={() => setEditingChannel('new')}>
              添加新渠道
            </Button>
            <Button variant='ghost' onClick={() => setBatch(true)}>
              批量登记模型
            </Button>
          </div>
          <ChannelModelPicker
            key={channel?.id + ':' + channel?.version}
            initialChannel={channel}
            initialUpstream={source?.upstream}
            editChannel={setEditingChannel}
            onChange={(selected) => {
              setPickerTouched(true)
              setSource(selected)
              setSelectedKind('')
            }}
          />
          {source &&
            (hint.isPending || hint.isFetching ? (
              <LoadingState />
            ) : hint.isError ? (
              <RequestError
                error={hint.error}
                retry={() => void hint.refetch()}
              />
            ) : unsupported ? (
              <p role='status' className='text-sm text-muted-foreground'>
                此模型的接口暂不可用。
              </p>
            ) : !hint.data.available_kinds.length ? (
              <p role='status' className='text-sm text-muted-foreground'>
                请先在渠道设置中配置支持的接口。
              </p>
            ) : (
              <div className='flex flex-col gap-2'>
                <Label htmlFor='source-kind'>模型用途</Label>
                <Select
                  value={kind}
                  onValueChange={(value) =>
                    setSelectedKind(value as OperationKind)
                  }
                >
                  <SelectTrigger id='source-kind' className='w-full'>
                    <SelectValue placeholder='选择模型要完成的任务' />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {hint.data.available_kinds.map((value) => (
                        <SelectItem key={value} value={value}>
                          {kinds[value]}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <p className='text-sm text-muted-foreground'>
                  {hint.data.source !== 'unknown'
                    ? '已根据模型资料识别用途，下一步会补全已知的参数。对话协议沿用渠道配置。'
                    : hint.data.available_kinds.length === 1
                      ? '此渠道目前仅开放此用途，已为你选好。参数仍需按上游资料核对。'
                      : '暂未识别用途，请按任务选择：对话、文本向量、重排、图片或语音。对话协议沿用渠道配置。'}
                </p>
              </div>
            ))}
        </div>
        <Separator />
        <SheetFooter className='flex-row justify-end px-4 sm:px-6'>
          <Button variant='outline' onClick={requestClose}>
            取消
          </Button>
          <Button
            disabled={!canContinue}
            onClick={() => {
              if (!canContinue) return
              const initial = values()
              setDraft({
                ...initial,
                kind,
                name: source.upstream.slice(0, 100),
                slug: source.upstream,
                context_window: hint.data?.context_window
                  ? String(hint.data.context_window)
                  : '',
                max_output: hint.data?.max_output
                  ? String(hint.data.max_output)
                  : '',
                reference: {
                  provider: source.channel.provider,
                  model_id: source.upstream,
                },
                access: {
                  ...initial.access,
                  channel_id: source.channel.id,
                  upstream_id: source.upstream,
                },
                bindings: [
                  {
                    channel_id: source.channel.id,
                    upstream_id: source.upstream,
                    price: priceValues(),
                    enabled: false,
                    priority: '0',
                    weight: '100',
                    compatibility_key: '',
                    chat_options: {
                      reasoning_format: 'openai',
                      output_parameter: 'max_completion_tokens',
                    },
                  },
                ],
              })
            }}
          >
            下一步
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
