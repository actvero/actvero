import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { RefreshCw } from 'lucide-react'
import { api, ApiError, dateTime, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ServerTable } from '@/components/data-table/server-table'
import { FilterSelect } from '@/components/filter-select'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { Points, QuotaWindow } from './quota-windows'

type Entry = Schema['SettlementView']
const states: Record<string, string> = {
  reserved: '预占中',
  review: '待核对',
  settled: '已结算',
  released: '已释放',
}
const results: Record<string, string> = {
  success: '成功',
  failed: '失败',
  interrupted: '中断',
  cancelled: '已取消',
  unknown: '未知',
}
const safeReasons: Record<string, string> = {
  access_changed: '调用期间权限发生变化',
  configuration_changed: '调用期间配置发生变化',
  model_unavailable: '模型暂不可用',
  stream_started: '流式响应中断',
  caller_cancelled: '调用方已取消',
  upstream_timeout: '上游响应超时',
  upstream_error: '上游请求失败',
  no_available_route: '当前没有可用路线',
}
const kinds: Record<string, string> = {
  chat: '对话',
  embedding: '向量',
  rerank: '重排',
  image_generation: '图片生成',
}
function EntryStatus({ entry }: { entry: Entry }) {
  const settlement = entry.settlement_status ?? entry.status
  const result = entry.result_status ?? 'unknown'
  return (
    <div className='flex flex-wrap gap-1'>
      <Badge variant={result === 'success' ? 'secondary' : 'outline'}>
        结果：{results[result] ?? '未知'}
      </Badge>
      <Badge variant={settlement === 'review' ? 'outline' : 'secondary'}>
        结算：{states[settlement] ?? '未知'}
      </Badge>
    </div>
  )
}

function EntryPoints({ entry }: { entry: Entry }) {
  const settlement = entry.settlement_status ?? entry.status
  if (settlement === 'reserved' || settlement === 'review')
    return (
      <span>
        占用 <Points value={entry.reserved_points} />
      </span>
    )
  if (settlement === 'released')
    return <span>平台已释放；不代表上游用量为零</span>
  return entry.points === null ? (
    <span>消耗积分待确认</span>
  ) : (
    <span>
      已用 <Points value={entry.points} />
    </span>
  )
}

function EntryReason({ entry }: { entry: Entry }) {
  const code = entry.terminal_reason
  if (!code) return null
  return (
    <span className='text-xs text-muted-foreground'>
      {safeReasons[code] ?? '终止原因待确认'}
    </span>
  )
}

const usageFields = [
  'input_tokens',
  'output_tokens',
  'cache_read_tokens',
  'cache_write_5m_tokens',
  'cache_write_1h_tokens',
  'input_characters',
  'search_units',
  'image_count',
  'input',
  'output',
  'cache_read',
  'cache_write_5m',
  'cache_write_1h',
] as const

function usageEvidenceLabel(entry: Entry) {
  const usage = entry.usage
  const hasQuantity = usageFields.some((field) => {
    const value = usage?.[field]
    return typeof value === 'number' && Number.isFinite(value) && value >= 0
  })
  if (!hasQuantity) return '用量未知'
  if (
    usage.source === 'upstream' ||
    usage.source === 'validated_input' ||
    usage.source === 'confirmed_delivery'
  )
    return '已记录用量证据'
  if (usage.source === 'unknown') return '已记录数量，来源待确认'
  return '已记录数量，来源未记录'
}
const columns: ColumnDef<Entry>[] = [
  {
    accessorKey: 'model_name',
    header: '模型',
    cell: ({ row }) => (
      <div className='flex min-w-32 flex-col gap-1'>
        <span>{row.original.model_name}</span>
        <span className='text-xs text-muted-foreground'>
          {kinds[row.original.kind] ?? row.original.kind}
        </span>
      </div>
    ),
  },
  {
    id: 'state',
    header: '结果 / 结算',
    cell: ({ row }) => <EntryStatus entry={row.original} />,
  },
  {
    id: 'points',
    header: '积分',
    cell: ({ row }) => <EntryPoints entry={row.original} />,
  },
  {
    id: 'reason',
    header: '说明',
    cell: ({ row }) => (
      <div className='flex flex-col gap-1'>
        <EntryReason entry={row.original} />
        <span className='text-xs text-muted-foreground'>
          {usageEvidenceLabel(row.original)}
        </span>
      </div>
    ),
  },
  {
    id: 'date',
    header: '调用时间',
    cell: ({ row }) => dateTime(row.original.created_at),
  },
]

