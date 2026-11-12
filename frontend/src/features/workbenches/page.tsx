import { useDeferredValue, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { ArrowUpRight, LayoutTemplate, Search } from 'lucide-react'
import { api, dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import { ServerTable } from '@/components/data-table/server-table'
import { FilterSelect } from '@/components/filter-select'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceIcon } from '@/components/resource-icon'
import { WorkbenchDevelopmentGuide } from './development-guide'
import {
  audiences,
  categories,
  options,
  useWorkbenches,
  type WorkbenchSummary,
} from './shared'
import { WorkbenchStatusBadge } from './status-badge'
import { UploadWorkbenchDialog } from './upload-dialog'

const columns: ColumnDef<WorkbenchSummary>[] = [
  {
    accessorKey: 'display_name',
    header: '工作台',
    cell: ({ row: { original: item } }) => (
      <Link
        className='flex min-w-0 items-center gap-3'
        to='/workbenches/$workbenchId'
        params={{ workbenchId: item.id }}
      >
        <ResourceIcon name={item.display_name} image={item.icon_data_url} />
        <div className='flex min-w-0 flex-col gap-0.5'>
          <span className='font-medium break-all'>{item.display_name}</span>
          <span className='hidden truncate text-xs text-muted-foreground sm:block'>
            {item.package_name}
          </span>
        </div>
      </Link>
    ),
  },
  {
    accessorKey: 'category',
    header: '分类',
    meta: { className: 'hidden lg:table-cell' },
    cell: ({ row }) => categories[row.original.category],
  },
  {
    accessorKey: 'current_version',
    header: '发布版本',
    cell: ({ row }) => row.original.current_version ?? '—',
  },
  {
    accessorKey: 'status',
    header: '状态',
    cell: ({ row: { original: item } }) => (
      <div className='flex flex-wrap gap-1.5'>
        <WorkbenchStatusBadge status={item.status} />
        {item.status !== 'draft' && item.has_draft && (
          <Badge variant='outline'>有草稿</Badge>
        )}
      </div>
    ),
  },
  {
    accessorKey: 'audience',
    header: '使用范围',
    meta: { className: 'hidden md:table-cell' },
    cell: ({ row }) => audiences[row.original.audience],
  },
  {
    accessorKey: 'updated_at',
    header: '更新时间',
    meta: { className: 'hidden xl:table-cell' },
    cell: ({ row }) => dateTime(row.original.updated_at),
  },
  {
    id: 'action',
    header: () => <span className='sr-only'>操作</span>,
    meta: { className: 'w-12' },
    cell: ({ row: { original: item } }) => (
      <Button variant='ghost' size='icon' asChild>
        <Link
          to='/workbenches/$workbenchId'
          params={{ workbenchId: item.id }}
          aria-label={`查看 ${item.display_name}`}
        >
          <ArrowUpRight />
        </Link>
      </Button>
    ),
  },
]

export function WorkbenchesPage() {
  const navigate = useNavigate()
  const { key } = useWorkbenches()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const q = useDeferredValue(search.trim())
  const query = useQuery({
    queryKey: [...key, 'list', q, category, status, page],
    queryFn: ({ signal }) =>
      api<Schema['WorkbenchPage']>(
        `/workbenches?${new URLSearchParams({
          q,
          page: String(page),
          ...(category ? { category } : {}),
          ...(status ? { status } : {}),
        })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
    placeholderData: keepPreviousData,
  })
  const filtered = !!(q || category || status)
  function clearFilters() {
    setSearch('')
    setCategory('')
    setStatus('')
    setPage(1)
  }
  return (
    <PageShell
      title='工作台'
      action={
        <div className='flex flex-wrap items-center gap-2'>
          <WorkbenchDevelopmentGuide />
          <UploadWorkbenchDialog
            onUploaded={(item) =>
              void navigate({
                to: '/workbenches/$workbenchId',
                params: { workbenchId: item.id },
              })
            }
          />
        </div>
      }
    >
      <div className='flex flex-wrap items-center gap-2'>
        <InputGroup className='w-full sm:w-72'>
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
          <InputGroupInput
            aria-label='搜索工作台'
            placeholder='搜索名称或包名…'
            maxLength={100}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
          />
        </InputGroup>
        <FilterSelect
          label='分类'
          value={category}
          options={options(categories)}
          onChange={(value) => {
            setCategory(value)
            setPage(1)
          }}
        />
        <FilterSelect
          label='状态'
          value={status}
          options={options({
            draft: '草稿',
            published: '已发布',
            withdrawn: '已下架',
          })}
          onChange={(value) => {
            setStatus(value)
            setPage(1)
          }}
        />
        {filtered && (
          <Button variant='ghost' onClick={clearFilters}>
            清除筛选
          </Button>
        )}
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : query.data.total === 0 ? (
        <Empty className='border'>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <LayoutTemplate />
            </EmptyMedia>
            <EmptyTitle>
              {filtered ? '没有匹配的工作台' : '暂无工作台'}
            </EmptyTitle>
            <EmptyDescription>
              {filtered
                ? '尝试调整关键词或筛选条件。'
                : '上传一个 .tgz 安装包，创建第一个工作台。'}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div aria-busy={query.isFetching}>
          <ServerTable
            items={query.data.items}
            total={query.data.total}
            columns={columns}
            page={page}
            onPage={setPage}
            empty='这一页没有工作台'
            getRowId={(item) => item.id}
          />
        </div>
      )}
    </PageShell>
  )
}
