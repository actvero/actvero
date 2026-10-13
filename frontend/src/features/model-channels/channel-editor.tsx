import { useEffect, useRef, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, PlugZap } from 'lucide-react'
import { api, ApiError, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Form } from '@/components/ui/form'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { channelPath } from './api'
import {
  ChannelAdvancedFields,
  ChannelConnectionFields,
} from './channel-fields'
import { channelSchema, modelIds, type ChannelValues } from './channel-form'
import { ChannelModelFields } from './channel-model-fields'
import { useProviderModules, type ProviderModule } from './provider-modules'
import { ProviderPicker } from './provider-picker'
import type { Channel, Detail } from './shared'

type Inspection = Schema['DraftInspectionView']
type Resolved = Schema['ResolvedConnection']
type EditorProps = {
  channel?: Channel
  copyFrom?: Detail
  close: () => void
  saved: (channel: Detail) => void
  restoreFocus?: () => void
}

const operationEndpoints = {
  chat: 'chat_completions',
  embedding: 'embeddings',
  rerank: 'rerank',
  image_generation: 'images',
  speech: 'speech',
} as const

function valuesFor(
  provider: ProviderModule,
  source?: Detail,
  copy = false
): ChannelValues {
  const mode =
    source?.connection.address_mode ??
    (provider.id === 'openai-compatible' ? 'service_root' : 'provider_default')
  return {
    name: copy ? `${source!.name} 副本` : (source?.name ?? provider.name),
    description: source?.description ?? '',
    icon: source?.icon ?? '',
    address_mode: mode,
    base_url: source?.connection.legacy_base_url ?? source?.base_url ?? '',
    service_root: source?.connection.service_root ?? '',
    custom_prefix:
      source?.connection.api_prefix !== null &&
      source?.connection.api_prefix !== undefined,
    api_prefix: source?.connection.api_prefix ?? '',
    auth_mode: source?.auth_mode ?? 'api_key',
    api_key: '',
    timeout_seconds: source?.timeout_seconds ?? 20,
    declared_apis: (source?.declared_apis ??
      provider.default_apis) as ChannelValues['declared_apis'],
    manual_enabled: source?.manual_enabled ?? true,
    automatic_protection: source?.automatic_protection?.enabled ?? true,
    test_upstream_id: source?.test_defaults?.upstream_id ?? '',
    test_operation: source?.test_defaults?.operation ?? '',
    test_stream: source?.test_defaults?.stream ?? false,
    models: source?.models.map(({ id }) => id) ?? [],
    manual_models: '',
  }
}

function address(values: ChannelValues): Schema['ChannelConnectionSettings'] {
  return {
    address_mode: values.address_mode,
    resolver_version: 1,
    ...(values.address_mode === 'service_root'
      ? { service_root: values.service_root.trim() }
      : {}),
    ...(values.address_mode === 'legacy_api_base'
      ? { legacy_base_url: values.base_url.trim() }
      : {}),
    ...(values.address_mode !== 'legacy_api_base' && values.custom_prefix
      ? { api_prefix: values.api_prefix.trim() }
      : {}),
  }
}

function sameAddress(
  left: Schema['ChannelConnectionSettings'],
  right: Schema['ChannelConnectionSettings']
) {
  return (
    left.address_mode === right.address_mode &&
    (left.service_root ?? '') === (right.service_root ?? '') &&
    (left.legacy_base_url ?? '') === (right.legacy_base_url ?? '') &&
    (left.api_prefix ?? null) === (right.api_prefix ?? null)
  )
}

