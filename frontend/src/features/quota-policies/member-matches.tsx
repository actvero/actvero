import { useDeferredValue, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { RefreshCw } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ServerTable } from '@/components/data-table/server-table'
import { LoadingState, RequestError } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { MemberUsage } from './settlements'

type MemberMatch = Schema['MemberQuotaMatch']
const columns: ColumnDef<MemberMatch>[] = [
  {
    id: 'name',
    header: '成员',
    cell: ({ row: { original: m } }) => (
      <div className='flex min-w-40 items-center gap-3'>
        <UserAvatar user={{ name: m.name, avatar_url: null }} />
        <div className='flex flex-col gap-1'>
          <span>{m.name}</span>
          <span className='text-sm text-muted-foreground'>{m.email}</span>
          {m.role === 'administrator' && (
            <Badge variant='outline'>管理员</Badge>
          )}
        </div>
      </div>
    ),
  },
  {
    id: 'policy',
    header: '采用策略',
    cell: ({ row: { original: m } }) =>
      m.selected ? (
        <div className='flex min-w-28 flex-col items-start gap-1'>
          <span>{m.selected.name}</span>
          <Badge variant='secondary'>优先级 {m.selected.priority}</Badge>
        </div>
      ) : (
        '未配置'
      ),
  },
  {
    id: 'matched',
    header: '其他命中',
    cell: ({ row: { original: m } }) => (
      <div className='flex min-w-24 flex-wrap gap-1'>
        {m.matched.slice(1).map((p) => (
          <Badge key={p.id} variant='outline'>
            {p.name}
          </Badge>
        ))}
        {m.matched.length <= 1 && '—'}
      </div>
    ),
  },
  {
    id: 'usage',
    header: '剩余额度',
    meta: { className: 'w-80 whitespace-normal' },
    cell: ({ row }) => <MemberUsage memberId={row.original.member_id} />,
  },
]
export function MemberMatches() {
  const { organization } = useOrganization()
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const q = useDeferredValue(search)
  const params = new URLSearchParams({ q, page: String(page) }).toString()
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'quota',
      'matches',
      params,
    ],
    queryFn: ({ signal }) =>
      api<Schema['QuotaMatchPage']>(
        '/quota/matches?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <Input
          className='max-w-sm'
          value={search}
          maxLength={200}
          aria-label='搜索成员匹配'
          placeholder='搜索姓名或邮箱…'
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        <Button
          variant='outline'
          onClick={() =>
            void client.invalidateQueries({
              queryKey: ['organization', organization.tenant_id, 'quota'],
            })
          }
        >
          <RefreshCw />
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
          empty='没有匹配的有效成员'
        />
      )}
    </div>
  )
}
