import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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

export function ModelCreate({
  close,
  saved,
  restoreFocus,
}: {
  close: () => void
  saved: (model: Model) => void
  restoreFocus?: () => void
}) {
  const { organization } = useOrganization()
  const [sourceMode, setSourceMode] = useState(false)
  const [source, setSource] = useState<ChannelModelSource | null>(null)
  const [pickerTouched, setPickerTouched] = useState(false)
  const [selectedKind, setSelectedKind] = useState<OperationKind | ''>('')
  const [draft, setDraft] = useState<ModelValues | null>(null)
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
  const kind = selectedKind || hint.data?.kind || ''
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
  if (!sourceMode)
    return (
      <ModelEditor
        initialValues={values()}
        initialWithoutOperation
        onQuickImport={() => setSourceMode(true)}
        close={close}
        saved={saved}
        restoreFocus={restoreFocus}
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
          <Button
            variant='ghost'
            className='self-start'
            onClick={() => setSourceMode(false)}
          >
            返回登记模型
          </Button>
          <ChannelModelPicker
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
                <Label htmlFor='source-kind'>接口类型</Label>
                <Select
                  value={kind}
                  onValueChange={(value) =>
                    setSelectedKind(value as OperationKind)
                  }
                >
                  <SelectTrigger id='source-kind' className='w-full'>
                    <SelectValue placeholder='选择模型支持的接口' />
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
                  {hint.data.source === 'litellm'
                    ? 'SDK 资料仅供参考，请按上游实际接口确认；不会自动开放调用或配置价格。'
                    : '未识别接口类型，请按上游模型资料选择；不会自动开放调用或配置价格。'}
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
