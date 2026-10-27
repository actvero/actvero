import { useDeferredValue, useState } from 'react'
import { useFormContext } from 'react-hook-form'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Check, ChevronLeft, ChevronRight } from 'lucide-react'
import { api, dateTime, messageOf, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import type { ModelValues, PriceKey } from './model-form'
import { ReferenceDetail } from './reference-detail'
import { emptyReferenceFilters } from './reference-filter-values'
import { ReferenceFilterBar, ReferenceSelect } from './reference-filters'
import {
  referenceChanges,
  referenceDraft,
  referenceProvider,
  isPlanChannel,
  type ImportOptions,
} from './reference-import'
import type { ReferenceModel } from './reference-models'

type PickerProps = {
  mode: 'metadata' | 'price'
  disabled: boolean
  preserveSlug?: boolean
  names?: Record<string, string>
  priceTarget?: PriceKey
  applied?: (target: PriceKey) => void
}

export function ReferencePicker(props: PickerProps) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          disabled={props.disabled}
        >
          {props.mode === 'metadata' ? '从公开资料补全' : '导入参考价格'}
        </Button>
      </DialogTrigger>
      {open && <PickerContent {...props} close={() => setOpen(false)} />}
    </Dialog>
  )
}

function PickerContent({
  mode,
  preserveSlug = false,
  names = {},
  priceTarget = 'budget_price',
  applied,
  close,
}: PickerProps & { close: () => void }) {
  const form = useFormContext<ModelValues>()
  const [current] = useState(() => structuredClone(form.getValues()))
  const initialBinding =
    priceTarget === 'budget_price'
      ? (current.bindings.find(
          (b) => b.channel_id === current.reference?.channel_id
        ) ?? current.bindings[0])
      : current.bindings[Number(priceTarget.split('.')[1])]
  const [contextIndex, setContextIndex] = useState(
    Math.max(0, current.bindings.indexOf(initialBinding))
  )
  const { organization, csrf } = useOrganization()
  const [search, setSearch] = useState(
    (
      initialBinding?.upstream_id ||
      current.reference?.model_id ||
      current.slug
    ).slice(0, 100)
  )
  const [filters, setFilters] = useState({ ...emptyReferenceFilters })
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<ReferenceModel | null>(null)
  const [selectedFetchedAt, setSelectedFetchedAt] = useState('')
  const [step, setStep] = useState<'list' | 'detail' | 'preview'>('list')
  const [prioritize, setPrioritize] = useState(true)
  const [acknowledged, setAcknowledged] = useState(false)
  const [draftChanged, setDraftChanged] = useState(false)
  const [priceExcluded, setPriceExcluded] = useState(false)
  const [fxRate, setFxRate] = useState('')
  const [fxDate, setFxDate] = useState('')
  const [fxPreview, setFxPreview] = useState<{
    key: string
    price: Schema['TokenPrice-Output']
    fx_rate: string
    fx_date: string
    rounding_notes: string[]
  } | null>(null)
  const [fxError, setFxError] = useState('')
  const [fxPending, setFxPending] = useState(false)
  const [options, setOptions] = useState<ImportOptions>({
    metadata: mode === 'metadata',
    basic: true,
    limits: true,
    capabilities: true,
    overwrite: false,
    price: mode === 'price',
    snapshot: false,
    target: priceTarget,
  })
  const targets: [string, string][] = [
    ['budget_price', '成员预算价格'],
    ...current.bindings.map((b, i): [string, string] => [
      `bindings.${i}.price`,
      `${names[b.channel_id] || '渠道'} / ${b.upstream_id} · 采购价格`,
    ]),
  ]
  const targetLabel =
    targets.find(([key]) => key === options.target)?.[1] ?? '未知价格对象'
  const targetBinding =
    options.target === 'budget_price'
      ? null
      : current.bindings[Number(options.target.split('.')[1])]
  const contextBinding =
    targetBinding ?? current.bindings[contextIndex] ?? current.bindings[0]
  const channelId = contextBinding?.channel_id ?? ''
  const channel = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'model-channels',
      channelId,
    ],
    enabled: !!channelId,
    queryFn: ({ signal }) =>
      api<Schema['ChannelDetail']>(
        '/llm/channels/' + channelId,
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
  })
  const preferredProvider = channel.data?.provider
    ? referenceProvider(channel.data.provider)
    : (current.reference?.provider ?? '')
  const preferredModel =
    contextBinding?.upstream_id || current.reference?.model_id || current.slug
  const conversion = useQuery({
    queryKey: ['organization', organization.tenant_id, 'llm-point-conversion'],
    enabled: options.price && options.target === 'budget_price',
    queryFn: ({ signal }) =>
      api<Schema['PointConversionSettings']>(
        '/llm/point-conversion',
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
  })
  const params = new URLSearchParams({
    q: search,
    page: String(page),
  })
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  if (prioritize) {
    params.set('preferred_provider', preferredProvider)
    params.set('preferred_model', preferredModel)
  }
  const serialized = params.toString()
  const deferredParams = useDeferredValue(serialized)
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'reference-models',
      deferredParams,
    ],
    queryFn: ({ signal }) =>
      api<Schema['ReferencePage']>(
        '/llm/reference-models?' + deferredParams,
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
    placeholderData: keepPreviousData,
  })
  const updating = query.isFetching || serialized !== deferredParams
  const targetCurrency = conversion.data?.conversion?.currency
  const needsFx =
    options.price &&
    options.target === 'budget_price' &&
    !!selected?.price &&
    !!targetCurrency &&
    targetCurrency !== selected.price.currency
  const fxKey =
    selected && targetCurrency
      ? `${selected.provider}/${selected.model_id}/${JSON.stringify(selected.price)}/${targetCurrency}/${fxRate}/${fxDate}`
      : ''
  const activeFx = fxPreview?.key === fxKey ? fxPreview : null
  const quoteLimit =
    !!selected?.quote_snapshot &&
    current.quote_snapshots.length >= 10 &&
    !current.quote_snapshots.some(
      (item) =>
        item.provider === selected.provider &&
        item.model_id === selected.model_id
    )
  const candidate = selected
    ? referenceDraft(
        current,
        selected,
        {
          ...options,
          convertedPrice: activeFx?.price,
          fxRate: activeFx?.fx_rate,
          fxDate: activeFx?.fx_date,
          fetchedAt: selectedFetchedAt,
        },
        preserveSlug
      )
    : null
  const changes = candidate ? referenceChanges(current, candidate, options) : []
  let priceBlocked = ''
  if (options.price) {
    if (current.kind !== 'chat')
      priceBlocked = `${{ embedding: '向量', rerank: '重排', image_generation: '图片生成', speech: '语音合成', transcription: '语音转文字' }[current.kind]}接口的生效计量与这份 Token 输入/输出报价不匹配；可保存原始参考报价，按当前接口的实际计量单独配置价格。`
    else if (
      !selected?.price ||
      (!selected.price_importable &&
        !(options.partialBudget && options.target === 'budget_price'))
    )
      priceBlocked = selected?.price_conditions?.length
        ? '这份报价暂不能直接导入：' + selected.price_conditions.join('；')
        : '这份报价没有可导入的完整单价，请在价格配置中手动填写。'
    else if (options.target === 'budget_price') {
      if (conversion.isPending || conversion.isFetching)
        priceBlocked = '正在核对组织计价币种…'
      else if (conversion.isError)
        priceBlocked = '无法核对组织计价币种，请重试。'
      else if (needsFx && !activeFx)
        priceBlocked = `组织使用 ${targetCurrency}，报价为 ${selected.price.currency}，请填写汇率与日期并核对服务端换算结果。`
    } else if (!targetBinding) priceBlocked = '该渠道关联已不存在。'
    else if (channel.isPending || channel.isFetching)
      priceBlocked = '正在核对采购渠道…'
    else if (channel.isError || !channel.data?.provider)
      priceBlocked = '无法核对采购渠道，请重试。'
    else if (isPlanChannel(channel.data))
      priceBlocked = '此渠道使用套餐计费，公开按量报价不能作为套餐采购单价。'
    else if (!acknowledged) priceBlocked = '请确认已核对该渠道的实际采购单价。'
  }
  // Build the recovery preview independently: a valid quote may still be blocked
  // by its currency, procurement acknowledgement or subscription channel.
  const metadataOptions = { ...options, price: false }
  const metadataCandidate =
    selected && (options.metadata || options.snapshot) && priceBlocked
      ? referenceDraft(current, selected, metadataOptions, preserveSlug)
      : null
  const metadataChanges = metadataCandidate
    ? referenceChanges(current, metadataCandidate, metadataOptions)
    : []
  const metadataOnly = metadataChanges.length > 0
  const previewCount = metadataOnly ? metadataChanges.length : changes.length
  const select = (model: ReferenceModel) => {
    setSelected(model)
    setOptions((previous) => ({
      ...previous,
      snapshot:
        !!model.quote_snapshot &&
        (current.quote_snapshots.length < 10 ||
          current.quote_snapshots.some(
            (item) =>
              item.provider === model.provider &&
              item.model_id === model.model_id
          )),
      partialBudget: false,
    }))
    setSelectedFetchedAt(query.data?.fetched_at ?? '')
    setStep('detail')
    setAcknowledged(false)
    setFxPreview(null)
  }
  const resetResults = () => {
    setPage(1)
    setSelected(null)
    setStep('list')
    setAcknowledged(false)
    setFxPreview(null)
  }
  const selectedLabel = selected
    ? `${selected.provider_name} / ${selected.model_id}`
    : '尚未选择'
  const apply = () => {
    if (
      !candidate ||
      priceBlocked ||
      !changes.length ||
      query.isError ||
      updating
    )
      return
    // A preview describes one exact draft, never a binding that changed underneath it.
    if (JSON.stringify(form.getValues()) !== JSON.stringify(current)) {
      setDraftChanged(true)
      return
    }
    form.reset(candidate, { keepDefaultValues: true })
    if (options.price) applied?.(options.target)
    close()
  }
  return (
    <DialogContent
      className='flex h-[90dvh] max-h-[960px] min-w-0 flex-col sm:max-w-6xl'
      aria-describedby={undefined}
    >
      <DialogHeader className='shrink-0 pr-6'>
        <DialogTitle>
          {step === 'preview' ? '预览导入修改' : '选择公开模型资料与报价'}
        </DialogTitle>
        <p className='text-sm break-words text-muted-foreground'>
          当前模型：{current.name || current.slug || '新模型'}
          {contextBinding &&
            ` · ${channel.data?.name || names[channelId] || '关联渠道'} / ${contextBinding.upstream_id}`}
        </p>
        {current.bindings.length > 1 &&
          !targetBinding &&
          step !== 'preview' && (
            <div className='max-w-lg'>
              <ReferenceSelect
                label='参考渠道'
                value={String(contextIndex)}
                items={current.bindings.map((b, i) => [
                  String(i),
                  `${names[b.channel_id] || '渠道'} / ${b.upstream_id}`,
                ])}
                change={(value) => {
                  setContextIndex(Number(value))
                  setSearch(
                    current.bindings[Number(value)].upstream_id.slice(0, 100)
                  )
                  resetResults()
                }}
              />
            </div>
          )}
      </DialogHeader>
      <Separator />
      {step === 'preview' ? (
        <div className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto'>
          <p className='text-sm break-all'>{selectedLabel}</p>
          {priceExcluded && (
            <Alert>
              <AlertDescription>
                {options.snapshot
                  ? '本次仅保存所选资料与参考报价，成员预算价格与渠道采购价格均保持不变。'
                  : '本次仅导入模型资料，成员预算价格与渠道采购价格均保持不变。'}
              </AlertDescription>
            </Alert>
          )}
          {options.snapshot && selected?.quote_snapshot && (
            <Alert>
              <AlertDescription>
                保存原始参考报价：{selected.quote_snapshot.currency} /{' '}
                {selected.quote_snapshot.unit} {selected.quote_snapshot.metric}
                ，{Object.keys(selected.quote_snapshot.raw_cost ?? {}).length}{' '}
                项。未支持的条件仍只作参考。
              </AlertDescription>
            </Alert>
          )}
          {options.price && (
            <Alert>
              <AlertDescription>
                价格对象：{targetLabel}。
                {options.partialBudget &&
                  '这是组织内部简化预算价；未选的供应商费率不进入预算。'}
                以下单价为{' '}
                {activeFx?.price.currency ?? selected?.price?.currency ?? 'USD'}{' '}
                / 每百万 Token；未提供的旧费率将清空。
                {activeFx &&
                  ` 汇率 ${activeFx.fx_rate}，日期 ${activeFx.fx_date}。`}
              </AlertDescription>
            </Alert>
          )}
          {activeFx?.rounding_notes.map((note, i) => (
            <p key={i} className='text-xs text-muted-foreground'>
              {note}
            </p>
          ))}
          <div className='flex flex-col divide-y rounded-md border'>
            {changes.map((row) => (
              <div
                key={row.label}
                className='grid gap-2 p-3 text-sm sm:grid-cols-[1fr_1fr_1fr]'
              >
                <span className='font-medium'>{row.label}</span>
                <span className='break-all text-muted-foreground'>
                  当前：{row.before}
                </span>
                <span className='break-all'>修改为：{row.after}</span>
              </div>
            ))}
          </div>
          <p className='text-sm text-muted-foreground'>
            确认后仅更新编辑草稿，保存模型后生效。渠道绑定、调用权限和其他接口配置保持原值。
          </p>
          {draftChanged && (
            <Alert variant='destructive'>
              <AlertDescription>
                原模型草稿已变化，请关闭并重新打开公开模型选择器。
              </AlertDescription>
            </Alert>
          )}
        </div>
      ) : (
        <div className='flex min-h-0 flex-1 flex-col gap-3'>
          <div
            className={cn(
              'max-h-[42dvh] shrink-0 overflow-y-auto',
              step === 'detail' && 'hidden lg:block'
            )}
          >
            <ReferenceFilterBar
              search={search}
              setSearch={(value) => {
                setSearch(value)
                resetResults()
              }}
              filters={filters}
              change={(value) => {
                setFilters(value)
                resetResults()
              }}
              facets={query.data?.facets}
              preferred={preferredProvider}
              prioritize={prioritize}
              setPrioritize={(value) => {
                setPrioritize(value)
                resetResults()
              }}
            />
          </div>
          <div className='flex shrink-0 flex-wrap items-center justify-between gap-1 text-xs text-muted-foreground'>
            <span>
              models.dev · {query.data?.total ?? '—'} 条供应商模型记录
            </span>
            <span>
              {query.data && `抓取于 ${dateTime(query.data.fetched_at)}`}
            </span>
          </div>
          {query.data?.stale && (
            <Alert>
              <AlertDescription>同步失败，正在使用旧资料。</AlertDescription>
            </Alert>
          )}
          <div className='grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]'>
            <div
              className={cn(
                'min-h-0 min-w-0 flex-col gap-3',
                step === 'detail' ? 'hidden lg:flex' : 'flex'
              )}
            >
              <div
                className='min-h-0 flex-1 overflow-y-auto rounded-md border p-2'
                aria-busy={updating}
              >
                {query.isPending ||
                query.isPlaceholderData ||
                serialized !== deferredParams ? (
                  <LoadingState />
                ) : query.isError ? (
                  <RequestError
                    error={query.error}
                    retry={() => void query.refetch()}
                  />
                ) : (
                  <div className='flex flex-col gap-1'>
                    {query.data.items.length === 0 && (
                      <div className='p-5 text-sm text-muted-foreground'>
                        没有匹配的公开资料。试试减少筛选条件或调整模型 ID。
                      </div>
                    )}
                    {query.data.items.map((model) => (
                      <Button
                        key={`${model.provider}/${model.model_id}`}
                        type='button'
                        variant={
                          selected?.provider === model.provider &&
                          selected.model_id === model.model_id
                            ? 'secondary'
                            : 'ghost'
                        }
                        aria-pressed={
                          selected?.provider === model.provider &&
                          selected.model_id === model.model_id
                        }
                        className='h-auto w-full justify-start px-3 py-3 text-left whitespace-normal'
                        onClick={() => select(model)}
                      >
                        <div className='flex w-full min-w-0 flex-col gap-2'>
                          <div className='flex items-center justify-between gap-2'>
                            <span className='min-w-0 truncate'>
                              {model.name}
                            </span>
                            {selected?.provider === model.provider &&
                              selected.model_id === model.model_id && (
                                <Check className='shrink-0' />
                              )}
                          </div>
                          <span className='text-xs break-all text-muted-foreground'>
                            {model.model_id}
                          </span>
                          <div className='flex flex-wrap gap-2 text-xs text-muted-foreground'>
                            <span>{model.provider_name}</span>
                            <span>
                              上下文{' '}
                              {model.context_window?.toLocaleString() ?? '未知'}
                            </span>
                            {model.price && (
                              <span>
                                {model.price_importable ? '' : '基础价 '}输入 $
                                {model.price.input ?? '—'} / 输出 $
                                {model.price.output ?? '—'} · 每百万 Token
                              </span>
                            )}
                          </div>
                          {model.model_id.toLowerCase() ===
                            preferredModel.toLowerCase() &&
                            model.provider === preferredProvider && (
                              <Badge variant='outline' className='self-start'>
                                当前渠道与型号匹配
                              </Badge>
                            )}
                        </div>
                      </Button>
                    ))}
                  </div>
                )}
              </div>
              <div className='flex shrink-0 items-center justify-between gap-2'>
                <Button
                  type='button'
                  size='sm'
                  variant='outline'
                  disabled={page === 1 || updating}
                  onClick={() => setPage(page - 1)}
                >
                  <ChevronLeft />
                  上一页
                </Button>
                <span className='text-sm tabular-nums'>
                  {page} /{' '}
                  {Math.max(
                    1,
                    Math.ceil(
                      (query.data?.total ?? 0) / (query.data?.page_size ?? 20)
                    )
                  )}
                </span>
                <Button
                  type='button'
                  size='sm'
                  variant='outline'
                  disabled={
                    !query.data ||
                    page * (query.data.page_size ?? 20) >= query.data.total ||
                    updating
                  }
                  onClick={() => setPage(page + 1)}
                >
                  下一页
                  <ChevronRight />
                </Button>
              </div>
            </div>
            <div
              className={cn(
                'min-h-0 min-w-0 flex-col gap-4 overflow-y-auto rounded-md border p-4',
                step === 'list' ? 'hidden lg:flex' : 'flex'
              )}
            >
              {selected ? (
                <>
                  <Button
                    type='button'
                    variant='ghost'
                    size='sm'
                    className='shrink-0 self-start lg:hidden'
                    onClick={() => setStep('list')}
                  >
                    <ArrowLeft />
                    返回结果
                  </Button>
                  <ReferenceDetail
                    key={`${selected.provider}/${selected.model_id}`}
                    model={selected}
                    mode={mode}
                  />
                  <Separator />
                  <div className='flex flex-col gap-3'>
                    <h4 className='text-sm font-medium'>导入内容</h4>
                    <Label className='flex items-center gap-2'>
                      <Checkbox
                        checked={options.metadata}
                        onCheckedChange={(v) =>
                          setOptions({ ...options, metadata: v === true })
                        }
                      />
                      导入模型资料
                    </Label>
                    {options.metadata && (
                      <div className='ml-6 flex flex-col gap-3'>
                        {(
                          [
                            ['basic', '名称、开发方与图标'],
                            ['limits', '上下文与输出上限'],
                            ['capabilities', '能力声明与思考参数'],
                          ] as const
                        ).map(([key, label]) => (
                          <Label key={key} className='flex items-center gap-2'>
                            <Checkbox
                              checked={options[key]}
                              onCheckedChange={(v) =>
                                setOptions({ ...options, [key]: v === true })
                              }
                            />
                            {label}
                          </Label>
                        ))}
                        <Label className='flex items-center gap-2'>
                          <Checkbox
                            checked={options.overwrite}
                            onCheckedChange={(v) =>
                              setOptions({ ...options, overwrite: v === true })
                            }
                          />
                          覆盖已有资料
                        </Label>
                        <p className='text-xs text-muted-foreground'>
                          {options.overwrite
                            ? '覆盖所选资料中已填写的值。'
                            : '只填空项和未知声明。'}
                          {preserveSlug && '已有模型技术名称保持不变。'}
                        </p>
                      </div>
                    )}
                    <Label className='flex items-center gap-2'>
                      <Checkbox
                        checked={options.snapshot}
                        disabled={!selected.quote_snapshot || quoteLimit}
                        onCheckedChange={(v) =>
                          setOptions({ ...options, snapshot: v === true })
                        }
                      />
                      保存原始参考报价快照（不改价格）
                    </Label>
                    {quoteLimit && (
                      <p className='text-xs text-destructive'>
                        已保存 10 份报价；请先在模型配置中清理旧快照。
                      </p>
                    )}
                    <Label className='flex items-center gap-2'>
                      <Checkbox
                        checked={options.price}
                        onCheckedChange={(v) =>
                          setOptions({ ...options, price: v === true })
                        }
                      />
                      导入参考价格
                    </Label>
                    {options.price && (
                      <div className='ml-6 flex flex-col gap-3'>
                        <ReferenceSelect
                          label='导入价格对象'
                          value={options.target}
                          items={targets}
                          change={(v) => {
                            setOptions({
                              ...options,
                              target: v as PriceKey,
                              partialBudget: false,
                            })
                            setAcknowledged(false)
                          }}
                        />
                        {targetBinding && (
                          <Label className='flex items-start gap-2'>
                            <Checkbox
                              checked={acknowledged}
                              onCheckedChange={(v) =>
                                setAcknowledged(v === true)
                              }
                            />
                            已核对该渠道的供应商、套餐和实际采购单价
                          </Label>
                        )}
                        {options.target === 'budget_price' &&
                          !selected.price_importable &&
                          selected.price?.output != null &&
                          ['input', 'output'].every((key) =>
                            selected.quote_items?.some(
                              (item) =>
                                item.key === key && item.status === 'compatible'
                            )
                          ) && (
                            <Label className='flex items-start gap-2'>
                              <Checkbox
                                checked={!!options.partialBudget}
                                onCheckedChange={(v) =>
                                  setOptions({
                                    ...options,
                                    partialBudget: v === true,
                                  })
                                }
                              />
                              仅采用基础输入/输出作组织内部预算价；其他供应商费率只保存在参考报价中
                            </Label>
                          )}
                        {targetBinding &&
                          preferredProvider &&
                          preferredProvider !== selected.provider && (
                            <p className='text-sm text-muted-foreground'>
                              报价供应商与当前渠道不同，请核实后再导入。
                            </p>
                          )}
                        {options.target === 'budget_price' &&
                          conversion.data?.conversion === null && (
                            <p className='text-sm text-muted-foreground'>
                              组织尚未配置积分换算；可保存价格草稿，成员扣费需另行配置。
                            </p>
                          )}
                        {needsFx && selected.price && (
                          <div className='flex flex-col gap-2 rounded-md border p-3'>
                            <p className='text-sm'>
                              显式汇率换算：1 {selected.price.currency} = ?{' '}
                              {targetCurrency}。请填写有依据的汇率与日期。
                            </p>
                            <div className='grid gap-2 sm:grid-cols-2'>
                              <Label htmlFor='reference-fx-rate'>
                                汇率
                                <Input
                                  id='reference-fx-rate'
                                  inputMode='decimal'
                                  value={fxRate}
                                  onChange={(event) => {
                                    setFxRate(event.target.value)
                                    setFxPreview(null)
                                  }}
                                  placeholder='例如 7.1234'
                                />
                              </Label>
                              <Label htmlFor='reference-fx-date'>
                                汇率日期
                                <Input
                                  id='reference-fx-date'
                                  type='date'
                                  value={fxDate}
                                  onChange={(event) => {
                                    setFxDate(event.target.value)
                                    setFxPreview(null)
                                  }}
                                />
                              </Label>
                            </div>
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              disabled={
                                fxPending ||
                                !/^\d+(?:\.\d+)?$/.test(fxRate) ||
                                !fxDate
                              }
                              onClick={() => {
                                setFxPending(true)
                                setFxError('')
                                void api<{
                                  price: Schema['TokenPrice-Output']
                                  fx_rate: string
                                  fx_date: string
                                  rounding_notes: string[]
                                }>(
                                  '/llm/reference-price-preview',
                                  'POST',
                                  {
                                    price: selected.price,
                                    target_currency: targetCurrency,
                                    fx_rate: fxRate,
                                    fx_date: fxDate,
                                  },
                                  csrf
                                )
                                  .then((result) =>
                                    setFxPreview({
                                      key: fxKey,
                                      price: result.price,
                                      fx_rate: result.fx_rate,
                                      fx_date: result.fx_date,
                                      rounding_notes: result.rounding_notes,
                                    })
                                  )
                                  .catch((error: unknown) =>
                                    setFxError(messageOf(error))
                                  )
                                  .finally(() => setFxPending(false))
                              }}
                            >
                              核对换算结果
                            </Button>
                            {fxError && (
                              <p className='text-xs text-destructive'>
                                {fxError}
                              </p>
                            )}
                            {activeFx && (
                              <p className='text-xs'>
                                已核对：输入 {activeFx.price.input}、输出{' '}
                                {activeFx.price.output ?? '未提供'}{' '}
                                {activeFx.price.currency} / 每百万
                                Token；预览中可检查覆盖结果。
                              </p>
                            )}
                          </div>
                        )}
                        {priceBlocked && (
                          <Alert>
                            <AlertDescription className='break-words'>
                              {priceBlocked}
                              {metadataOnly && (
                                <p>
                                  可点击下方「仅预览资料」继续，价格保持不变。
                                </p>
                              )}
                            </AlertDescription>
                          </Alert>
                        )}
                        {conversion.isError &&
                          options.target === 'budget_price' && (
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              onClick={() => void conversion.refetch()}
                            >
                              重试币种检查
                            </Button>
                          )}
                        {channel.isError && targetBinding && (
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            onClick={() => void channel.refetch()}
                          >
                            重试渠道检查
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className='m-auto text-center text-sm text-muted-foreground'>
                  选择左侧模型，查看资料与供应商报价。
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      <Separator />
      <DialogFooter className='shrink-0 gap-3 sm:items-center'>
        <p className='mr-auto text-xs text-muted-foreground'>
          {step === 'preview'
            ? `将修改 ${changes.length} 项`
            : '公开资料 · 手动导入 · 保存模型后生效'}
        </p>
        {step === 'preview' ? (
          <>
            <Button
              type='button'
              variant='outline'
              onClick={() => {
                setPriceExcluded(false)
                setStep('detail')
              }}
            >
              返回调整
            </Button>
            <Button
              type='button'
              disabled={
                !!priceBlocked ||
                !changes.length ||
                draftChanged ||
                query.isError ||
                updating
              }
              onClick={apply}
            >
              确认应用到草稿
            </Button>
          </>
        ) : (
          <>
            <Button type='button' variant='outline' onClick={close}>
              取消
            </Button>
            <Button
              type='button'
              disabled={
                !selected ||
                (!!priceBlocked && !metadataOnly) ||
                !previewCount ||
                query.isError ||
                updating
              }
              onClick={() => {
                // The explicitly labelled action drops price import before
                // preview/apply, never just ignores the validation error.
                if (metadataOnly) setOptions(metadataOptions)
                setPriceExcluded(metadataOnly)
                setStep('preview')
              }}
            >
              {metadataOnly
                ? options.snapshot
                  ? '仅预览资料与报价'
                  : '仅预览资料'
                : '预览修改'}
              {previewCount > 0 && `（${previewCount}）`}
            </Button>
          </>
        )}
      </DialogFooter>
    </DialogContent>
  )
}
