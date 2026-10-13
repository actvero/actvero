import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { RefreshCw, Search } from 'lucide-react'
import { api, dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import { ServerTable } from '@/components/data-table/server-table'
import { PageShell } from '@/components/layout/page-shell'
import { RequestError, LoadingState } from '@/components/request-state'
import { CopyButton } from './capability-controls'
import { Choice } from './choice'
import { useMcp } from './shared'

type Activity = Schema['McpActivityView']
const outcomes = { success: '成功', failed: '失败', timeout: '超时' }
const operations: Record<string, string> = {
  tools: '工具调用',
  prompts: '获取提示词',
  resources: '读取资源',
  templates: '读取资源模板',
  discover: '读取能力',
  health_check: '健康检查',
  recovered: '连接恢复',
}
export function ActivityPage({
  category,
  serviceId = '',
}: {
  category: 'call' | 'connection'
  serviceId?: string
}) {
  const { key } = useMcp()
  const [page, setPage] = useState(1)
  const [service, setService] = useState(serviceId || 'all')
  const [result, setResult] = useState('all')
  const [range, setRange] = useState('all')
  const [rangeAnchor, setRangeAnchor] = useState(() => Date.now())
  const [draft, setDraft] = useState('')
  const [q, setQ] = useState('')
  const [detail, setDetail] = useState<Activity | null>(null)
  const since = useMemo(
    () =>
      range === 'all'
        ? ''
        : new Date(rangeAnchor - Number(range) * 86400000).toISOString(),
    [range, rangeAnchor]
  )
  const params = new URLSearchParams({ category, page: String(page) })
  if (service !== 'all') params.set('service_id', service)
  if (result !== 'all') params.set('result', result)
  if (q) params.set('q', q)
  if (since) params.set('since', since)
  const query = useQuery({
    queryKey: [...key, 'activities', params.toString()],
    queryFn: ({ signal }) =>
      api<Schema['McpActivityPage']>(
        `/mcp/activities?${params}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const services = useQuery({
    queryKey: [...key, 'services'],
    queryFn: () => api<Schema['McpServicePage']>('/mcp/services'),
  })
  const serviceOptions = {
    all: '全部服务',
    ...(service !== 'all'
      ? {
          [service]:
            services.data?.items.find((s) => s.id === service)?.name ||
            '所选服务',
        }
      : {}),
    ...Object.fromEntries(
      services.data?.items.map((s) => [s.id, s.display_name || s.name]) ?? []
    ),
  }
  const columns: ColumnDef<Activity>[] = [
    {
      accessorKey: 'created_at',
      header: '时间',
      cell: ({ row }) => dateTime(row.original.created_at),
    },
    {
      accessorKey: 'actor_name',
      header: category === 'call' ? '调用人' : '检查身份',
    },
    { accessorKey: 'service_name', header: '服务' },
    {
      accessorKey: 'operation',
      header: category === 'call' ? '能力' : '事件',
      cell: ({ row }) =>
        row.original.capability ||
        operations[row.original.operation] ||
        row.original.operation,
    },
    {
      accessorKey: 'source',
      header: '来源',
      cell: ({ row }) =>
        row.original.source === 'access_key'
          ? '访问密钥'
          : row.original.source === 'desktop'
            ? '桌面端'
            : row.original.source === 'health'
              ? '后台检查'
              : '控制台',
    },
    {
      accessorKey: 'duration_ms',
      header: '耗时',
      cell: ({ row }) => `${(row.original.duration_ms / 1000).toFixed(2)} s`,
    },
    {
      accessorKey: 'result',
      header: '结果',
      cell: ({ row }) => (
        <Badge
          variant={
            row.original.result === 'success' ? 'success' : 'destructive'
          }
        >
          {outcomes[row.original.result as keyof typeof outcomes] ||
            row.original.result}
        </Badge>
      ),
    },
    {
      id: 'detail',
      header: '',
      cell: ({ row }) => (
        <Button
          variant='ghost'
          size='sm'
          onClick={() => setDetail(row.original)}
        >
          详情
        </Button>
      ),
    },
  ]
  const title = category === 'call' ? '调用记录' : '连接日志'
  return (
    <PageShell
      title={title}
      action={
        <Button
          variant='outline'
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          <RefreshCw data-icon='inline-start' />
          刷新
        </Button>
      }
    >
      <div className='flex flex-wrap items-center gap-3'>
        <div className='w-36'>
          <Choice
            label='时间范围'
            value={range}
            options={{
              all: '全部时间',
              '1': '最近 24 小时',
              '7': '最近 7 天',
              '30': '最近 30 天',
            }}
            onChange={(v) => {
              setRangeAnchor(Date.now())
              setRange(v)
              setPage(1)
            }}
          />
        </div>
        <div className='w-48'>
          <Choice
            label='筛选服务'
            value={service}
            options={serviceOptions}
            onChange={(v) => {
              setService(v)
              setPage(1)
            }}
          />
        </div>
        <div className='w-32'>
          <Choice
            label='筛选结果'
            value={result}
            options={{ all: '全部结果', ...outcomes }}
            onChange={(v) => {
              setResult(v)
              setPage(1)
            }}
          />
        </div>
        <form
          className='flex min-w-0 flex-1 gap-2'
          onSubmit={(e) => {
            e.preventDefault()
            setQ(draft.trim())
            setPage(1)
          }}
        >
          <Input
            aria-label='搜索记录'
            placeholder='搜索服务、能力、人员或请求编号…'
            value={draft}
            maxLength={100}
            onChange={(e) => setDraft(e.target.value)}
          />
          <Button variant='outline' type='submit' aria-label='搜索'>
            <Search />
          </Button>
        </form>
      </div>
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
          empty='暂无符合条件的记录'
        />
      )}
      <Sheet
        open={!!detail}
        onOpenChange={(v) => {
          if (!v) setDetail(null)
        }}
      >
        <SheetContent className='overflow-y-auto sm:max-w-lg'>
          <SheetHeader>
            <SheetTitle>
              {category === 'call' ? '调用详情' : '连接详情'}
            </SheetTitle>
            <SheetDescription>{detail?.service_name}</SheetDescription>
          </SheetHeader>
          {detail && (
            <div className='flex flex-col gap-5 px-4 pb-6'>
              <dl className='grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-4 text-sm'>
                {Object.entries({
                  '能力 / 事件':
                    detail.capability ||
                    operations[detail.operation] ||
                    detail.operation,
                  操作人: detail.actor_name,
                  来源:
                    detail.source === 'access_key'
                      ? '访问密钥'
                      : detail.source === 'desktop'
                        ? '桌面端'
                        : detail.source === 'health'
                          ? '后台健康检查'
                          : '控制台',
                  时间: dateTime(detail.created_at),
                  耗时: `${detail.duration_ms} ms`,
                  结果:
                    outcomes[detail.result as keyof typeof outcomes] ||
                    detail.result,
                  错误分类: detail.error_code || '无',
                  说明: detail.message || '已完成',
                }).map(([label, value]) => (
                  <div key={label} className='contents'>
                    <dt className='text-muted-foreground'>{label}</dt>
                    <dd className='min-w-0 break-words'>{value}</dd>
                  </div>
                ))}
              </dl>
              <div className='flex items-center gap-2'>
                <span className='text-sm text-muted-foreground'>请求编号</span>
                <code className='min-w-0 text-xs break-all'>
                  {detail.request_id}
                </code>
                <CopyButton value={detail.request_id} label='请求编号' />
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </PageShell>
  )
}
