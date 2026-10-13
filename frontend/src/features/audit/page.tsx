import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { api, dateTime, type Schema } from '@/lib/api'
import { ServerTable } from '@/components/data-table/server-table'
import { PageShell } from '@/components/layout/page-shell'
import { RequestError, LoadingState } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { auditActions } from './actions'

export function AuditPage() {
  const { organization, user } = useOrganization()
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, 'events', page],
    queryFn: ({ signal }) =>
      api<Schema['EventPage']>(
        '/enterprises/' + organization.tenant_id + '/events?page=' + page,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const columns: ColumnDef<Schema['EventView']>[] = [
    {
      accessorKey: 'created_at',
      header: '时间',
      cell: ({ row }) => dateTime(row.original.created_at),
    },
    { accessorKey: 'actor_name', header: '操作人' },
    {
      accessorKey: 'action',
      header: '操作',
      cell: ({ row }) =>
        auditActions[row.original.action] ?? row.original.action,
    },
    { accessorKey: 'target_name', header: '对象' },
    {
      accessorKey: 'result',
      header: '结果',
      cell: ({ row }) =>
        ({ success: '成功', submitted: '已提交', failed: '失败' })[
          row.original.result
        ] ?? row.original.result,
    },
  ]
  return (
    <PageShell title='操作记录'>
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
          empty='暂无操作记录'
        />
      )}
    </PageShell>
  )
}
