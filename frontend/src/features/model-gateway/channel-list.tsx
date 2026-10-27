import type { ReactNode } from 'react'
import {
  getCoreRowModel,
  useReactTable,
  type VisibilityState,
  type SortingState,
} from '@tanstack/react-table'
import { DataTableView } from '@/vendor/newapi/components/data-table/core/data-table-view'
import { StatusBadgeTypeContext } from '@/vendor/newapi/components/status-badge'
import { ChannelCard as NativeChannelCard } from '@/vendor/newapi/features/channels/components/channel-card'
import { CHANNEL_TYPE_OPTIONS } from '@/vendor/newapi/features/channels/constants'
import {
  ArrowDown,
  ArrowUp,
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
  Table2,
  LayoutGrid,
  X,
  SlidersHorizontal,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuCheckboxItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { channelTypeName, type Channel } from './api'
import {
  initialChannelFilters,
  type ChannelFilters,
} from './channel-list-state'
import {
  ChannelTableContext,
  type ChannelActions,
} from './channel-table-context'
import { useChannelColumns } from './use-channel-columns'

function FilterSelect({
  label,
  value,
  options,
  onChange,
  compact = false,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  compact?: boolean
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        aria-label={label}
        className={cn(
          'w-full min-w-0 [&_[data-slot=select-value]]:truncate',
          compact && 'w-auto min-w-16'
        )}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function IconAction({
  label,
  children,
  ...props
}: {
  label: string
  children: ReactNode
} & React.ComponentProps<typeof Button>) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant='ghost' size='icon' aria-label={label} {...props}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

export function ChannelListToolbar({
  filters,
  onChange,
  groups,
  fetching,
  onRefresh,
  visibility,
  onVisibility,
}: {
  filters: ChannelFilters
  onChange: (value: ChannelFilters) => void
  groups: string[]
  fetching: boolean
  onRefresh: () => void
  visibility: VisibilityState
  onVisibility: (value: VisibilityState) => void
}) {
  const update = (key: keyof ChannelFilters, value: string) =>
    onChange({ ...filters, [key]: value })
  const filtered =
    filters.q ||
    filters.model ||
    [filters.state, filters.type, filters.group].some(
      (value) => value !== 'all'
    )
  return (
    <div
      className='@container/channel-toolbar flex min-w-0 shrink-0 flex-col gap-2'
      role='search'
      aria-label='筛选渠道'
    >
      <div className='grid min-w-0 grid-cols-6 gap-2 @min-[52rem]/channel-toolbar:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_repeat(3,minmax(0,7.5rem))]'>
        <InputGroup className='col-span-6 min-w-0 @min-[24rem]/channel-toolbar:col-span-3 @min-[52rem]/channel-toolbar:col-span-1'>
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
          <InputGroupInput
            aria-label='搜索渠道'
            placeholder='按名称或 ID 筛选…'
            value={filters.q}
            onChange={(event) => update('q', event.target.value)}
          />
        </InputGroup>
        <InputGroup className='col-span-6 min-w-0 @min-[24rem]/channel-toolbar:col-span-3 @min-[52rem]/channel-toolbar:col-span-1'>
          <InputGroupInput
            aria-label='按模型筛选'
            placeholder='按模型筛选…'
            value={filters.model}
            onChange={(event) => update('model', event.target.value)}
          />
        </InputGroup>
        <div className='col-span-2 min-w-0 @min-[52rem]/channel-toolbar:col-span-1'>
          <FilterSelect
            label='状态'
            value={filters.state}
            onChange={(value) => update('state', value)}
            options={[
              { value: 'all', label: '全部状态' },
              { value: 'enabled', label: '已启用' },
              { value: 'disabled', label: '已禁用' },
            ]}
          />
        </div>
        <div className='col-span-2 min-w-0 @min-[52rem]/channel-toolbar:col-span-1'>
          <FilterSelect
            label='类型'
            value={filters.type}
            onChange={(value) => update('type', value)}
            options={[
              { value: 'all', label: '全部类型' },
              ...CHANNEL_TYPE_OPTIONS.map((option) => ({
                value: String(option.value),
                label: channelTypeName(option.value).startsWith('渠道类型')
                  ? option.label
                  : channelTypeName(option.value),
              })),
            ]}
          />
        </div>
        <div className='col-span-2 min-w-0 @min-[52rem]/channel-toolbar:col-span-1'>
          <FilterSelect
            label='分组'
            value={filters.group}
            onChange={(value) => update('group', value)}
            options={[
              { value: 'all', label: '全部分组' },
              ...groups.map((group) => ({ value: group, label: group })),
            ]}
          />
        </div>
      </div>
      <div className='flex min-w-0 flex-wrap items-center justify-between gap-2'>
        <div className='flex min-w-0 items-center gap-1'>
          <div className='w-32 min-w-0'>
            <FilterSelect
              label='渠道排序依据'
              value={filters.sort}
              onChange={(value) => update('sort', value)}
              options={[
                { value: 'priority', label: '优先级' },
                { value: 'id', label: 'ID' },
                { value: 'name', label: '名称' },
                { value: 'response_time', label: '响应时间' },
                { value: 'balance', label: '已使用 / 剩余' },
                { value: 'test_time', label: '上次测试' },
              ]}
            />
          </div>
          <IconAction
            label={filters.order === 'desc' ? '降序' : '升序'}
            onClick={() =>
              update('order', filters.order === 'desc' ? 'asc' : 'desc')
            }
          >
            {filters.order === 'desc' ? <ArrowDown /> : <ArrowUp />}
          </IconAction>
          <IconAction label='刷新渠道' disabled={fetching} onClick={onRefresh}>
            <RefreshCw className={cn(fetching && 'animate-spin')} />
          </IconAction>
          {filtered && (
            <Button
              variant='ghost'
              size='sm'
              onClick={() =>
                onChange({
                  ...initialChannelFilters,
                  sort: filters.sort,
                  order: filters.order,
                })
              }
            >
              <X data-icon='inline-start' />
              重置
            </Button>
          )}
        </div>
        <div className='ms-auto flex shrink-0 items-center gap-1'>
          <TabsList aria-label='视图模式'>
            <TabsTrigger value='table' aria-label='表格视图'>
              <Table2 />
              表格
            </TabsTrigger>
            <TabsTrigger value='cards' aria-label='卡片视图'>
              <LayoutGrid />
              卡片
            </TabsTrigger>
          </TabsList>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant='outline' size='sm'>
                <SlidersHorizontal data-icon='inline-start' />
                查看
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align='end'>
              <DropdownMenuGroup>
                {Object.entries({
                  id: 'ID',
                  name: '名称',
                  type: '类型',
                  status: '状态',
                  group: '分组',
                  priority: '优先级',
                  weight: '权重',
                  balance: '已使用 / 剩余',
                  response_time: '响应',
                  test_time: '上次测试',
                  models: '模型',
                }).map(([id, label]) => (
                  <DropdownMenuCheckboxItem
                    key={id}
                    checked={visibility[id] !== false}
                    onCheckedChange={(checked) =>
                      onVisibility({ ...visibility, [id]: checked })
                    }
                  >
                    {label}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  )
}

export function ChannelList({
  items,
  quotaPerUnit,
  visibility,
  onVisibility,
  sorting,
  onSort,
  ...actions
}: {
  items: Channel[]
  quotaPerUnit?: number | null
  visibility: VisibilityState
  onVisibility: (value: VisibilityState) => void
  sorting: SortingState
  onSort: (sort: SortingState) => void
} & ChannelActions) {
  const columns = useChannelColumns()
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: items,
    columns,
    getRowId: (channel) => String(channel.id),
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    state: { columnVisibility: visibility, sorting },
    onColumnVisibilityChange: (updater) =>
      onVisibility(
        typeof updater === 'function' ? updater(visibility) : updater
      ),
    onSortingChange: (updater) =>
      onSort(typeof updater === 'function' ? updater(sorting) : updater),
  })
  return (
    <ChannelTableContext.Provider value={{ actions, quotaPerUnit }}>
      <StatusBadgeTypeContext.Provider value='text'>
        <TabsContent value='table' className='min-w-0'>
          <DataTableView
            table={table}
            containerClassName='min-w-0 max-w-full'
            applyHeaderSize
            tableClassName='w-max min-w-full table-auto'
            pinnedColumns={[
              {
                columnId: 'actions',
                side: 'right',
                cellClassName: 'bg-background',
              },
            ]}
          />
        </TabsContent>
        <TabsContent value='cards' className='min-w-0'>
          <div className='grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-4'>
            {table.getRowModel().rows.map((row) => (
              <div
                key={row.id}
                className='min-w-0 rounded-xl border bg-card p-3'
              >
                <NativeChannelCard row={row} isSelected={false} />
              </div>
            ))}
          </div>
        </TabsContent>
      </StatusBadgeTypeContext.Provider>
    </ChannelTableContext.Provider>
  )
}

export function ChannelPagination({
  page,
  pageSize,
  total,
  fetching,
  onPage,
  onPageSize,
}: {
  page: number
  pageSize: number
  total: number
  fetching: boolean
  onPage: (page: number) => void
  onPageSize: (size: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <nav
      aria-label='渠道分页'
      className='flex shrink-0 flex-wrap items-center justify-between gap-3 border-t bg-background pt-4 text-sm'
    >
      <p className='text-muted-foreground' aria-live='polite'>
        总计 {total} 个渠道
      </p>
      <div className='flex flex-wrap items-center justify-end gap-x-4 gap-y-2'>
        <div className='flex items-center gap-2'>
          <span className='text-xs text-muted-foreground'>每页行数</span>
          <FilterSelect
            label='每页行数'
            compact
            value={String(pageSize)}
            onChange={(value) => onPageSize(Number(value))}
            options={[20, 50, 100].map((size) => ({
              value: String(size),
              label: String(size),
            }))}
          />
        </div>
        <div className='flex items-center gap-1'>
          <span className='px-2 text-xs text-muted-foreground'>
            第 {page} / {pages} 页
          </span>
          <IconAction
            label='首页'
            disabled={page <= 1 || fetching}
            onClick={() => onPage(1)}
          >
            <ChevronFirst />
          </IconAction>
          <IconAction
            label='上一页'
            disabled={page <= 1 || fetching}
            onClick={() => onPage(page - 1)}
          >
            <ChevronLeft />
          </IconAction>
          <IconAction
            label='下一页'
            disabled={page >= pages || fetching}
            onClick={() => onPage(page + 1)}
          >
            <ChevronRight />
          </IconAction>
          <IconAction
            label='末页'
            disabled={page >= pages || fetching}
            onClick={() => onPage(pages)}
          >
            <ChevronLast />
          </IconAction>
        </div>
      </div>
    </nav>
  )
}
