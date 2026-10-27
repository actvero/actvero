import { lazy, Suspense, useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Plus, Search, Server } from 'lucide-react'
import { toast } from 'sonner'
import { messageOf } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from '@/components/ui/empty'
import { Tabs } from '@/components/ui/tabs'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  gateway,
  splitNames,
  useGateway,
  useGatewayRefresh,
  type Channel,
  type Page,
} from './api'
import {
  ChannelList,
  ChannelListToolbar,
  ChannelPagination,
} from './channel-list'
import { initialChannelFilters } from './channel-list-state'
import { GatewayLogsButton } from './logs'
import { NativeLanguage } from './native-language'
import { EditorDialog } from './shared'

const NativeChannelEditor = lazy(() =>
  import('./native-editor').then((module) => ({
    default: module.NativeChannelEditor,
  }))
)

const NativeChannelTest = lazy(() =>
  import('./native-test').then((module) => ({
    default: module.NativeChannelTest,
  }))
)

export function GatewayChannels() {
  return (
    <NativeLanguage>
      <GatewayChannelsContent />
    </NativeLanguage>
  )
}
function GatewayChannelsContent() {
  const { csrf } = useOrganization()
  const refresh = useGatewayRefresh()
  const [filters, setFilters] = useState(initialChannelFilters)
  const [search, setSearch] = useState({ q: '', model: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [view, setView] = useState(() =>
    localStorage.getItem('actvero:gateway-channels:view') === 'cards'
      ? 'cards'
      : 'table'
  )
  const [editor, setEditor] = useState<Channel | 'new' | null>(null)
  const [test, setTest] = useState<Channel | null>(null)
  const [models, setModels] = useState<Channel | null>(null)
  const [removing, setRemoving] = useState<Channel | null>(null)
  const [visibility, setVisibility] = useState<Record<string, boolean>>({
    models: false,
  })
  useEffect(() => {
    const timer = window.setTimeout(
      () => setSearch({ q: filters.q, model: filters.model }),
      250
    )
    return () => window.clearTimeout(timer)
  }, [filters.q, filters.model])
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    q: search.q,
    model: search.model,
    sort_by: filters.sort,
    sort_order: filters.order,
    ...(filters.state !== 'all' ? { state: filters.state } : {}),
    ...(filters.type !== 'all' ? { type: filters.type } : {}),
    ...(filters.group !== 'all' ? { group: filters.group } : {}),
  })
  const query = useGateway<Page<Channel>>(`/channels?${params}`, true, true)
  const options = useGateway<{
    base_urls: Record<string, string>
    groups: string[]
    quota_per_unit?: number | null
  }>('/channel-options')
  const status = useMutation({
    mutationFn: (channel: Channel) =>
      gateway(
        `/channels/${channel.id}/status`,
        'POST',
        { status: channel.status === 1 ? 2 : 1 },
        csrf
      ),
    onSuccess: async (_, channel) => {
      toast.success(channel.status === 1 ? '渠道已停用' : '渠道已启用')
      await refresh()
    },
  })
  const quickTest = useMutation({
    mutationFn: (channel: Channel) =>
      gateway<{ time?: number }>(
        `/channels/${channel.id}/test`,
        'POST',
        {},
        csrf
      ),
    onSuccess: (data, channel) =>
      toast.success(
        `${channel.name} 测试成功${typeof data.time === 'number' ? ` · ${Math.round(data.time * 1000)} 毫秒` : ''}`
      ),
    onError: (error, channel) =>
      toast.error(`${channel.name}：${messageOf(error)}`),
    onSettled: () => refresh(),
  })
  const filtered = !!(
    filters.q ||
    filters.model ||
    [filters.state, filters.type, filters.group].some(
      (value) => value !== 'all'
    )
  )
  return (
    <PageShell
      compact
      fixedContent
      title='渠道'
      titleAfter={
        query.data && <Badge variant='secondary'>{query.data.total}</Badge>
      }
      action={
        <div className='flex flex-wrap items-center gap-2'>
          <GatewayLogsButton />
          <Button onClick={() => setEditor('new')}>
            <Plus data-icon='inline-start' />
            添加渠道
          </Button>
        </div>
      }
    >
      <Tabs
        value={view}
        onValueChange={(value) => {
          setView(value)
          localStorage.setItem('actvero:gateway-channels:view', value)
        }}
        className='min-h-0 min-w-0 flex-1 gap-4'
      >
        <ChannelListToolbar
          visibility={visibility}
          onVisibility={setVisibility}
          filters={filters}
          onChange={(value) => {
            setFilters(value)
            setPage(1)
          }}
          groups={options.data?.groups ?? []}
          fetching={query.isFetching}
          onRefresh={() => void query.refetch()}
        />
        {status.error && <RequestError error={status.error} />}
        <div className='min-h-0 flex-1 overflow-auto' aria-label='渠道列表'>
          {query.isPending ? (
            <LoadingState />
          ) : query.error ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : query.data.items.length ? (
            <>
              <ChannelList
                items={query.data.items}
                quotaPerUnit={options.data?.quota_per_unit}
                visibility={visibility}
                onVisibility={setVisibility}
                sorting={[{ id: filters.sort, desc: filters.order === 'desc' }]}
                onSort={(next) => {
                  const order = next[0] ?? { id: 'priority', desc: true }
                  setFilters({
                    ...filters,
                    sort: order.id,
                    order: order.desc ? 'desc' : 'asc',
                  })
                  setPage(1)
                }}
                testingId={quickTest.isPending ? quickTest.variables.id : null}
                onQuickTest={(channel) => quickTest.mutate(channel)}
                onDelete={setRemoving}
                pendingId={status.isPending ? status.variables.id : null}
                onEdit={setEditor}
                onTest={setTest}
                onStatus={(channel) => status.mutate(channel)}
                onModels={setModels}
              />
            </>
          ) : (
            <Empty className='min-h-64 rounded-lg border border-dashed'>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  {filtered ? <Search /> : <Server />}
                </EmptyMedia>
                <EmptyTitle>
                  {page > 1
                    ? '这一页没有渠道'
                    : filtered
                      ? '没有匹配的渠道'
                      : '还没有渠道'}
                </EmptyTitle>
                <EmptyDescription>
                  {filtered
                    ? '尝试其他关键词，或清除筛选条件。'
                    : '添加供应商连接，开始配置模型与路由。'}
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button
                  variant={filtered ? 'outline' : 'default'}
                  onClick={() =>
                    page > 1
                      ? setPage(1)
                      : filtered
                        ? setFilters(initialChannelFilters)
                        : setEditor('new')
                  }
                >
                  {page > 1 ? '返回首页' : filtered ? '清除筛选' : '添加渠道'}
                </Button>
              </EmptyContent>
            </Empty>
          )}
        </div>
        {query.data && query.data.total > 0 && (
          <ChannelPagination
            page={page}
            pageSize={pageSize}
            total={query.data.total}
            fetching={query.isFetching}
            onPage={setPage}
            onPageSize={(value) => {
              setPageSize(value)
              setPage(1)
            }}
          />
        )}
      </Tabs>
      {editor && (
        <Suspense fallback={<LoadingState />}>
          <NativeChannelEditor
            key={editor === 'new' ? 'new' : editor.id}
            channel={editor === 'new' ? undefined : editor}
            onClose={() => setEditor(null)}
          />
        </Suspense>
      )}
      {test && (
        <Suspense fallback={<LoadingState />}>
          <NativeChannelTest channel={test} onClose={() => setTest(null)} />
        </Suspense>
      )}
      {removing && (
        <ChannelDeleteDialog
          channel={removing}
          onClose={() => setRemoving(null)}
        />
      )}
      {models && (
        <EditorDialog
          title={`${models.name} 的模型`}
          description={`共 ${splitNames(models.models).length} 个模型`}
          onClose={() => setModels(null)}
        >
          <div className='flex max-h-80 flex-wrap gap-2 overflow-y-auto'>
            {splitNames(models.models).map((model) => (
              <Badge
                key={model}
                variant='outline'
                className='max-w-full font-mono break-all whitespace-normal'
              >
                {model}
              </Badge>
            ))}
          </div>
        </EditorDialog>
      )}
    </PageShell>
  )
}

function ChannelDeleteDialog({
  channel,
  onClose,
}: {
  channel: Channel
  onClose: () => void
}) {
  const { csrf } = useOrganization()
  const refresh = useGatewayRefresh()
  const remove = useMutation({
    mutationFn: () =>
      gateway(`/channels/${channel.id}`, 'DELETE', undefined, csrf),
    onSuccess: async () => {
      await refresh()
      toast.success('渠道已删除')
      onClose()
    },
  })
  return (
    <EditorDialog
      title='删除渠道'
      description={`确认删除渠道“${channel.name}”？此操作无法撤销。`}
      onClose={onClose}
    >
      {remove.error && <RequestError error={remove.error} />}
      <div className='flex justify-end gap-2'>
        <Button variant='outline' onClick={onClose} disabled={remove.isPending}>
          取消
        </Button>
        <Button
          variant='destructive'
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          {remove.isPending ? '正在删除…' : '删除'}
        </Button>
      </div>
    </EditorDialog>
  )
}
