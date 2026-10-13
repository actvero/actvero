import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { toast } from 'sonner'
import { api, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ServerTable } from '@/components/data-table/server-table'
import { FilterSelect } from '@/components/filter-select'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { QuotaWindow } from '@/features/usage/quota-windows'
import { ReconcileDialog } from './reconcile-dialog'
import { pendingRecoveries } from './reconcile-recovery'

type Entry = Schema['SettlementView']
const states: Record<string, string> = {
  reserved: '预占中',
  review: '待核对',
  settled: '已结算',
  released: '已释放',
}
export function Settlements() {
  const { organization, user } = useOrganization()
  const client = useQueryClient()
  const [state, setState] = useState('')
  const [page, setPage] = useState(1)
  const [callId, setCallId] = useState<string | null>(null)
  const trigger = useRef<HTMLElement | null>(null)
  const params = new URLSearchParams({ state, page: String(page) }).toString()
  const prefix = ['organization', organization.tenant_id, 'quota']
  const recoveries = pendingRecoveries(organization.tenant_id, user.id)
  const query = useQuery({
    queryKey: [...prefix, 'settlements', params],
    queryFn: ({ signal }) =>
      api<Schema['SettlementPage']>(
        '/llm/settlements?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const columns: ColumnDef<Entry>[] = [
    { accessorKey: 'member_name', header: '成员' },
    { accessorKey: 'model_name', header: '模型' },
    {
      id: 'state',
      header: '状态',
      cell: ({ row }) => (
        <Badge
          variant={row.original.status === 'review' ? 'outline' : 'secondary'}
        >
          {states[row.original.status]}
        </Badge>
      ),
    },
    {
      accessorKey: 'points',
      header: '消耗积分',
      cell: ({ row }) => row.original.points ?? '待确认',
    },
    { accessorKey: 'reserved_points', header: '预占积分' },
    {
      id: 'date',
      header: '受理时间',
      cell: ({ row }) => dateTime(row.original.created_at),
    },
    {
      id: 'action',
      header: '操作',
      cell: ({ row }) =>
        ['review', 'reserved'].includes(row.original.status) ? (
          <Button
            variant='outline'
            size='sm'
            onClick={() => {
              trigger.current = document.activeElement as HTMLElement
              setCallId(row.original.id)
            }}
          >
            核对
          </Button>
        ) : (
          '—'
        ),
    },
  ]
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      {recoveries.length > 0 && (
        <Alert>
          <AlertTitle>有待确认的核对请求</AlertTitle>
          <AlertDescription>
            <p>这些编号可跨筛选条件回查；浏览器没有保存核对用量或依据。</p>
            {recoveries.map((item) => (
              <div
                key={item.request_id}
                className='flex min-w-0 flex-wrap items-center gap-2'
              >
                <span className='min-w-0 font-mono text-xs break-all'>
                  调用 {item.call_id} · 请求 {item.request_id}
                </span>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => {
                    trigger.current = document.activeElement as HTMLElement
                    setCallId(item.call_id)
                  }}
                >
                  回查核对
                </Button>
              </div>
            ))}
          </AlertDescription>
        </Alert>
      )}
      <div className='flex flex-wrap gap-2'>
        <FilterSelect
          label='结算状态'
          value={state}
          onChange={(v) => {
            setState(v)
            setPage(1)
          }}
          options={Object.entries(states).map(([value, label]) => ({
            value,
            label,
          }))}
        />
        <Button
          variant='outline'
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          刷新
        </Button>
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
          empty='暂无结算记录'
        />
      )}
      {callId && (
        <ReconcileDialog
          key={callId}
          callId={callId}
          close={() => setCallId(null)}
          restoreFocus={() => trigger.current?.focus()}
          saved={() => {
            setCallId(null)
            void client.invalidateQueries({ queryKey: prefix })
            toast.success('核对结果已保存')
          }}
        />
      )}
    </div>
  )
}
export function MemberUsage({ memberId }: { memberId: string }) {
  const { organization } = useOrganization()
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'quota',
      'member-usage',
      memberId,
    ],
    queryFn: ({ signal }) =>
      api<Schema['QuotaView']>(
        `/llm/members/${memberId}/quota`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return (
    <div className='flex w-72 flex-col gap-4 py-2'>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : query.data.status === 'unconfigured' ? (
        <span className='text-sm text-muted-foreground'>未配置额度</span>
      ) : (
        query.data.windows.map((w) => (
          <QuotaWindow
            key={`${w.rule.kind}-${w.rule.hours ?? 'week'}`}
            window={w}
            compact
          />
        ))
      )}
    </div>
  )
}
