import { useRef, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { api, ApiError, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CollapsibleSection } from '@/components/ui/collapsible'
import { Form } from '@/components/ui/form'
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
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { BindingFields } from './binding-fields'
import { activationDraft, issueTab } from './model-activation'
import { ModelEndpointsPanel } from './model-endpoints'
import { ModelFields } from './model-fields'
import {
  modelInput,
  forKind,
  priceInput,
  kinds,
  operationDrafts,
  operationModel,
  operationsInput,
  shareModelFields,
  type OperationKind,
  modelSchema,
  values,
  type Model,
  type ModelValues,
} from './model-form'
import { ModelReadiness } from './model-readiness'
import { PriceFields } from './price-fields'
import { ReferenceSnapshots } from './reference-snapshots'
import { AccessFields } from './retrieval-fields'

function compareDrafts(
  current: ModelValues,
  drafts: ModelValues[],
  server: Model
) {
  const local = drafts.map((draft) =>
    draft.kind === current.kind ? current : shareModelFields(draft, current)
  )
  const remote = operationDrafts(server)
  const rows: [string, string, string][] = [
    ['展示名称', current.name, server.name],
    ['技术名称', current.slug, server.slug],
    [
      '显示排序',
      current.display_order,
      String((server as Model & { display_order?: number }).display_order ?? 0),
    ],
    [
      '公开报价参考',
      JSON.stringify(current.quote_snapshots),
      JSON.stringify(server.quote_snapshots ?? []),
    ],
    ['开发方', current.vendor, server.vendor ?? ''],
    ['说明', current.description, server.description ?? ''],
    [
      '图标',
      JSON.stringify([current.icon_key, !!current.icon]),
      JSON.stringify([server.icon_key, !!server.icon]),
    ],
    [
      '资料参考',
      JSON.stringify(current.reference),
      JSON.stringify(server.reference),
    ],
    [
      '成员范围',
      JSON.stringify([current.access.audience, current.access.member_ids]),
      JSON.stringify([server.access?.audience, server.access?.member_ids]),
    ],
  ]
  for (const [kind, label] of Object.entries(kinds)) {
    const draft = local.find((item) => item.kind === kind)
    const saved = remote.find((item) => item.kind === kind)
    if (!draft || !saved) {
      if (draft || saved)
        rows.push([
          `${label}接口`,
          draft ? '已配置' : '未配置',
          saved ? '已配置' : '未配置',
        ])
      continue
    }
    rows.push(
      [
        `${label}开放`,
        String(draft.operation_enabled),
        String(saved.operation_enabled),
      ],
      [
        `${label}上下文与输出上限`,
        JSON.stringify([draft.context_window, draft.max_output]),
        JSON.stringify([saved.context_window, saved.max_output]),
      ],
      [
        `${label}能力声明`,
        JSON.stringify([draft.capabilities, draft.reasoning]),
        JSON.stringify([saved.capabilities, saved.reasoning]),
      ],
      [
        `${label}向量/重排参数`,
        JSON.stringify(draft.retrieval),
        JSON.stringify(saved.retrieval),
      ],
      [
        `${label}图片参数`,
        JSON.stringify(draft.image),
        JSON.stringify(saved.image),
      ],
      [
        `${label}调用目标`,
        JSON.stringify(draft.access),
        JSON.stringify(saved.access),
      ],
      [
        `${label}渠道关联与采购价`,
        JSON.stringify(
          draft.bindings.map((item) => [
            item.binding_id,
            item.channel_id,
            item.upstream_id,
            item.enabled,
            item.price,
          ])
        ),
        JSON.stringify(
          saved.bindings.map((item) => [
            item.binding_id,
            item.channel_id,
            item.upstream_id,
            item.enabled,
            item.price,
          ])
        ),
      ],
      [
        `${label}路由`,
        JSON.stringify(draft.routing),
        JSON.stringify(saved.routing),
      ],
      [
        `${label}价格`,
        JSON.stringify(draft.budget_price),
        JSON.stringify(saved.budget_price),
      ]
    )
  }
  return rows.filter(([, draft, saved]) => draft !== saved)
}

export function ModelEditor({
  model,
  initialValues,
  independentCreation = false,
  initialNames,
  close,
  saved,
  restoreFocus,
}: {
  model?: Model
  initialValues?: ModelValues
  independentCreation?: boolean
  initialNames?: Record<string, string>
  close: () => void
  saved: (model: Model) => void
  restoreFocus?: () => void
}) {
  const { csrf } = useOrganization()
  const [currentModel, setCurrentModel] = useState(model)
  const [drafts, setDrafts] = useState(() =>
    initialValues
      ? [initialValues]
      : model
        ? operationDrafts(model)
        : [values()]
  )
  const initial = drafts[0] ?? { ...values(model), operation_enabled: false }
  const form = useForm<ModelValues>({
    resolver: zodResolver(modelSchema),
    defaultValues: initial,
  })
  const currentKind = useWatch({ control: form.control, name: 'kind' })
  const currentBindings = useWatch({ control: form.control, name: 'bindings' })
  const operationEnabled = useWatch({
    control: form.control,
    name: 'operation_enabled',
  })
  const [draftDirty, setDraftDirty] = useState(!!initialValues)
  function changeOperation(kind: OperationKind, add = false) {
    const current = form.getValues()
    if (form.formState.isDirty || add) setDraftDirty(true)
    const updated = drafts.map((d) =>
      d.kind === current.kind ? current : shareModelFields(d, current)
    )
    const target = add
      ? drafts.length === 0 && kind === current.kind
        ? { ...current, operation_enabled: false, bindings: [] }
        : shareModelFields({ ...values(), kind }, current)
      : updated.find((d) => d.kind === kind)!
    setDrafts(add ? [...updated, target] : updated)
    form.reset(target)
    setPriceTarget('budget_price')
    setError(null)
    if (add) setTab('profile')
  }
  // Keep unsaved parameters for each type while creating one independent model.
  const creationDrafts = useRef<Partial<Record<OperationKind, ModelValues>>>({})
  function changeCreationKind(kind: OperationKind) {
    const current = form.getValues()
    creationDrafts.current[current.kind] = structuredClone(current)
    const target = shareModelFields(
      creationDrafts.current[kind] ?? { ...values(), kind },
      current
    )
    setDrafts([target])
    form.reset(target)
    setDraftDirty(true)
    setPriceTarget('budget_price')
    setError(null)
  }
  const [removing, setRemoving] = useState(false)
  const [tab, setTab] = useState('profile')
  const [priceTarget, setPriceTarget] = useState('budget_price')
  const [error, setError] = useState<unknown>(null)
  const [discarding, setDiscarding] = useState(false)
  const [slugConfirm, setSlugConfirm] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [latest, setLatest] = useState<Model | null>(null)
  const [loadingLatest, setLoadingLatest] = useState(false)
  const [forbidden, setForbidden] = useState(false)
  const [names, setNames] = useState<Record<string, string>>(
    () =>
      initialNames ??
      Object.fromEntries(
        (model?.binding_states ?? []).map((b) => [b.channel_id, b.channel_name])
      )
  )
  const [activating, setActivating] = useState(false)
  const [confirmActivation, setConfirmActivation] = useState(false)
  const pending = form.formState.isSubmitting || activating
  const readOnly = !!currentModel?.archived || forbidden || conflict
  const dirty = form.formState.isDirty || draftDirty
  const comparison = latest
    ? compareDrafts(form.getValues(), drafts, latest)
    : []
  function requestClose() {
    if (pending) return
    if (dirty) setDiscarding(true)
    else close()
  }
  async function loadLatest() {
    if (!currentModel) return
    setLoadingLatest(true)
    try {
      setLatest(await api<Model>('/llm/models/' + currentModel.id))
    } catch (cause) {
      setError(cause)
      if (cause instanceof ApiError && cause.status === 403) setForbidden(true)
    } finally {
      setLoadingLatest(false)
    }
  }
  function adoptLatest() {
    if (!latest) return
    const next = operationDrafts(latest)
    setCurrentModel(latest)
    setDrafts(next)
    setNames(
      Object.fromEntries(
        latest.binding_states.map((b) => [b.channel_id, b.channel_name])
      )
    )
    form.reset(next[0] ?? { ...values(latest), operation_enabled: false })
    setDraftDirty(false)
    setTab('profile')
    setConflict(false)
    setLatest(null)
    setError(null)
  }
  async function submit(
    data: ModelValues,
    confirmedSlug = false,
    activate = false
  ) {
    if (readOnly || conflict) return
    if (currentModel && data.slug !== currentModel.slug && !confirmedSlug) {
      setSlugConfirm(true)
      setConfirmActivation(activate)
      return
    }
    setError(null)
    try {
      if (activate) data = activationDraft(data)
      else if (!currentModel)
        data = { ...data, access: { ...data.access, enabled: false } }
      const all = drafts.map((d) =>
        d.kind === data.kind ? data : shareModelFields(d, data)
      )
      for (const draft of all) {
        const parsed = modelSchema.safeParse(draft)
        if (!parsed.success) {
          setDrafts(all)
          setDraftDirty(true)
          form.reset(draft)
          const path = parsed.error.issues[0].path
          setTab(issueTab(path))
          setPriceTarget(
            path[0] === 'bindings' && path.includes('price')
              ? `bindings.${String(path[1])}.price`
              : 'budget_price'
          )
          setError(
            new Error(`${kinds[draft.kind]}：${parsed.error.issues[0].message}`)
          )
          await form.trigger()
          return
        }
      }
      if (activate) {
        const active = data.bindings.filter(
          (binding) =>
            binding.enabled &&
            (data.routing.mode === 'auto' ||
              (binding.channel_id === data.access.channel_id &&
                binding.upstream_id === data.access.upstream_id))
        )
        if (!active.length) {
          setTab('bindings')
          throw new Error(
            '请添加调用来源；自动调度需至少选择一个参与调用的来源。'
          )
        }
        const channels = await Promise.all(
          [...new Set(active.map((binding) => binding.channel_id))].map((id) =>
            api<Schema['ChannelDetail']>('/llm/channels/' + id)
          )
        )
        const unavailable = channels.find(
          (channel) => !channel.manual_enabled || channel.archived
        )
        if (unavailable) {
          setTab('bindings')
          throw new Error(
            `渠道“${unavailable.name}”已停用或归档，请在渠道管理中恢复后重试。`
          )
        }
        if (!data.budget_price.enabled) {
          setTab('prices')
          throw new Error(
            '请先配置成员预算价格。未知价格不能按免费处理；如确实免费，请明确填写 0。'
          )
        }
        const pointPrice = await api<Schema['PointPrice']>(
          '/llm/point-prices/preview',
          'POST',
          priceInput(forKind(data.budget_price, data.kind)),
          csrf
        )
        if (pointPrice.status !== 'ready') {
          setTab('prices')
          throw new Error(
            '成员预算价格尚未完成积分换算，请在价格配置中检查币种与组织积分换算。'
          )
        }
      }
      const result = await api<Model>(
        currentModel ? '/llm/models/' + currentModel.id : '/llm/models',
        currentModel ? 'PUT' : 'POST',
        {
          ...modelInput(all[0] ?? data),
          operations: operationsInput(all),
          ...(currentModel ? { version: currentModel.version } : {}),
        },
        csrf
      )
      saved(result)
    } catch (cause) {
      setError(cause)
      if (currentModel && cause instanceof ApiError && cause.status === 409)
        setConflict(true)
      if (cause instanceof ApiError && cause.status === 403) setForbidden(true)
    }
  }
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) requestClose()
      }}
    >
      <SheetContent
        className='w-full gap-0 sm:max-w-6xl'
        aria-describedby={undefined}
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          form.setFocus('name')
        }}
        onCloseAutoFocus={
          restoreFocus
            ? (e) => {
                e.preventDefault()
                restoreFocus()
              }
            : undefined
        }
      >
        <SheetHeader className='shrink-0 px-4 pr-12 sm:px-6'>
          <SheetTitle className='flex flex-wrap items-center gap-2'>
            {currentModel
              ? '编辑模型'
              : independentCreation
                ? '创建模型'
                : '配置模型'}
            {drafts.length === 1 && (
              <Badge variant='secondary'>{kinds[currentKind]}</Badge>
            )}
          </SheetTitle>
        </SheetHeader>
        <ConfirmDialog
          open={discarding}
          onOpenChange={setDiscarding}
          title='放弃未保存的模型修改？'
          desc='当前模型的全部接口草稿都会丢失。'
          cancelBtnText='继续编辑'
          confirmText='放弃修改'
          destructive
          handleConfirm={() => {
            setDiscarding(false)
            close()
          }}
        />
        <ConfirmDialog
          open={slugConfirm}
          onOpenChange={setSlugConfirm}
          title='确认更改技术名称？'
          desc={`原标识 ${currentModel?.slug ?? ''} 将不再匹配此模型；使用旧标识的客户端需要改为 ${form.getValues('slug')}。渠道的上游模型 ID 不会随之更改。`}
          cancelBtnText='返回检查'
          confirmText='确认更改并保存'
          handleConfirm={() => {
            setSlugConfirm(false)
            void form.handleSubmit((data) =>
              submit(data, true, confirmActivation)
            )()
          }}
        />
        <ConfirmDialog
          open={removing}
          onOpenChange={setRemoving}
          title={`移除${kinds[currentKind]}接口配置？`}
          desc='保存后移除此接口的渠道和价格配置，已有调用与用量记录保留。'
          cancelBtnText='取消'
          confirmText='移除'
          destructive
          handleConfirm={() => {
            const current = form.getValues()
            const remaining = drafts
              .filter((d) => d.kind !== currentKind)
              .map((d) => shareModelFields(d, current))
            setDrafts(remaining)
            form.reset(remaining[0] ?? shareModelFields(values(), current))
            setDraftDirty(true)
            setPriceTarget('budget_price')
            setRemoving(false)
          }}
        />
        <Separator />
        <Form {...form}>
          <form
            className='flex min-h-0 flex-1 flex-col'
            onSubmit={(e) =>
              void form.handleSubmit(
                (data) => submit(data),
                (errors) => {
                  setTab(
                    errors.retrieval ||
                      errors.image ||
                      errors.kind ||
                      errors.name ||
                      errors.slug ||
                      errors.context_window ||
                      errors.max_output ||
                      errors.description ||
                      errors.vendor ||
                      errors.capabilities ||
                      errors.reasoning ||
                      errors.chat_policy ||
                      errors.speech ||
                      errors.transcription ||
                      errors.icon
                      ? 'profile'
                      : errors.access?.channel_id ||
                          errors.routing ||
                          (Array.isArray(errors.bindings) &&
                            errors.bindings.some(
                              (b) =>
                                b && Object.keys(b).some((k) => k !== 'price')
                            ))
                        ? 'bindings'
                        : errors.access
                          ? 'access'
                          : 'prices'
                  )
                  const index = Array.isArray(errors.bindings)
                    ? errors.bindings.findIndex((b) => b?.price)
                    : -1
                  setPriceTarget(
                    errors.budget_price || index < 0
                      ? 'budget_price'
                      : `bindings.${index}.price`
                  )
                }
              )(e)
            }
          >
            <div className='min-h-0 flex-1 overflow-y-auto p-4 sm:p-6'>
              {currentModel?.archived && (
                <Alert className='mb-4'>
                  <AlertTitle>模型已归档</AlertTitle>
                  <AlertDescription>
                    当前仅可查看，恢复模型后才能编辑。
                  </AlertDescription>
                </Alert>
              )}
              {forbidden && (
                <Alert className='mb-4' variant='destructive'>
                  <AlertTitle>没有编辑权限</AlertTitle>
                  <AlertDescription>
                    已停止提交。请关闭编辑器并重新检查权限。
                  </AlertDescription>
                </Alert>
              )}
              {conflict && (
                <Alert className='mb-4'>
                  <AlertTitle>服务器配置已变化，草稿仍保留</AlertTitle>
                  <AlertDescription className='flex flex-col gap-3'>
                    <span>
                      为避免覆盖他人修改，当前草稿不能再次提交。请加载服务器版本并比较，再决定是否采用最新配置。
                    </span>
                    <div className='flex flex-wrap gap-2'>
                      <Button
                        type='button'
                        variant='outline'
                        disabled={loadingLatest}
                        onClick={() => void loadLatest()}
                      >
                        {loadingLatest ? '加载中…' : '加载最新并比较'}
                      </Button>
                    </div>
                    {latest && (
                      <div className='flex flex-col gap-2 rounded-lg border p-3 text-sm'>
                        <span>
                          当前草稿：{form.getValues('name')} ·{' '}
                          {form.getValues('slug')} · {drafts.length} 个接口
                        </span>
                        <span>
                          服务器版本 {latest.version}：{latest.name} ·{' '}
                          {latest.slug} · {latest.operations?.length ?? 1}{' '}
                          个接口
                        </span>
                        {comparison.length > 0 && (
                          <div className='max-h-48 overflow-y-auto rounded-md border p-2'>
                            <p className='font-medium'>
                              具体差异（草稿 / 服务器）
                            </p>
                            <ul className='mt-2 flex flex-col gap-2'>
                              {comparison.map(([field, draft, saved]) => (
                                <li key={field} className='break-all'>
                                  <span className='font-medium'>{field}</span>
                                  <div>草稿：{draft || '空白'}</div>
                                  <div>服务器：{saved || '空白'}</div>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <span>
                          采用服务器版本会丢弃当前草稿；如需合并，请先记录草稿并在最新配置中重新编辑。
                        </span>
                        <Button
                          type='button'
                          variant='outline'
                          className='self-start'
                          onClick={adoptLatest}
                        >
                          放弃草稿，采用服务器配置
                        </Button>
                      </div>
                    )}
                  </AlertDescription>
                </Alert>
              )}
              {drafts.length > 0 && !independentCreation && (
                <ModelReadiness navigate={setTab} />
              )}
              {!independentCreation && (
                <CollapsibleSection
                  title='高级：多个用途与独立开关'
                  defaultOpen={!!currentModel || !drafts.length}
                  className='mb-4'
                >
                  <div className='flex flex-wrap items-center justify-between gap-3'>
                    <div>
                      <h3 className='font-medium'>模型用途</h3>
                      <p className='text-sm text-muted-foreground'>
                        先核对当前用途的参数、来源和价格，再保存草稿或直接启用。对话请求协议沿用渠道配置。
                      </p>
                    </div>
                    {drafts.length < Object.keys(kinds).length && (
                      <Select
                        value=''
                        disabled={pending || readOnly}
                        onValueChange={(kind) =>
                          changeOperation(kind as OperationKind, true)
                        }
                      >
                        <SelectTrigger aria-label='添加接口' className='w-40'>
                          <SelectValue placeholder='添加接口' />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            {Object.entries(kinds)
                              .filter(
                                ([kind]) =>
                                  !drafts.some((draft) => draft.kind === kind)
                              )
                              .map(([kind, label]) => (
                                <SelectItem key={kind} value={kind}>
                                  {label}
                                </SelectItem>
                              ))}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                  {drafts.length === 0 ? (
                    <p className='mt-4 text-sm text-muted-foreground'>
                      尚未配置调用接口。可先登记模型资料并保存；模型不会开放调用。
                    </p>
                  ) : (
                    <div className='mt-4 flex flex-col gap-2'>
                      {drafts.map((draft) => {
                        const active = draft.kind === currentKind
                        const enabled = active
                          ? operationEnabled
                          : draft.operation_enabled
                        return (
                          <div
                            key={draft.kind}
                            className='flex flex-wrap items-center gap-3 rounded-md border p-3'
                          >
                            <span className='min-w-20 font-medium'>
                              {kinds[draft.kind]}
                            </span>
                            <span className='text-sm text-muted-foreground'>
                              {active
                                ? currentBindings.length
                                : draft.bindings.length}{' '}
                              个来源
                            </span>
                            <div className='ml-auto flex items-center gap-2'>
                              <Switch
                                aria-label={`启用${kinds[draft.kind]}接口`}
                                checked={enabled}
                                disabled={pending || readOnly}
                                onCheckedChange={(checked) => {
                                  if (active)
                                    form.setValue(
                                      'operation_enabled',
                                      checked,
                                      {
                                        shouldDirty: true,
                                      }
                                    )
                                  else {
                                    setDrafts((before) =>
                                      before.map((item) =>
                                        item.kind === draft.kind
                                          ? {
                                              ...item,
                                              operation_enabled: checked,
                                            }
                                          : item
                                      )
                                    )
                                    setDraftDirty(true)
                                  }
                                }}
                              />
                              <Button
                                type='button'
                                variant={active ? 'secondary' : 'outline'}
                                size='sm'
                                onClick={() => changeOperation(draft.kind)}
                              >
                                配置
                              </Button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </CollapsibleSection>
              )}

              <Tabs
                value={tab}
                onValueChange={setTab}
                className='min-w-0 gap-6'
              >
                <div className='overflow-x-auto'>
                  <TabsList>
                    <TabsTrigger value='profile'>基本信息</TabsTrigger>
                    <TabsTrigger value='bindings' disabled={!drafts.length}>
                      渠道与路由
                    </TabsTrigger>
                    <TabsTrigger value='prices'>价格配置</TabsTrigger>
                    <TabsTrigger value='access' disabled={!drafts.length}>
                      调用设置
                    </TabsTrigger>
                  </TabsList>
                </div>
                <TabsContent value='profile'>
                  <fieldset disabled={pending || readOnly}>
                    <ModelFields
                      disabled={pending || readOnly}
                      showOperation
                      operationConfigured={drafts.length > 0}
                      existing={!!currentModel}
                      names={names}
                      showMetadataSuggestion={!independentCreation}
                      changeKind={
                        independentCreation ? changeCreationKind : undefined
                      }
                    />
                  </fieldset>
                  {drafts.length > 0 && (
                    <CollapsibleSection
                      title='接口路径与请求示例'
                      className='mt-6'
                    >
                      <ModelEndpointsPanel
                        model={currentModel}
                        dirty={dirty}
                        configuredOnly
                      />
                    </CollapsibleSection>
                  )}
                </TabsContent>
                <TabsContent value='bindings'>
                  <fieldset disabled={pending || readOnly}>
                    {drafts.length > 0 && (
                      <BindingFields
                        key={currentKind}
                        model={
                          currentModel
                            ? operationModel(currentModel, currentKind)
                            : undefined
                        }
                        disabled={pending || readOnly}
                        names={names}
                        remember={(id, name) =>
                          setNames((before) => ({ ...before, [id]: name }))
                        }
                      />
                    )}
                  </fieldset>
                  {drafts.length > 0 && !independentCreation && (
                    <Button
                      type='button'
                      variant='outline'
                      className='mt-4'
                      disabled={
                        pending ||
                        readOnly ||
                        operationEnabled ||
                        (drafts.length === 1 &&
                          form.getValues('access.enabled'))
                      }
                      onClick={() => setRemoving(true)}
                    >
                      移除当前接口配置
                    </Button>
                  )}
                </TabsContent>
                <TabsContent value='access'>
                  <fieldset disabled={pending || readOnly}>
                    {drafts.length > 0 && (
                      <AccessFields
                        disabled={pending || readOnly || !drafts.length}
                        singleOperation={drafts.length === 1}
                        names={names}
                      />
                    )}
                  </fieldset>
                </TabsContent>
                <TabsContent value='prices'>
                  <fieldset disabled={pending || readOnly}>
                    {drafts.length > 0 && (
                      <PriceFields
                        disabled={pending || readOnly}
                        names={names}
                        target={priceTarget}
                        setTarget={setPriceTarget}
                      />
                    )}
                  </fieldset>
                  <ReferenceSnapshots disabled={pending || readOnly} />
                </TabsContent>
              </Tabs>
            </div>
            <Separator />
            <SheetFooter className='shrink-0 flex-row flex-wrap items-center justify-end px-4 sm:px-6'>
              {!!error && (
                <div className='w-full'>
                  <RequestError error={error} />
                </div>
              )}
              <div className='flex gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  disabled={pending}
                  onClick={requestClose}
                >
                  取消
                </Button>
                {!readOnly && (
                  <>
                    <Button
                      variant={independentCreation ? 'default' : 'outline'}
                      disabled={pending}
                    >
                      {pending
                        ? '保存中…'
                        : currentModel
                          ? '保存配置'
                          : independentCreation
                            ? '创建模型'
                            : '保存草稿'}
                    </Button>
                    {drafts.length > 0 && !independentCreation && (
                      <Button
                        type='button'
                        disabled={pending}
                        onClick={async () => {
                          setActivating(true)
                          try {
                            await submit(form.getValues(), false, true)
                          } finally {
                            setActivating(false)
                          }
                        }}
                      >
                        {activating ? '正在校验…' : '保存并启用'}
                      </Button>
                    )}
                  </>
                )}
              </div>
            </SheetFooter>
          </form>
        </Form>
      </SheetContent>
    </Sheet>
  )
}