export function ChannelEditor({
  channel,
  copyFrom,
  close,
  saved,
  restoreFocus,
}: EditorProps) {
  const { organization } = useOrganization()
  const [saving, setSaving] = useState(false)
  const providers = useProviderModules()
  const [selected, setSelected] = useState<ProviderModule | null>(null)
  const [draftName, setDraftName] = useState('')
  const requestClose = useRef<(() => void) | null>(null)
  const provider =
    channel || copyFrom
      ? providers.data?.find(
          (item) => item.id === (channel ?? copyFrom)?.provider
        )
      : selected
  const complete =
    channel && 'models' in channel ? (channel as Detail) : undefined
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-channels',
      channel?.id,
      'editor',
    ],
    enabled: !!channel && !complete,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: ({ signal }) =>
      api<Detail>(
        channelPath(channel!.id),
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const initial = complete ?? query.data
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open && !saving) (requestClose.current ?? close)()
      }}
    >
      <SheetContent
        className='w-full gap-0 sm:max-w-6xl'
        aria-describedby={undefined}
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => {
          if (restoreFocus) {
            event.preventDefault()
            restoreFocus()
          }
        }}
      >
        <SheetHeader className='shrink-0 px-4 py-5 sm:px-6'>
          <div className='flex flex-wrap items-center gap-3 pr-6'>
            <SheetTitle>
              {channel ? '编辑渠道' : copyFrom ? '复制渠道配置' : '添加渠道'}
            </SheetTitle>
            {provider && <Badge variant='outline'>{provider.name}</Badge>}
          </div>
        </SheetHeader>
        <Separator />
        {providers.isError ? (
          <div className='p-6'>
            <RequestError
              error={providers.error}
              retry={() => void providers.refetch()}
            />
          </div>
        ) : providers.isPending ? (
          <LoadingState />
        ) : !channel && !provider ? (
          <ProviderPicker
            providers={providers.data}
            select={setSelected}
            close={close}
          />
        ) : !provider ? (
          <div className='p-6'>
            <RequestError error={new Error('此渠道的供应商模块暂不可用')} />
          </div>
        ) : channel && !initial ? (
          query.isError ? (
            <div className='p-6'>
              <RequestError
                error={query.error}
                retry={() => void query.refetch()}
              />
            </div>
          ) : (
            <LoadingState />
          )
        ) : (
          <ChannelForm
            key={initial?.id ?? copyFrom?.id ?? provider.id}
            provider={provider}
            draftName={draftName}
            changeProvider={
              channel || copyFrom
                ? undefined
                : (name) => {
                    setDraftName(name)
                    setSelected(null)
                  }
            }
            channel={initial}
            copyFrom={copyFrom}
            close={close}
            saved={saved}
            setSaving={setSaving}
            registerClose={(handler) => {
              requestClose.current = handler
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}

function ChannelForm({
  provider,
  draftName,
  changeProvider,
  channel,
  copyFrom,
  close,
  saved,
  setSaving,
  registerClose,
}: {
  channel?: Detail
  copyFrom?: Detail
  close: () => void
  saved: (channel: Detail) => void
  setSaving: (saving: boolean) => void
  registerClose: (handler: (() => void) | null) => void
  provider: ProviderModule
  draftName: string
  changeProvider?: (name: string) => void
}) {
  const { csrf } = useOrganization()
  const [current, setCurrent] = useState(channel)
  const [error, setError] = useState<unknown>(null)
  const [inspectionError, setInspectionError] = useState<unknown>(null)
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [preview, setPreview] = useState<Inspection | null>(null)
  const [addressPreview, setAddressPreview] = useState<Resolved | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [inspecting, setInspecting] = useState<'check' | 'discover' | null>(
    null
  )
  const [tab, setTab] = useState('connection')
  const [switching, setSwitching] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [latest, setLatest] = useState<Detail | null>(null)
  const [receiptUnknown, setReceiptUnknown] = useState(false)
  const [receiptMissing, setReceiptMissing] = useState(false)
  const [receiptBusy, setReceiptBusy] = useState(false)
  const [forbidden, setForbidden] = useState(false)
  const [requestId] = useState(() => crypto.randomUUID())
  const activeRequest = useRef<AbortController | null>(null)
  const operation = useRef(false)
  const defaults = valuesFor(provider, channel ?? copyFrom, !!copyFrom)
  if (!channel && !copyFrom && draftName) defaults.name = draftName
  const form = useForm<ChannelValues>({
    resolver: zodResolver(channelSchema),
    defaultValues: defaults,
  })
  const watched = useWatch({ control: form.control })
  const models = watched.models ?? []
  const manualModels = watched.manual_models ?? ''
  const selectedCount = new Set([...models, ...modelIds(manualModels)]).size
  const currentAddress = address(form.getValues())
  const needsKey = !!(
    !current?.credential_configured ||
    !current ||
    !sameAddress(currentAddress, current.connection)
  )
  const pending =
    form.formState.isSubmitting ||
    inspecting !== null ||
    previewing ||
    receiptBusy ||
    receiptUnknown ||
    forbidden
  useEffect(() => {
    form.setFocus('name')
    return () => activeRequest.current?.abort()
  }, [form])
  useEffect(() => {
    registerClose(() => {
      if (form.formState.isSubmitting || receiptUnknown || receiptBusy) return
      activeRequest.current?.abort()
      setInspecting(null)
      setPreviewing(false)
      if (form.formState.isDirty) setDiscarding(true)
      else close()
    })
    return () => registerClose(null)
  }, [
    registerClose,
    close,
    form.formState.isDirty,
    form.formState.isSubmitting,
    receiptBusy,
    receiptUnknown,
  ])

  function invalidateInspection() {
    setInspection(null)
    setPreview(null)
    setInspectionError(null)
    setAddressPreview(null)
  }
  function denyIfForbidden(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 403) {
      setForbidden(true)
      form.setValue('api_key', '')
    }
  }
  function connection(values: ChannelValues) {
    return {
      provider: provider.id,
      base_url:
        values.address_mode === 'legacy_api_base'
          ? values.base_url
          : (current?.base_url ?? ''),
      connection: address(values),
      auth_mode: values.auth_mode,
      api_key:
        values.auth_mode === 'api_key' && values.api_key
          ? values.api_key
          : undefined,
      timeout_seconds: values.timeout_seconds,
      declared_apis: values.declared_apis,
    } satisfies Pick<
      Schema['ChannelInput'],
      | 'provider'
      | 'base_url'
      | 'connection'
      | 'auth_mode'
      | 'api_key'
      | 'timeout_seconds'
      | 'declared_apis'
    >
  }
  function checkKey(values: ChannelValues) {
    if (values.auth_mode === 'api_key' && needsKey && !values.api_key) {
      form.setError('api_key', {
        message: '请填写 API Key；修改地址时需要重新填写',
      })
      setTab('connection')
      return false
    }
    return true
  }
  async function resolvePreview() {
    if (operation.current) return
    if (!(await form.trigger(['base_url', 'service_root', 'api_prefix']))) {
      setTab(
        form.getFieldState('api_prefix').invalid ? 'advanced' : 'connection'
      )
      return
    }
    setPreviewing(true)
    setAddressPreview(null)
    setInspectionError(null)
    const controller = new AbortController()
    activeRequest.current = controller
    try {
      const result = await api<Resolved>(
        '/llm/channel-addresses/resolve',
        'POST',
        {
          provider: provider.id,
          connection: address(form.getValues()),
          operations: ['chat'],
          stream: false,
        } satisfies Schema['ChannelAddressInput'],
        csrf,
        controller.signal
      )
      if (!controller.signal.aborted) setAddressPreview(result)
    } catch (cause) {
      if (!controller.signal.aborted) {
        denyIfForbidden(cause)
        setInspectionError(cause)
      }
    } finally {
      if (!controller.signal.aborted) setPreviewing(false)
    }
  }
  async function inspect(discover: boolean) {
    if (operation.current || !provider.model_discovery) return
    if (
      !(await form.trigger([
        'base_url',
        'service_root',
        'api_prefix',
        'auth_mode',
        'api_key',
        'timeout_seconds',
      ]))
    ) {
      setTab(
        form.getFieldState('timeout_seconds').invalid ||
          form.getFieldState('api_prefix').invalid
          ? 'advanced'
          : 'connection'
      )
      return
    }
    const values = form.getValues()
    if (!checkKey(values) || operation.current) return
    operation.current = true
    const controller = new AbortController()
    activeRequest.current = controller
    setInspectionError(null)
    setInspecting(discover ? 'discover' : 'check')
    try {
      const result = await api<Inspection>(
        '/llm/channel-drafts/inspect',
        'POST',
        {
          ...connection(values),
          discover,
          ...(current
            ? { channel_id: current.id, version: current.version }
            : {}),
        } satisfies Schema['DraftInspectionInput'],
        csrf,
        controller.signal
      )
      if (controller.signal.aborted) return
      setInspection(result)
      if (!result.ok) {
        setInspectionError(new Error(result.message))
        if (discover) setPreview(null)
      } else if (discover) setPreview(result)
    } catch (cause) {
      if (!controller.signal.aborted) {
        denyIfForbidden(cause)
        setInspection(null)
        if (discover) setPreview(null)
        setInspectionError(cause)
      }
    } finally {
      if (!controller.signal.aborted) setInspecting(null)
      operation.current = false
    }
  }
  async function submit(values: ChannelValues, retry = false) {
    if (
      operation.current ||
      forbidden ||
      conflict ||
      (receiptUnknown && !retry) ||
      !checkKey(values)
    )
      return
    const selected = [
      ...new Set([...values.models, ...modelIds(values.manual_models)]),
    ]
    if (selected.length > 1000) {
      form.setError('models', { message: '每个渠道最多登记 1000 个模型' })
      setTab('connection')
      return
    }
    const testEndpoint = values.test_operation
      ? operationEndpoints[values.test_operation]
      : null
    const testReady =
      !values.test_upstream_id ||
      (selected.includes(values.test_upstream_id) &&
        !!values.test_operation &&
        provider.test_operations.includes(values.test_operation) &&
        (values.test_operation === 'speech' ||
          (!!testEndpoint &&
            values.declared_apis.includes(
              testEndpoint as ChannelValues['declared_apis'][number]
            ))) &&
        (!values.test_stream || values.test_operation === 'chat'))
    if (!testReady) {
      form.setError('test_upstream_id', {
        message: '请重新选择已登记模型和测试接口，或清除默认',
      })
      setTab('advanced')
      return
    }
    if (!values.test_upstream_id && values.test_operation) {
      form.setError('test_upstream_id', {
        message: '请先选择默认测试模型或清除默认',
      })
      setTab('advanced')
      return
    }
    const endpoint = testEndpoint
    const body: Schema['ChannelInput'] = {
      ...connection(values),
      name: values.name,
      description: values.description,
      icon: values.icon,
      manual_enabled: values.manual_enabled,
      automatic_protection: { enabled: values.automatic_protection },
      test_defaults:
        values.test_upstream_id && values.test_operation && endpoint
          ? {
              upstream_id: values.test_upstream_id,
              operation: values.test_operation,
              endpoint,
              stream: values.test_stream,
            }
          : null,
      models: selected.map((id) => ({ id })),
      ...(!current ? { request_id: requestId } : {}),
    }
    operation.current = true
    setSaving(true)
    setError(null)
    try {
      const result = await api<Detail>(
        current ? channelPath(current.id) : '/llm/channels',
        current ? 'PUT' : 'POST',
        current ? { ...body, version: current.version } : body,
        csrf
      )
      form.resetField('api_key')
      saved(result)
    } catch (cause) {
      denyIfForbidden(cause)
      if (
        cause instanceof ApiError &&
        cause.status === 409 &&
        !cause.references?.length &&
        current
      ) {
        setConflict(true)
      } else if (
        !current &&
        (!(cause instanceof ApiError) || cause.status >= 500)
      ) {
        setReceiptUnknown(true)
        setReceiptMissing(false)
      }
      setError(cause)
    } finally {
      operation.current = false
      setSaving(false)
    }
  }
  async function queryReceipt() {
    setReceiptBusy(true)
    setError(null)
    try {
      let receipt: Schema['MutationReceiptView']
      try {
        receipt = await api<Schema['MutationReceiptView']>(
          `/llm/mutation-receipts/${requestId}?scope=channel.create`
        )
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404)
          setReceiptMissing(true)
        throw cause
      }
      setReceiptMissing(false)
      const result = await api<Detail>(channelPath(receipt.resource_id))
      form.resetField('api_key')
      saved(result)
    } catch (cause) {
      denyIfForbidden(cause)
      setError(cause)
    } finally {
      setReceiptBusy(false)
    }
  }
  async function loadLatest() {
    if (!current) return
    setReceiptBusy(true)
    try {
      setLatest(await api<Detail>(channelPath(current.id)))
    } catch (cause) {
      setError(cause)
      denyIfForbidden(cause)
    } finally {
      setReceiptBusy(false)
    }
  }
  function adoptLatest() {
    if (!latest) return
    form.reset(valuesFor(provider, latest))
    setCurrent(latest)
    setConflict(false)
    setLatest(null)
    setError(null)
    invalidateInspection()
  }

  return (
    <Form {...form}>
      <form
        className='flex min-h-0 flex-1 flex-col'
        onSubmit={(event) =>
          void form.handleSubmit(
            (values) => submit(values),
            (errors) =>
              setTab(
                errors.name ||
                  errors.base_url ||
                  errors.service_root ||
                  errors.api_key ||
                  errors.models ||
                  errors.manual_models
                  ? 'connection'
                  : 'advanced'
              )
          )(event)
        }
      >
        <div className='min-h-0 flex-1 overflow-y-auto p-4 sm:p-6'>
          <Tabs value={tab} onValueChange={setTab} className='min-w-0 gap-6'>
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <TabsList className='max-w-full overflow-x-auto'>
                <TabsTrigger value='connection'>连接与模型</TabsTrigger>
                <TabsTrigger value='advanced'>高级设置</TabsTrigger>
              </TabsList>
              {changeProvider && (
                <Button
                  type='button'
                  variant='outline'
                  disabled={pending}
                  onClick={() => setSwitching(true)}
                >
                  更换供应商
                </Button>
              )}
            </div>
            {!provider.member_inference && (
              <Alert>
                <AlertTitle>可配置与测试</AlertTitle>
                <AlertDescription>
                  此供应商当前支持配置与管理员诊断，暂未开放成员调用。
                  {provider.model_discovery
                    ? '可读取模型目录。'
                    : '模型需要手动登记。'}
                </AlertDescription>
              </Alert>
            )}
            <TabsContent value='connection'>
              <fieldset
                disabled={pending}
                className='grid min-w-0 items-start gap-6 lg:grid-cols-2'
              >
                <div className='flex min-w-0 flex-col gap-4'>
                  <ChannelConnectionFields
                    provider={provider}
                    pending={pending}
                    needsKey={needsKey}
                    invalidate={invalidateInspection}
                    preview={() => void resolvePreview()}
                    previewPending={previewing}
                    showAdvanced={() => setTab('advanced')}
                  />
                  {addressPreview && (
                    <Alert>
                      <AlertTitle>最终地址预览</AlertTitle>
                      <AlertDescription>
                        <div className='flex min-w-0 flex-col gap-2 break-all'>
                          <span>
                            {addressPreview.directory_url
                              ? `目录：${addressPreview.directory_method} ${addressPreview.directory_url}`
                              : provider.reference_catalog
                                ? '模型目录：此套餐不提供目录，可搜索参考模型或输入实际模型 ID'
                                : '模型目录：当前预设暂未接入，请手动登记模型 ID'}
                          </span>
                          {addressPreview.operation_targets.map((target) => (
                            <span key={target.operation}>
                              {target.operation}：{target.method} {target.url}
                            </span>
                          ))}
                        </div>
                      </AlertDescription>
                    </Alert>
                  )}
                  {provider.model_discovery && (
                    <Button
                      type='button'
                      variant='outline'
                      className='self-start'
                      disabled={pending}
                      onClick={() => void inspect(false)}
                    >
                      <PlugZap />
                      {inspecting === 'check' ? '正在检查…' : '检查目录连接'}
                    </Button>
                  )}
                  {!!inspectionError && (
                    <RequestError error={inspectionError} />
                  )}
                  {inspection?.ok && !inspectionError && (
                    <Alert>
                      <CheckCircle2 />
                      <AlertTitle>目录读取成功</AlertTitle>
                      <AlertDescription>
                        {inspection.message}；不代表推理或成员权限已就绪。
                      </AlertDescription>
                    </Alert>
                  )}
                </div>
                <ChannelModelFields
                  modelDiscovery={provider.model_discovery}
                  referenceCatalog={provider.reference_catalog}
                  candidates={
                    preview?.candidates?.map((model) => model.id) ?? []
                  }
                  discovered={preview !== null}
                  partial={preview?.partial ?? false}
                  pending={pending}
                  discovering={inspecting === 'discover'}
                  discover={() => void inspect(true)}
                />
              </fieldset>
            </TabsContent>
            <TabsContent value='advanced'>
              <fieldset disabled={pending}>
                <ChannelAdvancedFields
                  provider={provider}
                  pending={pending}
                  invalidate={invalidateInspection}
                />
              </fieldset>
            </TabsContent>
          </Tabs>
        </div>
        <Separator />
        <SheetFooter className='shrink-0 flex-row flex-wrap items-center justify-between px-4 sm:px-6'>
          {!!error && (
            <div className='w-full'>
              <RequestError error={error} />
            </div>
          )}
          {error instanceof ApiError &&
            error.status === 409 &&
            !!error.references?.length && (
              <Alert variant='destructive' className='w-full'>
                <AlertTitle>库存仍被模型绑定使用</AlertTitle>
                <AlertDescription>
                  {error.references
                    .map(
                      (reference) =>
                        `${reference.model_name}（${reference.operation}）`
                    )
                    .join('、')}
                  。请先在模型配置中停用绑定，再移除来源。
                </AlertDescription>
              </Alert>
            )}
          {forbidden && (
            <Alert variant='destructive' className='w-full'>
              <AlertTitle>管理权限已变化</AlertTitle>
              <AlertDescription>
                密钥输入已清空。请返回渠道列表。
              </AlertDescription>
            </Alert>
          )}
          {conflict && (
            <Alert className='w-full'>
              <AlertTitle>配置已被其他管理员修改</AlertTitle>
              <AlertDescription>
                <div className='flex flex-col gap-2'>
                  <p>你的草稿仍在本页，未自动重试。</p>
                  {latest ? (
                    <>
                      <p>
                        当前服务器：{latest.name} ·{' '}
                        {latest.connection.address_mode} ·{' '}
                        {latest.models.length} 个模型；本地草稿：
                        {form.getValues('name')} ·{' '}
                        {form.getValues('address_mode')} · {selectedCount}{' '}
                        个模型。
                      </p>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        className='self-start'
                        onClick={adoptLatest}
                      >
                        舍弃草稿，采用最新配置
                      </Button>
                    </>
                  ) : (
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      className='self-start'
                      onClick={() => void loadLatest()}
                    >
                      加载最新并比较
                    </Button>
                  )}
                </div>
              </AlertDescription>
            </Alert>
          )}
          {receiptUnknown && (
            <Alert className='w-full'>
              <AlertTitle>尚未确认保存结果</AlertTitle>
              <AlertDescription>
                <div className='flex flex-col gap-2'>
                  <p>
                    网络中断，服务端可能已经保存。请记录请求标识：{requestId}
                  </p>
                  <div className='flex flex-wrap gap-2'>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      disabled={receiptBusy}
                      onClick={() => void queryReceipt()}
                    >
                      查询保存结果
                    </Button>
                    {receiptMissing && (
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        disabled={receiptBusy}
                        onClick={() => void submit(form.getValues(), true)}
                      >
                        按原请求重试
                      </Button>
                    )}
                    <Button
                      type='button'
                      variant='ghost'
                      size='sm'
                      disabled={receiptBusy}
                      onClick={close}
                    >
                      稍后查看
                    </Button>
                  </div>
                </div>
              </AlertDescription>
            </Alert>
          )}
          <p className='text-sm text-muted-foreground'>
            已选择 {selectedCount} 个模型
          </p>
          <div className='flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              disabled={form.formState.isSubmitting || receiptBusy}
              onClick={() => {
                if (receiptUnknown) return
                activeRequest.current?.abort()
                setInspecting(null)
                setPreviewing(false)
                if (form.formState.isDirty) setDiscarding(true)
                else close()
              }}
            >
              取消
            </Button>
            <Button disabled={pending || conflict}>
              {form.formState.isSubmitting
                ? '保存中…'
                : current
                  ? '保存渠道'
                  : '保存为新渠道'}
            </Button>
          </div>
        </SheetFooter>
      </form>
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title='放弃未保存的修改？'
        desc='本次修改尚未保存。'
        confirmText='放弃修改并返回'
        cancelBtnText='继续编辑'
        destructive
        handleConfirm={close}
      />
      <ConfirmDialog
        open={switching}
        onOpenChange={setSwitching}
        title='更换供应商'
        desc='保留渠道名称，清空当前地址、密钥、库存和测试默认后返回供应商列表。'
        confirmText='更换'
        cancelBtnText='取消'
        handleConfirm={() => changeProvider?.(form.getValues('name'))}
      />
    </Form>
  )
}
