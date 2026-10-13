import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, dateTime, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { ServerTable } from '@/components/data-table/server-table'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSkills } from './shared'

const columns: ColumnDef<Schema['SkillDistributionView']>[] = [
  {
    accessorKey: 'skill_name',
    header: '技能',
    cell: ({ row }) => (
      <Link to='/skills/$skillId' params={{ skillId: row.original.skill_id }}>
        {row.original.skill_name}
      </Link>
    ),
  },
  { accessorKey: 'version', header: '版本' },
  { accessorKey: 'actor_name', header: '获取人' },
  {
    accessorKey: 'source',
    header: '来源',
    cell: ({ row }) =>
      row.original.source === 'desktop' ? '桌面端' : '控制台',
  },
  {
    accessorKey: 'created_at',
    header: '发放时间',
    cell: ({ row }) => dateTime(row.original.created_at),
  },
]
export function SkillDistributions({ skill }: { skill?: string }) {
  const { key } = useSkills()
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [...key, 'distributions', skill, page],
    queryFn: ({ signal }) =>
      api<Schema['SkillDistributionPage']>(
        `/skills/distributions?${new URLSearchParams({ page: String(page), ...(skill ? { skill_id: skill } : {}) })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return (
    <PageShell
      title='分发记录'
      description='记录通过授权校验后发放的技能包，不代表客户端已完成安装。'
      action={
        skill && (
          <Button variant='outline' asChild>
            <Link to='/skill-distributions' search={{ skill: undefined }}>
              查看全部记录
            </Link>
          </Button>
        )
      }
    >
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
          empty='暂无技能包分发记录'
        />
      )}
    </PageShell>
  )
}