export function MyUsagePage() {
  const { organization, user } = useOrganization()
  const client = useQueryClient()
  const [state, setState] = useState('')
  const [page, setPage] = useState(1)
  const prefix = [
    'organization',
    organization.tenant_id,
    'quota',
    'self',
    user.id,
  ]
  const quota = useQuery({
    queryKey: [...prefix, 'windows'],
    queryFn: ({ signal }) =>
      api<Schema['QuotaView']>(
        '/account/llm/quota',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const params = new URLSearchParams({ state, page: String(page) }).toString()
  const usage = useQuery({
    queryKey: [...prefix, 'history', params],
    queryFn: ({ signal }) =>
      api<Schema['SettlementPage']>(
        '/account/llm/usage?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const accessLost =
    (quota.error instanceof ApiError &&
      [401, 403].includes(quota.error.status)) ||
    (usage.error instanceof ApiError && [401, 403].includes(usage.error.status))
  return (
    <PageShell
      title='我的用量'
      action={
        <div className='flex flex-wrap gap-2'>
          <Button asChild variant='outline'>
            <Link to='/my-models' search={{ q: '', operation: '', page: 1 }}>
              可用模型
            </Link>
          </Button>
          <Button asChild variant='outline'>
            <Link to='/my-access-keys'>访问密钥</Link>
          </Button>
          <Button
            variant='outline'
            disabled={quota.isFetching || usage.isFetching}
            onClick={() => void client.invalidateQueries({ queryKey: prefix })}
          >
            <RefreshCw />
            刷新
          </Button>
        </div>
      }
    >
      {accessLost ? (
        <RequestError error={quota.error ?? usage.error} />
      ) : (
        <>
          {quota.isPending ? (
            <LoadingState />
          ) : quota.isError ? (
            <RequestError
              error={quota.error}
              retry={() => void quota.refetch()}
            />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>模型额度</CardTitle>
                <CardDescription>
                  {quota.data.status === 'active'
                    ? `当前策略 · ${String(quota.data.policy?.name ?? '—')}`
                    : '尚未配置额度策略，请联系管理员。'}
                </CardDescription>
              </CardHeader>
              {quota.data.windows.length > 0 && (
                <CardContent
                  className={cn(
                    'grid gap-8 md:grid-cols-2',
                    quota.data.windows.length > 2 && 'xl:grid-cols-3'
                  )}
                >
                  {quota.data.windows.map((w) => (
                    <QuotaWindow
                      key={`${w.rule.kind}-${w.rule.hours ?? 'week'}`}
                      window={w}
                    />
                  ))}
                </CardContent>
              )}
            </Card>
          )}
          <p className='text-sm text-muted-foreground'>
            预占和待核对仍占用成员额度；结果成功不一定已结算。刷新不会启动新的小时窗口。
          </p>
          <section
            className='flex min-w-0 flex-col gap-4'
            aria-label='调用记录'
          >
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <h2 className='text-lg font-semibold'>调用记录</h2>
              <FilterSelect
                label='结算状态'
                value={state}
                onChange={(value) => {
                  setState(value)
                  setPage(1)
                }}
                options={Object.entries(states).map(([value, label]) => ({
                  value,
                  label,
                }))}
              />
            </div>
            {usage.isPending ? (
              <LoadingState />
            ) : usage.isError ? (
              <RequestError
                error={usage.error}
                retry={() => void usage.refetch()}
              />
            ) : (
              <>
                <div className='hidden min-w-0 md:block'>
                  <ServerTable
                    items={usage.data.items}
                    columns={columns}
                    total={usage.data.total}
                    page={page}
                    onPage={setPage}
                    empty='暂无调用记录'
                  />
                </div>
                <div className='grid min-w-0 gap-3 md:hidden'>
                  {!usage.data.items.length ? (
                    <p className='text-sm text-muted-foreground'>
                      暂无调用记录
                    </p>
                  ) : (
                    usage.data.items.map((entry) => (
                      <Card key={entry.id} className='min-w-0'>
                        <CardHeader>
                          <CardTitle size='body' className='break-words'>
                            {entry.model_name} ·{' '}
                            {kinds[entry.kind] ?? entry.kind}
                          </CardTitle>
                          <CardDescription>
                            {dateTime(entry.created_at)}
                          </CardDescription>
                        </CardHeader>
                        <CardContent className='grid min-w-0 gap-2 text-sm'>
                          <EntryStatus entry={entry} />
                          <EntryPoints entry={entry} />
                          <EntryReason entry={entry} />
                          <span className='text-muted-foreground'>
                            {usageEvidenceLabel(entry)}
                          </span>
                        </CardContent>
                      </Card>
                    ))
                  )}
                  <div className='flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground'>
                    <span>
                      共 {usage.data.total} 条 · 第 {page} 页
                    </span>
                    <div className='flex gap-2'>
                      <Button
                        type='button'
                        size='sm'
                        variant='outline'
                        disabled={page <= 1}
                        onClick={() => setPage(page - 1)}
                      >
                        上一页
                      </Button>
                      <Button
                        type='button'
                        size='sm'
                        variant='outline'
                        disabled={page * 20 >= usage.data.total}
                        onClick={() => setPage(page + 1)}
                      >
                        下一页
                      </Button>
                    </div>
                  </div>
                </div>
              </>
            )}
          </section>
        </>
      )}
    </PageShell>
  )
}
