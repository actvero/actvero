import { useDeferredValue, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import {
  Ellipsis,
  Gauge,
  Pencil,
  Plus,
  Power,
  PowerOff,
  Search,
} from 'lucide-react'
import { toast } from 'sonner'
import { ApiError, api, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ServerTable } from '@/components/data-table/server-table'
import { FilterSelect } from '@/components/filter-select'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { channelPath, healthLabels } from './api'
import { ChannelDetail } from './channel-detail'
import { ChannelEditor } from './channel-editor'
import { ListDiagnostic } from './list-diagnostic'
import { useProviderModules } from './provider-modules'
import {
  ChannelAvatar,
  HealthBadge,
  ManualBadge,
  type Channel,
  type Detail,
} from './shared'

type Filters = {
  provider: string
  manual: string
  state: string
  health: string
}
type Action = { kind: 'status' | 'archive' | 'copy'; channel: Channel }
const initialFilters: Filters = {
  provider: '',
  manual: '',
  state: 'current',
  health: '',
}
const healthOptions = Object.entries(healthLabels).map(([value, label]) => ({
  value,
  label,
}))

function subscribeNarrow(callback: () => void) {
  const query = window.matchMedia('(max-width: 639px)')
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

function FilterFields({
  value,
  onChange,
  providers,
}: {
  value: Filters
  onChange: (value: Filters) => void
  providers: { id: string; name: string }[]
}) {
  const change = (key: keyof Filters, item: string) =>
    onChange({ ...value, [key]: item })
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <FilterSelect
        label='供应商'
        value={value.provider}
        onChange={(item) => change('provider', item)}
        options={providers.map((item) => ({
          value: item.id,
          label: item.name,
        }))}
      />
      <FilterSelect
        label='渠道状态'
        value={value.manual}
        onChange={(item) => change('manual', item)}
        options={[
          { value: 'true', label: '已启用' },
          { value: 'false', label: '已停用' },
        ]}
      />
      <FilterSelect
        label='归档'
        value={value.state}
        onChange={(item) => change('state', item || 'all')}
        options={[
          { value: 'current', label: '当前渠道' },
          { value: 'archived', label: '已归档' },
        ]}
      />
      <FilterSelect
        label='健康'
        value={value.health}
        onChange={(item) => change('health', item)}
        options={healthOptions}
      />
    </div>
  )
}

export function ModelChannelsPage() {
  const { csrf, organization } = useOrganization()
  const client = useQueryClient()
  const providers = useProviderModules()
  const narrow = useSyncExternalStore(
    subscribeNarrow,
    () => window.matchMedia('(max-width: 639px)').matches,
    () => false
  )
  const [search, setSearch] = useState('')
  const deferred = useDeferredValue(search)
  const [filters, setFilters] = useState<Filters>(initialFilters)
  const [draftFilters, setDraftFilters] = useState<Filters>(initialFilters)
  const [filterOpen, setFilterOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [batchTarget, setBatchTarget] = useState<boolean | null>(null)
  const [batchResults, setBatchResults] = useState<
    Schema['ChannelStatusResult'][] | null
  >(null)
  const [batchError, setBatchError] = useState<unknown>(null)
  const [editor, setEditor] = useState<Channel | 'new' | null>(null)
  const [copyFrom, setCopyFrom] = useState<Detail | null>(null)
  const [detail, setDetail] = useState<{ id: string; tab: string } | null>(null)
  const [returnDetail, setReturnDetail] = useState<{
    id: string
    tab: string
  } | null>(null)
  const [action, setAction] = useState<Action | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const addButton = useRef<HTMLButtonElement>(null)
  const trigger = useRef<HTMLElement | null>(null)
  const prefix = ['organization', organization.tenant_id, 'model-channels']
  const params = new URLSearchParams({
    q: deferred,
    state: filters.state,
    page: String(page),
  })
  if (filters.provider) params.set('provider', filters.provider)
  if (filters.manual) params.set('manual_enabled', filters.manual)
  if (filters.health) params.set('health_summary', filters.health)
  const query = useQuery({
    queryKey: [...prefix, 'list', params.toString()],
    queryFn: ({ signal }) =>
      api<Schema['ChannelPage']>(
        '/llm/channels?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const selectable =
    query.data?.items.filter((channel) => !channel.archived) ?? []
  const chosen = selectable.filter((channel) => selected.has(channel.id))
  const emptyMessage =
    search ||
    filters.provider ||
    filters.manual ||
    filters.health ||
    filters.state !== 'current'
      ? '没有匹配的渠道'
      : '还没有渠道。选择供应商，开始接入模型。'
  function changed(channel: Detail) {
    client.setQueryData([...prefix, channel.id], channel)
    void client.invalidateQueries({ queryKey: prefix })
  }
  function refresh() {
    void client.invalidateQueries({ queryKey: prefix })
  }
  function setActiveFilters(value: Filters) {
    setFilters(value)
    setPage(1)
    setSelected(new Set())
    setBatchResults(null)
  }
  function remember() {
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
  }
  function restore() {
    if (trigger.current?.isConnected) trigger.current.focus()
    else addButton.current?.focus()
  }
  function openDetail(channel: Channel, tab = 'connection') {
    remember()
    setReturnDetail(null)
    setDetail({ id: channel.id, tab })
  }
  function openAction(kind: Action['kind'], channel: Channel) {
    if (!detail) remember()
    setReturnDetail(detail)
    setDetail(null)
    setError(null)
    setAction({ kind, channel })
  }
  function closeAction() {
    setAction(null)
    if (returnDetail) {
      setDetail(returnDetail)
      setReturnDetail(null)
    }
  }
  function closeEditor() {
    setEditor(null)
    setCopyFrom(null)
    if (returnDetail) {
      setDetail(returnDetail)
      setReturnDetail(null)
    }
  }
  function toggleSelected(id: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
    setBatchResults(null)
  }
  async function confirmAction() {
    if (!action) return
    setBusy(true)
    setError(null)
    try {
      if (action.kind === 'copy') {
        setCopyFrom(await api<Detail>(channelPath(action.channel.id), 'GET'))
        setEditor('new')
        setAction(null)
      } else {
        const path =
          channelPath(action.channel.id) +
          (action.kind === 'status' ? '/status' : '/archive')
        const payload =
          action.kind === 'status'
            ? {
                version: action.channel.version,
                manual_enabled: !action.channel.manual_enabled,
              }
            : {
                version: action.channel.version,
                archived: !action.channel.archived,
              }
        changed(await api<Detail>(path, 'PUT', payload, csrf))
        toast.success(
          action.kind === 'status'
            ? action.channel.manual_enabled
              ? '渠道已停用'
              : '渠道已启用'
            : action.channel.archived
              ? '渠道已恢复'
              : '渠道已归档'
        )
        closeAction()
      }
    } catch (e) {
      setError(e)
      refresh()
    } finally {
      setBusy(false)
    }
  }
  async function confirmBatch() {
    if (batchTarget === null || !chosen.length) return
    setBusy(true)
    setBatchError(null)
    try {
      const response = await api<Schema['ChannelStatusBatchResult']>(
        '/llm/channels/status-batch',
        'POST',
        {
          items: chosen.map((channel) => ({
            id: channel.id,
            version: channel.version,
            manual_enabled: batchTarget,
          })),
        },
        csrf
      )
      setBatchResults(response.items)
      setSelected((current) => {
        const next = new Set(current)
        response.items
          .filter((item) => item.status === 'updated')
          .forEach((item) => next.delete(item.id))
        return next
      })
      setBatchTarget(null)
      refresh()
    } catch (e) {
      setBatchError(e)
      refresh()
    } finally {
      setBusy(false)
    }
  }
  function more(channel: Channel) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant='ghost'
            size='icon'
            aria-label={`${channel.name}的更多操作`}
          >
            <Ellipsis />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align='end'
          onCloseAutoFocus={(event) => {
            if (editor || action || detail) event.preventDefault()
          }}
        >
          <DropdownMenuGroup>
            <DropdownMenuItem onSelect={() => openDetail(channel)}>
              查看详情
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => openAction('copy', channel)}>
              复制为新渠道
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => openAction('archive', channel)}>
              {channel.archived ? '恢复渠道' : '归档渠道'}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }
  function quickActions(channel: Channel) {
    const actions = [
      {
        label: '测试',
        icon: Gauge,
        run: () => openDetail(channel, 'test'),
      },
      {
        label: '编辑',
        icon: Pencil,
        run: () => {
          remember()
          setEditor(channel)
        },
      },
      {
        label: channel.manual_enabled ? '停用' : '启用',
        icon: channel.manual_enabled ? PowerOff : Power,
        run: () => openAction('status', channel),
      },
    ]
    return actions.map(({ label, icon: Icon, run }) => (
      <Tooltip key={label} delayDuration={250}>
        <TooltipTrigger asChild>
          <Button
            type='button'
            size='icon'
            variant='ghost'
            aria-label={label}
            disabled={channel.archived}
            onClick={run}
          >
            <Icon />
          </Button>
        </TooltipTrigger>
        <TooltipContent
          sideOffset={6}
          className='pointer-events-none data-[state=closed]:animate-none'
        >
          {label}
        </TooltipContent>
      </Tooltip>
    ))
  }
  const columns: ColumnDef<Channel>[] = [
    {
      id: 'select',
      header: () => (
        <Checkbox
          aria-label='选择当前页'
          checked={selectable.length > 0 && chosen.length === selectable.length}
          onCheckedChange={(checked) => {
            setSelected(
              checked
                ? new Set(selectable.map((channel) => channel.id))
                : new Set()
            )
            setBatchResults(null)
          }}
        />
      ),
      cell: ({ row: { original: channel } }) =>
        channel.archived ? null : (
          <Checkbox
            aria-label={`选择${channel.name}`}
            checked={selected.has(channel.id)}
            onCheckedChange={(checked) =>
              toggleSelected(channel.id, checked === true)
            }
          />
        ),
    },
    {
      id: 'name',
      header: '渠道 / 供应商',
      cell: ({ row: { original: channel } }) => (
        <div className='flex min-w-60 items-center gap-3'>
          <ChannelAvatar channel={channel} />
          <div className='flex min-w-0 flex-col'>
            <Button
              variant='link'
              className='h-auto max-w-64 justify-start p-0'
              onClick={() => openDetail(channel)}
            >
              <span className='truncate'>{channel.name}</span>
            </Button>
            <span className='text-xs text-muted-foreground'>
              {providers.data?.find((item) => item.id === channel.provider)
                ?.name ?? channel.provider}
            </span>
          </div>
        </div>
      ),
    },
    {
      id: 'manual',
      header: '渠道状态',
      cell: ({ row }) => <ManualBadge channel={row.original} />,
    },
    {
      id: 'health',
      header: '绑定健康',
      cell: ({ row }) => <HealthBadge channel={row.original} />,
    },
    {
      id: 'models',
      header: '启用绑定 / 库存',
      cell: ({ row: { original: channel } }) => (
        <div className='flex flex-col items-start'>
          <span>
            {Object.values(channel.health_summary?.health_counts ?? {}).reduce(
              (sum, count) => sum + count,
              0
            )}{' '}
            个绑定
          </span>
          <Button
            variant='link'
            size='sm'
            className='h-auto justify-start p-0'
            onClick={() => openDetail(channel, 'models')}
          >
            {channel.model_count} 个登记模型
          </Button>
        </div>
      ),
    },
    {
      id: 'diagnostic',
      header: '最近测试',
      cell: ({ row }) => <ListDiagnostic channel={row.original} />,
    },
    {
      id: 'actions',
      header: () => <span className='sr-only'>操作</span>,
      cell: ({ row: { original: channel } }) => (
        <div className='flex items-center gap-1'>
          {quickActions(channel)}
          {more(channel)}
        </div>
      ),
    },
  ]
  return (
    <PageShell
      title='渠道管理'
      action={
        <Button
          ref={addButton}
          onClick={() => {
            remember()
            setCopyFrom(null)
            setEditor('new')
          }}
        >
          <Plus />
          添加渠道
        </Button>
      }
    >
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex min-w-0 flex-wrap items-center gap-3'>
          <div className='flex items-center gap-2'>
            <Search className='size-4 text-muted-foreground' />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(1)
                setSelected(new Set())
              }}
              aria-label='搜索渠道'
              placeholder='搜索名称或 Base URL'
              className='w-56 max-w-full sm:w-64'
            />
          </div>
          <div className='hidden lg:block'>
            <FilterFields
              value={filters}
              onChange={setActiveFilters}
              providers={providers.data ?? []}
            />
          </div>
          <Button
            variant='outline'
            className='lg:hidden'
            onClick={() => {
              setDraftFilters(filters)
              setFilterOpen(true)
            }}
          >
            筛选
          </Button>
          <Button variant='outline' onClick={refresh}>
            刷新
          </Button>
        </div>
        {query.data && (
          <span className='text-sm text-muted-foreground'>
            共 {query.data.total} 个渠道
          </span>
        )}
      </div>
      {chosen.length > 0 && (
        <div className='flex flex-wrap items-center gap-2'>
          <span className='text-sm'>
            当前页已选择 {chosen.length} 项（最多 50 项）
          </span>
          <Button
            size='sm'
            variant='outline'
            onClick={() => {
              setBatchError(null)
              setBatchTarget(true)
            }}
          >
            批量启用
          </Button>
          <Button
            size='sm'
            variant='outline'
            onClick={() => {
              setBatchError(null)
              setBatchTarget(false)
            }}
          >
            批量停用
          </Button>
          <Button
            size='sm'
            variant='ghost'
            onClick={() => setSelected(new Set())}
          >
            取消选择
          </Button>
        </div>
      )}
      {batchResults && (
        <Alert>
          <AlertTitle>批量操作结果</AlertTitle>
          <AlertDescription>
            <ul className='flex flex-col gap-1'>
              {batchResults.map((item) => (
                <li key={item.id}>
                  {query.data?.items.find((channel) => channel.id === item.id)
                    ?.name ?? item.id}
                  ：
                  {
                    {
                      updated: '已更新',
                      conflict: '版本冲突，请刷新',
                      not_found: '渠道不存在',
                      archived: '已归档',
                    }[item.status]
                  }
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
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
          onPage={(next) => {
            setPage(next)
            setSelected(new Set())
          }}
          empty={emptyMessage}
          renderItems={
            narrow
              ? (items) => (
                  <div className='flex min-w-0 flex-col gap-3'>
                    {items.length ? (
                      items.map((channel) => (
                        <Card
                          key={channel.id}
                          density='compact'
                          className='min-w-0'
                        >
                          <CardHeader layout='row' className='min-w-0'>
                            {!channel.archived && (
                              <Checkbox
                                aria-label={`选择${channel.name}`}
                                checked={selected.has(channel.id)}
                                onCheckedChange={(checked) =>
                                  toggleSelected(channel.id, checked === true)
                                }
                              />
                            )}
                            <ChannelAvatar channel={channel} />
                            <CardTitle size='body' className='min-w-0 truncate'>
                              {channel.name}
                            </CardTitle>
                            {more(channel)}
                          </CardHeader>
                          <CardContent className='flex min-w-0 flex-col gap-2'>
                            <span className='text-sm text-muted-foreground'>
                              {providers.data?.find(
                                (item) => item.id === channel.provider
                              )?.name ?? channel.provider}
                            </span>
                            <div className='flex flex-wrap gap-2'>
                              <ManualBadge channel={channel} />
                              <HealthBadge channel={channel} />
                            </div>
                            <span className='text-sm'>
                              {Object.values(
                                channel.health_summary?.health_counts ?? {}
                              ).reduce((sum, count) => sum + count, 0)}{' '}
                              个启用绑定 · {channel.model_count} 个登记模型
                            </span>
                            <div className='flex flex-wrap items-center gap-2 text-sm'>
                              <span>最近测试</span>
                              <ListDiagnostic channel={channel} />
                            </div>
                          </CardContent>
                          <CardFooter className='flex flex-wrap gap-2'>
                            <Button
                              size='sm'
                              variant='outline'
                              onClick={() => openDetail(channel)}
                            >
                              查看详情
                            </Button>
                            <Button
                              size='sm'
                              variant='outline'
                              onClick={() => openDetail(channel, 'models')}
                            >
                              库存
                            </Button>
                            {quickActions(channel)}
                          </CardFooter>
                        </Card>
                      ))
                    ) : (
                      <p className='text-sm text-muted-foreground'>
                        {emptyMessage}
                      </p>
                    )}
                  </div>
                )
              : undefined
          }
        />
      )}
      <Sheet open={filterOpen} onOpenChange={setFilterOpen}>
        <SheetContent className='w-full sm:max-w-sm'>
          <SheetHeader>
            <SheetTitle>筛选渠道</SheetTitle>
            <SheetDescription>选择筛选条件后应用到渠道列表。</SheetDescription>
          </SheetHeader>
          <FilterFields
            value={draftFilters}
            onChange={setDraftFilters}
            providers={providers.data ?? []}
          />
          <SheetFooter className='flex-row gap-2'>
            <Button
              variant='outline'
              onClick={() => setDraftFilters(initialFilters)}
            >
              重置
            </Button>
            <Button
              onClick={() => {
                setActiveFilters(draftFilters)
                setFilterOpen(false)
              }}
            >
              应用筛选
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
      {editor && (
        <ChannelEditor
          channel={editor === 'new' ? undefined : editor}
          copyFrom={copyFrom ?? undefined}
          close={closeEditor}
          restoreFocus={restore}
          saved={(channel) => {
            changed(channel)
            if (editor === 'new') {
              setSearch('')
              setActiveFilters(initialFilters)
            }
            closeEditor()
            toast.success('渠道已保存')
          }}
        />
      )}
      {detail && (
        <ChannelDetail
          key={detail.id}
          id={detail.id}
          initialTab={detail.tab}
          close={() => setDetail(null)}
          changed={changed}
          edit={(channel) => {
            setReturnDetail(detail)
            setDetail(null)
            setEditor(channel)
          }}
          copy={(channel) => openAction('copy', channel)}
          status={(channel) => openAction('status', channel)}
          archive={(channel) => openAction('archive', channel)}
          onTabChange={(tab) =>
            setDetail((current) => (current ? { ...current, tab } : current))
          }
          restoreFocus={restore}
        />
      )}
      {action && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open && !busy) closeAction()
          }}
          title={
            action.kind === 'copy'
              ? '复制为新渠道'
              : action.kind === 'status'
                ? action.channel.manual_enabled
                  ? '停用渠道'
                  : '启用渠道'
                : action.channel.archived
                  ? '恢复渠道'
                  : '归档渠道'
          }
          desc={
            action.kind === 'copy'
              ? `将“${action.channel.name}”复制为新草稿。新渠道不会复制密钥，请重新填写。`
              : action.kind === 'status'
                ? `确认${action.channel.manual_enabled ? '停用' : '启用'}“${action.channel.name}”？渠道状态与绑定健康独立。`
                : `确认${action.channel.archived ? '恢复' : '归档'}“${action.channel.name}”？`
          }
          cancelBtnText='取消'
          confirmText={busy ? '处理中…' : '确认'}
          isLoading={busy}
          disabled={
            error instanceof ApiError &&
            (error.status === 403 || error.status === 409)
          }
          handleConfirm={() => void confirmAction()}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            if (!returnDetail) restore()
          }}
        >
          {!!error && (
            <div className='flex flex-col gap-2'>
              <RequestError error={error} />
              <Button variant='outline' onClick={refresh}>
                刷新后关闭并重新操作，保留筛选
              </Button>
            </div>
          )}
        </ConfirmDialog>
      )}
      {batchTarget !== null && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open && !busy) setBatchTarget(null)
          }}
          title={batchTarget ? '批量启用渠道' : '批量停用渠道'}
          desc={`对当前页选中的 ${chosen.length} 个渠道逐项执行，冲突项需刷新后重试。`}
          cancelBtnText='取消'
          confirmText={busy ? '处理中…' : '确认'}
          isLoading={busy}
          disabled={
            batchError instanceof ApiError &&
            (batchError.status === 403 || batchError.status === 409)
          }
          handleConfirm={() => void confirmBatch()}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            restore()
          }}
        >
          {!!batchError && (
            <div className='flex flex-col gap-2'>
              <RequestError error={batchError} />
              <Button variant='outline' onClick={refresh}>
                刷新列表，保留筛选
              </Button>
            </div>
          )}
        </ConfirmDialog>
      )}
    </PageShell>
  )
}
