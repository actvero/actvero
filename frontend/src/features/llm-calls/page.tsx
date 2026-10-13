import { useRef, useState, useSyncExternalStore } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, ApiError, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ServerTable } from '@/components/data-table/server-table'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { CallDetailSheet } from './call-detail'
import { CallFilters } from './call-filters'
import { operations, queryFor, results, settlements } from './filters'
import { searchFromFilters, searchToFilters, type CallSearch } from './search'
import { timeInZone } from './time'

type Call = Schema['CallPage']['items'][number]

function subscribeNarrow(callback: () => void) {
  const query = window.matchMedia('(max-width: 639px)')
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

function callBadges(call: Call) {
  return (
    <div className='flex flex-wrap gap-1'>
      <Badge
        variant={call.result_status === 'success' ? 'secondary' : 'outline'}
      >
        结果：{results[call.result_status]}
      </Badge>
      <Badge variant='outline'>
        结算：{settlements[call.settlement_status]}
      </Badge>
    </div>
  )
}

export function LlmCallsPage({ search }: { search: CallSearch }) {
  const { organization, user } = useOrganization()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [permissionLost, setPermissionLost] = useState<ApiError | null>(null)
  const [detailId, setDetailId] = useState<string | null>(
    () => search.call_id || null
  )
  const trigger = useRef<HTMLElement | null>(null)
  const narrow = useSyncExternalStore(
    subscribeNarrow,
    () => window.matchMedia('(max-width: 639px)').matches,
    () => false
  )
  const zoneQuery = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'quota-default-timezone',
    ],
    enabled: !search.timezone,
    queryFn: ({ signal }) =>
      api<Schema['QuotaPolicyPage']>(
        '/quota/policies?state=current&page=1',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const zone = search.timezone || zoneQuery.data?.default_timezone || 'UTC'
  const effective = { ...search, timezone: zone }
  const local = searchToFilters(effective)
  let params = queryFor(
    search.from && search.to && !search.held
      ? { ...local, fromLocal: '', toLocal: '' }
      : local,
    search.page
  )
  if (search.from && search.to && !search.held) {
    const exact = new URLSearchParams(params)
    exact.set('from', search.from)
    exact.set('to', search.to)
    // Preserve the exact absolute instants of a shared URL, including DST-fold times.
    params = exact.toString()
  }
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'llm-calls',
      params,
    ],
    enabled:
      !permissionLost && (Boolean(search.timezone) || zoneQuery.isSuccess),
    queryFn: ({ signal }) =>
      api<Schema['CallPage']>(
        `/llm/calls?${params}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const columns: ColumnDef<Call>[] = [
    {
      id: 'time',
      header: '受理时间',
      cell: ({ row }) => timeInZone(row.original.created_at, zone),
    },
    {
      id: 'member',
      header: '成员 / 来源',
      cell: ({ row }) => (
        <span>
          {row.original.member_name ?? '管理员诊断'} · {row.original.source}
        </span>
      ),
    },
    {
      id: 'model',
      header: '模型 / 操作',
      cell: ({ row }) => (
        <span>
          {row.original.model_name ?? '无平台模型'} ·{' '}
          {operations[row.original.operation as keyof typeof operations] ??
            row.original.operation}
        </span>
      ),
    },
    {
      id: 'status',
      header: '结果 / 结算',
      cell: ({ row }) => callBadges(row.original),
    },
    {
      id: 'attempts',
      header: '尝试',
      cell: ({ row }) => row.original.attempt_count,
    },
    {
      id: 'action',
      header: '操作',
      cell: ({ row }) => (
        <Button
          type='button'
          variant='outline'
          size='sm'
          onClick={() => {
            trigger.current = document.activeElement as HTMLElement
            setDetailId(row.original.id)
          }}
        >
          查看详情
        </Button>
      ),
    },
  ]
  const forbidden =
    query.error instanceof ApiError && [401, 403].includes(query.error.status)
  if (permissionLost)
    return (
      <PageShell title='调用记录'>
        <RequestError error={permissionLost} />
      </PageShell>
    )
  return (
    <PageShell
      title='调用记录'
      description='结果与结算状态独立；未知用量不能按零处理。'
      action={
        <div className='flex flex-wrap gap-2'>
          <Button asChild variant='outline'>
            <Link
              to='/llm-usage'
              search={{
                ...search,
                source: search.source === 'all' ? 'member' : search.source,
                call_id: '',
                held: false,
                page: 1,
              }}
            >
              用量统计
            </Link>
          </Button>
          <Button
            type='button'
            variant='outline'
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            刷新
          </Button>
        </div>
      }
    >
      {!search.timezone && (
        <p className='text-sm text-muted-foreground'>
          时区：
          {zoneQuery.isError
            ? '组织默认时区读取失败，请重试或在筛选中明确选择。'
            : zoneQuery.data?.default_timezone
              ? `${zone}（组织默认周策略）`
              : 'UTC（组织未配置默认周策略时区，请在筛选中明确选择）'}
        </p>
      )}
      <CallFilters
        key={JSON.stringify(effective)}
        search={effective}
        onApply={(values) =>
          void navigate({ to: '/llm-calls', search: searchFromFilters(values) })
        }
      />
      {zoneQuery.isPending && !search.timezone ? (
        <LoadingState />
      ) : zoneQuery.isError && !search.timezone ? (
        <RequestError
          error={zoneQuery.error}
          retry={() => void zoneQuery.refetch()}
        />
      ) : query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError
          error={query.error}
          retry={forbidden ? undefined : () => void query.refetch()}
        />
      ) : (
        <ServerTable
          items={query.data.items}
          columns={columns}
          total={query.data.total}
          page={search.page}
          onPage={(page) =>
            void navigate({
              to: '/llm-calls',
              search:
                search.from && search.to
                  ? { ...effective, page }
                  : searchFromFilters(local, page),
            })
          }
          empty={search.held ? '当前没有占用中的正式调用' : '没有匹配的调用'}
          renderItems={
            narrow
              ? (items) => (
                  <div className='grid min-w-0 gap-3'>
                    {items.map((call) => (
                      <Card key={call.id} className='min-w-0'>
                        <CardContent className='grid min-w-0 gap-2 pt-4'>
                          <p className='font-medium break-words'>
                            {call.model_name ?? '无平台模型'} ·{' '}
                            {operations[
                              call.operation as keyof typeof operations
                            ] ?? call.operation}
                          </p>
                          <p className='text-sm text-muted-foreground'>
                            {timeInZone(call.created_at, zone)} ·{' '}
                            {call.member_name ?? '管理员诊断'} · {call.source}
                          </p>
                          {callBadges(call)}
                          <p className='text-xs text-muted-foreground'>
                            {call.attempt_count} 次尝试 · 调用编号{' '}
                            <span className='break-all'>{call.id}</span>
                          </p>
                          <Button
                            type='button'
                            variant='outline'
                            className='justify-self-start'
                            onClick={() => {
                              trigger.current =
                                document.activeElement as HTMLElement
                              setDetailId(call.id)
                            }}
                          >
                            查看详情
                          </Button>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )
              : undefined
          }
        />
      )}
      {detailId && (
        <CallDetailSheet
          key={detailId}
          id={detailId}
          timezone={zone}
          close={() => setDetailId(null)}
          restoreFocus={() => trigger.current?.focus()}
          onAccessDenied={(cause) => {
            setDetailId(null)
            if (cause.status === 401 || cause.status === 403) {
              setPermissionLost(cause)
              client.removeQueries({
                queryKey: [
                  'organization',
                  organization.tenant_id,
                  user.id,
                  'llm-calls',
                ],
              })
              client.removeQueries({
                queryKey: [
                  'organization',
                  organization.tenant_id,
                  user.id,
                  'llm-call',
                  detailId,
                ],
              })
            } else
              void client.invalidateQueries({
                queryKey: [
                  'organization',
                  organization.tenant_id,
                  user.id,
                  'llm-calls',
                ],
              })
          }}
        />
      )}
    </PageShell>
  )
}
