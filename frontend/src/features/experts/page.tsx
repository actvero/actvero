import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { Plus, Settings2 } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ServerTable } from '@/components/data-table/server-table'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceCategoriesDialog } from '@/components/resource-categories-dialog'
import { ResourceIcon } from '@/components/resource-icon'
import { SearchSelect } from '@/components/search-select'
import { ExpertActions } from './actions'
import { ExpertCategoryPicker } from './category-picker'
import {
  statusLabels,
  scopeLabels,
  useExperts,
  type ExpertSummary,
} from './shared'

const columns: ColumnDef<ExpertSummary>[] = [
  {
    accessorKey: 'name',
    header: '专家',
    cell: ({ row: { original: e } }) => (
      <Link
        to='/experts/$expertId'
        params={{ expertId: e.id }}
        className='flex items-center gap-3'
        aria-label={`打开专家 ${e.name}`}
      >
        <ResourceIcon image={e.avatar} name={e.name} />
        <div className='flex min-w-0 flex-col gap-1'>
          <span className='font-medium'>{e.name}</span>
          <p className='max-w-sm truncate text-sm text-muted-foreground'>
            {e.description}
          </p>
        </div>
      </Link>
    ),
  },
  {
    id: 'category',
    header: '类别',
    cell: ({ row }) => row.original.category.name,
  },
  {
    id: 'release',
    header: '当前版本',
    cell: ({ row }) => row.original.current_release?.version ?? '—',
  },
  {
    id: 'status',
    header: '状态',
    cell: ({ row: { original: e } }) => (
      <div className='flex flex-wrap gap-2'>
        <Badge variant='secondary'>{statusLabels[e.status]}</Badge>
        {e.current_release && e.has_changes && (
          <Badge variant='outline'>有未发布修改</Badge>
        )}
      </div>
    ),
  },
  {
    id: 'dependencies',
    header: '依赖状态',
    cell: ({ row }) =>
      row.original.dependency_issues ? (
        <Badge variant='outline'>
          {row.original.dependency_issues} 项待维护
        </Badge>
      ) : (
        '正常'
      ),
  },
  {
    accessorKey: 'audience',
    header: '使用范围',
    cell: ({ row }) => scopeLabels[row.original.audience],
  },
]
export function ExpertsPage() {
  const navigate = useNavigate()
  const { key } = useExperts()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('all')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [categoriesOpen, setCategoriesOpen] = useState(false)
  const query = useQuery({
    queryKey: [...key, 'list', q, category, status, page],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ q, page: String(page) })
      if (category !== 'all') params.set('category', category)
      if (status !== 'all') params.set('status', status)
      return api<Schema['ExpertPage']>(
        '/experts?' + params,
        'GET',
        undefined,
        undefined,
        signal
      )
    },
  })
  const itemCount = query.data?.items.length
  const actionableColumns = useMemo<ColumnDef<ExpertSummary>[]>(
    () => [
      ...columns,
      {
        id: 'actions',
        header: '操作',
        cell: ({ row }) => (
          <ExpertActions
            expert={row.original}
            edit
            deleted={() => {
              if (itemCount === 1 && page > 1) setPage(page - 1)
            }}
          />
        ),
      },
    ],
    [page, itemCount]
  )
  return (
    <PageShell
      title='专家'
      action={
        <div className='flex gap-2'>
          <Button variant='outline' onClick={() => setCategoriesOpen(true)}>
            <Settings2 />
            类别管理
          </Button>
          <Button asChild>
            <Link to='/experts/new'>
              <Plus />
              创建专家
            </Link>
          </Button>
        </div>
      }
    >
      <div className='flex flex-wrap gap-3'>
        <Input
          className='w-full sm:w-72'
          aria-label='搜索专家'
          placeholder='搜索名称或简介…'
          maxLength={100}
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setPage(1)
          }}
        />
        <ExpertCategoryPicker
          includeAll
          value={category}
          onValueChange={(v) => {
            setCategory(v)
            setPage(1)
          }}
        />
        <SearchSelect
          aria-label='发布状态'
          value={status}
          onValueChange={(v) => {
            setStatus(v)
            setPage(1)
          }}
          items={[
            { value: 'all', label: '全部状态' },
            { value: 'published', label: '已发布' },
            { value: 'unpublished', label: '未发布' },
          ]}
        />
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError
          error={query.error}
          retry={() => {
            setCategory('all')
            void query.refetch()
          }}
        />
      ) : (
        <ServerTable
          items={query.data.items}
          columns={actionableColumns}
          onRowClick={(expert) =>
            void navigate({
              to: '/experts/$expertId',
              params: { expertId: expert.id },
            })
          }
          total={query.data.total}
          page={page}
          onPage={setPage}
          empty={
            q || category !== 'all' || status !== 'all'
              ? '没有符合条件的专家'
              : '还没有专家，点击“创建专家”开始。'
          }
        />
      )}
      {categoriesOpen && (
        <ResourceCategoriesDialog
          resource='experts'
          noun='专家'
          close={() => {
            setCategoriesOpen(false)
            setCategory('all')
            setPage(1)
          }}
        />
      )}
    </PageShell>
  )
}
