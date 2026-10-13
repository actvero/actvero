import { useDeferredValue, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Archive, Ellipsis, Plus, RotateCcw, Search } from 'lucide-react'
import { toast } from 'sonner'
import { ApiError, api, type Schema } from '@/lib/api'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ServerTable } from '@/components/data-table/server-table'
import { FilterSelect } from '@/components/filter-select'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { endpointReasonLabel } from './endpoint-status'
import { ModelCreate } from './model-create'
import { ModelEditor } from './model-editor'
import {
  capabilities,
  kinds,
  operationModel,
  metrics,
  pointStates,
  type Model,
} from './model-form'
import { ModelImport } from './model-import'
import { ModelTest } from './model-test'
import { PointConversionButton } from './point-conversion'
import { modelIcon } from './reference-models'

function subscribeNarrow(callback: () => void) {
  const query = window.matchMedia('(max-width: 639px)')
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

function bindingIssue(model: Model) {
  const missing = model.binding_states.filter(
    (b) => b.state === 'missing'
  ).length
  const archived = model.binding_states.filter(
    (b) => b.state === 'archived'
  ).length
  return [
    missing && `${missing} 个来源缺失`,
    archived && `${archived} 个来源已归档`,
  ]
    .filter(Boolean)
    .join('，')
}

function EndpointSummary({ model }: { model: Model }) {
  const summary = model.endpoint_summary
  return (
    <div className='flex min-w-0 flex-col gap-1 text-sm'>
      <span>
        接口配置：
        {summary
          ? `${summary.ready_count}/${summary.configured_count} 就绪`
          : '待更新'}
      </span>
      {!!summary?.reasons?.length && (
        <span className='text-muted-foreground'>
          {Array.from(new Set(summary.reasons.map(endpointReasonLabel)))
            .slice(0, 2)
            .join('、')}
          {summary.reasons.length > 2 && '等'}
        </span>
      )}
    </div>
  )
}

export function ModelCatalogPage() {
  const { csrf, organization } = useOrganization()
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const q = useDeferredValue(search)
  const [state, setState] = useState('current')
  const [page, setPage] = useState(1)
  const [editor, setEditor] = useState<Model | 'new' | null>(null)
  const [importing, setImporting] = useState(false)
  const [testing, setTesting] = useState<Model | null>(null)
  const [kind, setKind] = useState('')
  const [archive, setArchive] = useState<Model | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [detailError, setDetailError] = useState<unknown>(null)
  const [loadingModelId, setLoadingModelId] = useState<string | null>(null)
  const [archiveStale, setArchiveStale] = useState(false)
  const [permissionDenied, setPermissionDenied] = useState(false)
  const narrow = useSyncExternalStore(
    subscribeNarrow,
    () => window.matchMedia('(max-width: 639px)').matches,
    () => false
  )
  const add = useRef<HTMLButtonElement>(null)
  const trigger = useRef<HTMLElement | null>(null)
  const prefix = ['organization', organization.tenant_id, 'model-catalog']
  const params = new URLSearchParams({
    q,
    ...(kind ? { kind } : {}),
    state: state || 'all',
    page: String(page),
  }).toString()
  const query = useQuery({
    queryKey: [...prefix, params],
    queryFn: ({ signal }) =>
      api<Schema['CatalogPage']>(
        '/llm/models?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const canWrite =
    !permissionDenied &&
    !(query.error instanceof ApiError && query.error.status === 403)
  function remember() {
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
  }
  function restore() {
    if (trigger.current?.isConnected) trigger.current.focus()
    else add.current?.focus()
  }
  async function openEditor(model: Model, preserveTrigger = false) {
    if (model.archived || loadingModelId || !canWrite) return
    if (!preserveTrigger) remember()
    setDetailError(null)
    setLoadingModelId(model.id)
    try {
      const latest = await api<Model>('/llm/models/' + model.id)
      if (latest.archived) {
        void client.invalidateQueries({ queryKey: prefix })
        setDetailError(new Error('模型已归档，请刷新列表后查看最新状态。'))
        return
      }
      setEditor(latest)
    } catch (e) {
      setDetailError(e)
      if (e instanceof ApiError && e.status === 403) setPermissionDenied(true)
      if (e instanceof ApiError && (e.status === 403 || e.status === 404))
        void client.invalidateQueries({ queryKey: prefix })
    } finally {
      setLoadingModelId(null)
    }
  }
  async function toggleArchive() {
    if (!archive || archiveStale || !canWrite) return
    setBusy(true)
    setError(null)
    try {
      await api(
        '/llm/models/' + archive.id + '/archive',
        'PUT',
        { version: archive.version, archived: !archive.archived },
        csrf
      )
      void client.invalidateQueries({ queryKey: prefix })
      setArchive(null)
      toast.success(archive.archived ? '模型已恢复' : '模型已归档')
    } catch (e) {
      setError(e)
      if (e instanceof ApiError && (e.status === 403 || e.status === 409)) {
        setArchiveStale(true)
        void client.invalidateQueries({ queryKey: prefix })
      }
      if (e instanceof ApiError && e.status === 403) setPermissionDenied(true)
    } finally {
      setBusy(false)
    }
  }
  const columns: ColumnDef<Model>[] = [
    {
      id: 'name',
      header: '模型 / 技术名称',
      cell: ({ row: { original: model } }) => (
        <div className='flex items-center gap-3'>
          <Avatar>
            <AvatarImage src={modelIcon(model)} alt='' />
            <AvatarFallback>{model.name.slice(0, 1)}</AvatarFallback>
          </Avatar>
          <div className='flex min-w-52 flex-col items-start gap-1'>
            <Button
              variant='link'
              className='h-auto max-w-64 justify-start p-0'
              disabled={model.archived || !canWrite}
              onClick={() => void openEditor(model)}
            >
              <span className='truncate'>{model.name}</span>
            </Button>
            <span className='text-sm text-muted-foreground'>{model.slug}</span>
            <Badge variant='secondary'>
              {model.archived
                ? '已归档'
                : model.access?.enabled
                  ? '已开放'
                  : '未开放'}
            </Badge>
          </div>
        </div>
      ),
    },
    {
      id: 'capabilities',
      header: '用途与能力',
      cell: ({ row: { original: model } }) => {
        if (model.operations)
          return (
            <div className='flex min-w-36 flex-wrap gap-1'>
              {model.operations.length
                ? model.operations.map((o) => (
                    <Badge
                      key={o.kind}
                      variant={o.enabled ? 'secondary' : 'outline'}
                    >
                      {kinds[o.kind ?? 'chat']}
                      {!o.enabled && ' · 未开放'}
                    </Badge>
                  ))
                : '未配置操作'}
            </div>
          )
        if (model.kind && model.kind !== 'chat')
          return <Badge variant='outline'>{kinds[model.kind]}</Badge>
        const supported = capabilities.filter(
          ([key]) => model.capabilities?.[key] === 'supported'
        )
        return supported.length ? (
          <div className='flex min-w-36 flex-wrap gap-1'>
            {supported.map(([key, label]) => (
              <Badge variant='outline' key={key}>
                {label}
              </Badge>
            ))}
          </div>
        ) : (
          <span className='text-sm text-muted-foreground'>未声明支持能力</span>
        )
      },
    },
    {
      id: 'channels',
      header: '渠道关联',
      cell: ({ row: { original: model } }) => (
        <div className='flex min-w-32 flex-col gap-1'>
          <span>
            {model.operations?.reduce(
              (sum, op) => sum + (op.bindings?.length ?? 0),
              0
            ) ??
              model.bindings?.length ??
              0}{' '}
            个关联
          </span>
          {!!bindingIssue(model) && (
            <Badge variant='destructive'>{bindingIssue(model)}</Badge>
          )}
          <EndpointSummary model={model} />
        </div>
      ),
    },
    {
      id: 'price',
      header: '预算价格',
      cell: ({ row: { original: model } }) => (
        <OperationPrices
          model={model}
          render={(model) =>
            model.budget_price ? (
              <div className='flex min-w-40 flex-col gap-1 text-sm'>
                <span>
                  {model.budget_price.currency} ·{' '}
                  {model.kind === 'image_generation' ? '每张' : '输入'}{' '}
                  {model.budget_price.input}
                </span>
                {(model.kind ?? 'chat') === 'chat' && (
                  <span>输出 {model.budget_price.output}</span>
                )}
                <span>
                  {model.budget_price.unit === 1
                    ? '每张'
                    : `每百万 ${metrics[model.budget_price.metric ?? 'tokens']}`}
                </span>
              </div>
            ) : (
              <span className='text-sm text-muted-foreground'>未配置</span>
            )
          }
        />
      ),
    },
    {
      id: 'points',
      header: '积分单价',
      cell: ({ row: { original: model } }) => (
        <OperationPrices
          model={model}
          render={(model) => {
            const value = model.point_price
            return value?.status === 'ready' ? (
              <div className='flex min-w-36 flex-col gap-1 text-sm'>
                <span>
                  {model.kind === 'image_generation' ? '每张' : '输入'}{' '}
                  {value.rates?.input} 积分
                </span>
                {(model.kind ?? 'chat') === 'chat' && (
                  <span>
                    输出{' '}
                    {value.rates?.output == null
                      ? '未配置'
                      : `${value.rates.output} 积分`}
                  </span>
                )}
                <span className='text-muted-foreground'>
                  {value.unit === 1
                    ? '每张'
                    : `每百万 ${metrics[value.metric ?? 'tokens']}`}
                </span>
              </div>
            ) : (
              <span className='text-sm text-muted-foreground'>
                {value ? pointStates[value.status] : '未配置'}
              </span>
            )
          }}
        />
      ),
    },
    {
      id: 'actions',
      header: () => <span className='sr-only'>操作</span>,
      cell: ({ row: { original: model } }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant='ghost'
              size='icon'
              aria-label={`${model.name}的更多操作`}
            >
              <Ellipsis />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align='end'
            onCloseAutoFocus={(e) => {
              if (editor || archive || testing) e.preventDefault()
            }}
          >
            <DropdownMenuGroup>
              {
                <DropdownMenuItem
                  disabled={model.archived || !canWrite}
                  onSelect={() => {
                    remember()
                    setTesting(model)
                  }}
                >
                  测试与记录
                </DropdownMenuItem>
              }
              <DropdownMenuItem
                disabled={
                  model.archived || !canWrite || loadingModelId === model.id
                }
                onSelect={() => void openEditor(model)}
              >
                编辑模型
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!canWrite}
                onSelect={() => {
                  remember()
                  setError(null)
                  setArchiveStale(false)
                  setArchive(model)
                }}
              >
                {model.archived ? <RotateCcw /> : <Archive />}
                {model.archived ? '恢复模型' : '归档模型'}
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ]
  return (
    <PageShell
      title='模型管理'
      description='统一技术名称、能力参数与渠道价格配置。'
      action={
        <div className='flex flex-wrap gap-2'>
          <PointConversionButton />
          <Button
            variant='outline'
            disabled={!canWrite}
            onClick={() => {
              remember()
              setImporting(true)
            }}
          >
            批量导入
          </Button>
          <Button
            ref={add}
            disabled={!canWrite}
            onClick={() => {
              remember()
              setEditor('new')
            }}
          >
            <Plus />
            添加模型
          </Button>
        </div>
      }
    >
      <div className='flex flex-wrap items-center gap-3'>
        <div className='flex items-center gap-2'>
          <Search className='size-4 text-muted-foreground' />
          <Input
            aria-label='搜索模型'
            placeholder='搜索名称或技术名称'
            className='w-56 sm:w-72'
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
          />
        </div>
        <FilterSelect
          label='模型用途'
          value={kind}
          onChange={(v) => {
            setKind(v)
            setPage(1)
          }}
          options={Object.entries(kinds).map(([value, label]) => ({
            value,
            label,
          }))}
        />
        <FilterSelect
          label='状态'
          value={state}
          onChange={(v) => {
            setState(v)
            setPage(1)
          }}
          options={[
            { value: 'current', label: '当前模型' },
            { value: 'archived', label: '已归档' },
          ]}
        />
      </div>
      {permissionDenied && (
        <p role='alert' className='text-sm text-muted-foreground'>
          模型管理权限已变化，写入操作已停用。请刷新页面获取最新权限。
        </p>
      )}
      {detailError !== null && (
        <RequestError
          error={detailError}
          retry={() => {
            setDetailError(null)
            void query.refetch()
          }}
        />
      )}
      {loadingModelId && (
        <p role='status' className='text-sm text-muted-foreground'>
          正在读取最新模型配置…
        </p>
      )}
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <ServerTable
          items={query.data.items}
          columns={columns}
          total={query.data.total}
          page={page}
          onPage={setPage}
          empty={
            search || state !== 'current'
              ? '没有匹配的模型'
              : '还没有模型。添加后可关联渠道中的上游模型。'
          }
          renderItems={
            narrow
              ? (items) => (
                  <div className='flex min-w-0 flex-col gap-3'>
                    {items.length ? (
                      items.map((model) => (
                        <Card
                          key={model.id}
                          density='compact'
                          className='min-w-0'
                        >
                          <CardContent className='flex min-w-0 flex-col gap-3 px-4 py-2'>
                            <div className='flex min-w-0 items-start justify-between gap-2'>
                              <div className='flex min-w-0 items-center gap-2'>
                                <Avatar className='shrink-0'>
                                  <AvatarImage src={modelIcon(model)} alt='' />
                                  <AvatarFallback>
                                    {model.name.slice(0, 1)}
                                  </AvatarFallback>
                                </Avatar>
                                <div className='min-w-0'>
                                  <Button
                                    variant='link'
                                    className='h-auto max-w-full justify-start p-0'
                                    disabled={model.archived || !canWrite}
                                    onClick={() => void openEditor(model)}
                                  >
                                    <span className='truncate'>
                                      {model.name}
                                    </span>
                                  </Button>
                                  <p className='text-sm break-all text-muted-foreground'>
                                    {model.slug}
                                  </p>
                                </div>
                              </div>
                              <Badge variant='secondary' className='shrink-0'>
                                {model.archived
                                  ? '已归档'
                                  : model.access?.enabled
                                    ? '已开放'
                                    : '未开放'}
                              </Badge>
                            </div>
                            <div className='flex flex-wrap gap-1'>
                              {model.operations?.length ? (
                                model.operations.map((op) => (
                                  <Badge
                                    key={op.kind}
                                    variant={
                                      op.enabled ? 'secondary' : 'outline'
                                    }
                                  >
                                    {kinds[op.kind ?? 'chat']}
                                    {!op.enabled && ' · 未开放'}
                                  </Badge>
                                ))
                              ) : (
                                <span className='text-sm text-muted-foreground'>
                                  未配置操作
                                </span>
                              )}
                            </div>
                            <div className='flex flex-wrap items-center gap-2 text-sm'>
                              <span>
                                渠道关联{' '}
                                {model.operations?.reduce(
                                  (sum, op) => sum + (op.bindings?.length ?? 0),
                                  0
                                ) ??
                                  model.bindings?.length ??
                                  0}
                              </span>
                              {!!bindingIssue(model) && (
                                <Badge variant='destructive'>
                                  {bindingIssue(model)}
                                </Badge>
                              )}
                            </div>
                            <EndpointSummary model={model} />
                            <div className='grid min-w-0 grid-cols-2 gap-2 border-t pt-3 text-sm'>
                              <div className='min-w-0'>
                                <p className='text-muted-foreground'>
                                  预算价格
                                </p>
                                <OperationPrices
                                  model={model}
                                  render={(operation) =>
                                    operation.budget_price ? (
                                      <span>
                                        {operation.budget_price.currency} ·{' '}
                                        {operation.budget_price.input}
                                      </span>
                                    ) : (
                                      <span>未配置</span>
                                    )
                                  }
                                />
                              </div>
                              <div className='min-w-0'>
                                <p className='text-muted-foreground'>
                                  积分单价
                                </p>
                                <OperationPrices
                                  model={model}
                                  render={(operation) =>
                                    operation.point_price?.status ===
                                    'ready' ? (
                                      <span>
                                        {operation.point_price.rates?.input}{' '}
                                        积分
                                      </span>
                                    ) : (
                                      <span>
                                        {operation.point_price
                                          ? pointStates[
                                              operation.point_price.status
                                            ]
                                          : '未配置'}
                                      </span>
                                    )
                                  }
                                />
                              </div>
                            </div>
                            <div className='flex flex-wrap gap-2 border-t pt-3'>
                              <Button
                                size='sm'
                                variant='outline'
                                disabled={model.archived || !canWrite}
                                onClick={() => {
                                  remember()
                                  setTesting(model)
                                }}
                              >
                                测试与记录
                              </Button>
                              <Button
                                size='sm'
                                variant='outline'
                                disabled={
                                  model.archived ||
                                  !canWrite ||
                                  loadingModelId === model.id
                                }
                                onClick={() => void openEditor(model)}
                              >
                                编辑
                              </Button>
                              <Button
                                size='sm'
                                variant='outline'
                                disabled={!canWrite}
                                onClick={() => {
                                  remember()
                                  setError(null)
                                  setArchiveStale(false)
                                  setArchive(model)
                                }}
                              >
                                {model.archived ? '恢复' : '归档'}
                              </Button>
                            </div>
                          </CardContent>
                        </Card>
                      ))
                    ) : (
                      <div className='rounded-md border p-8 text-center text-sm text-muted-foreground'>
                        {search || state !== 'current'
                          ? '没有匹配的模型'
                          : '还没有模型。添加后可关联渠道中的上游模型。'}
                      </div>
                    )}
                  </div>
                )
              : undefined
          }
        />
      )}
      {testing && (
        <ModelTest
          model={testing}
          close={() => setTesting(null)}
          restoreFocus={restore}
        />
      )}
      {importing && (
        <ModelImport
          close={() => setImporting(false)}
          restoreFocus={restore}
          configure={(model) => {
            setImporting(false)
            void openEditor(model, true)
          }}
        />
      )}
      {editor &&
        (editor === 'new' ? (
          <ModelCreate
            close={() => setEditor(null)}
            restoreFocus={restore}
            saved={() => {
              void client.invalidateQueries({ queryKey: prefix })
              setEditor(null)
              toast.success('模型配置已保存')
            }}
          />
        ) : (
          <ModelEditor
            model={editor}
            close={() => setEditor(null)}
            restoreFocus={restore}
            saved={() => {
              void client.invalidateQueries({ queryKey: prefix })
              setEditor(null)
              toast.success('模型配置已保存')
            }}
          />
        ))}
      {archive && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open && !busy) setArchive(null)
          }}
          title={archive.archived ? '恢复模型' : '归档模型'}
          desc={
            archive.archived
              ? `恢复“${archive.name}”后可继续编辑，模型调用需重新开启。接口、绑定和价格配置仍保留。`
              : `归档“${archive.name}”将关闭模型调用，保留接口、绑定和价格配置。`
          }
          cancelBtnText='取消'
          confirmText={
            busy
              ? '处理中…'
              : archiveStale
                ? '请先刷新'
                : archive.archived
                  ? '恢复'
                  : '归档'
          }
          isLoading={busy}
          disabled={archiveStale || !canWrite}
          handleConfirm={() => void toggleArchive()}
          onCloseAutoFocus={(e) => {
            e.preventDefault()
            restore()
          }}
        >
          {!!error && <RequestError error={error} />}
        </ConfirmDialog>
      )}
    </PageShell>
  )
}

function OperationPrices({
  model,
  render,
}: {
  model: Model
  render: (model: Model) => import('react').ReactNode
}) {
  if (!model.operations) return render(model)
  return (
    <div className='flex flex-col gap-3'>
      {model.operations.map((op) => (
        <div key={op.kind} className='flex flex-col gap-1'>
          <span>{kinds[op.kind ?? 'chat']}</span>
          {render(operationModel(model, op.kind ?? 'chat'))}
        </div>
      ))}
    </div>
  )
}
