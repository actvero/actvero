import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  AlignLeft,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
  Image,
  MoreHorizontal,
  RefreshCw,
  Table2,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, dateTime } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Progress } from '@/components/ui/progress'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ListPagination } from '@/components/list-pagination'
import { ListSearch, ListToolbar } from '@/components/list-toolbar'
import { LoadingState, RequestError } from '@/components/request-state'
import { packageSize } from '@/features/workbenches/shared'
import { Choice } from './controls'
import {
  documentNeedsAttention,
  documentNeedsProcessing,
  type useDocuments,
} from './document-data'
import { DocumentDialog } from './document-reader'
import { AddDocuments } from './document-upload'
import { busy, useKnowledge, type Base, type Document } from './shared'

export { DocumentDialog } from './document-reader'

const timeOrder = [
  { value: 'newest', label: '最近上传' },
  { value: 'oldest', label: '最早上传' },
  { value: 'name', label: '文件名 A–Z' },
]
const statuses = [
  { value: 'all', label: '全部状态' },
  { value: 'ready', label: '可检索' },
  { value: 'processing', label: '处理中' },
  { value: 'queued', label: '等待处理' },
  { value: 'waiting', label: '等待服务' },
  { value: 'attention', label: '需处理' },
  { value: 'cancelled', label: '已取消' },
]
const queueStatuses = [
  { value: 'pending', label: '当前队列' },
  ...statuses.map((item) =>
    item.value === 'ready' ? { ...item, label: '已完成' } : item
  ),
]
const collator = new Intl.Collator('zh-CN', { numeric: true })
const formatNumber = new Intl.NumberFormat('zh-CN').format
const formatUploadTime = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
}).format
const metadataColumn = 'hidden @3xl/documents:table-cell'

function matchesStatus(doc: Document, status: string) {
  if (status === 'all') return true
  if (status === 'pending') return documentNeedsProcessing(doc)
  if (status === 'processing')
    return ['parsing', 'chunking', 'indexing'].includes(doc.status)
  if (status === 'attention') return documentNeedsAttention(doc)
  return doc.status === status
}

function sortDocuments(documents: Document[], sort: string) {
  return [...documents].sort((left, right) => {
    if (sort === 'name') {
      const comparison = collator.compare(left.filename, right.filename)
      if (comparison !== 0) return comparison
    }
    const comparison =
      Date.parse(left.created_at) - Date.parse(right.created_at)
    return (
      (sort === 'oldest' ? comparison : -comparison) ||
      left.id.localeCompare(right.id)
    )
  })
}

export function Documents({
  base,
  query,
  queue = false,
}: {
  base: Base
  query: ReturnType<typeof useDocuments>
  queue?: boolean
}) {
  const { csrf, refresh } = useKnowledge()
  const [opened, setOpened] = useState<Document | null>(null)
  const [expanded, setExpanded] = useState<string>()
  const [search, setSearch] = useState('')
  const initialStatus = queue ? 'pending' : 'all'
  const [status, setStatus] = useState(initialStatus)
  const [sort, setSort] = useState('newest')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [confirm, setConfirm] = useState<{
    doc: Document
    action: 'delete' | 'rebuild'
  } | null>(null)
  const change = useMutation({
    mutationFn: ({ doc, action }: NonNullable<typeof confirm>) =>
      api(
        `/knowledge/${base.id}/documents/${doc.id}${action === 'rebuild' ? '/rebuild' : ''}`,
        action === 'delete' ? 'DELETE' : 'POST',
        action === 'rebuild'
          ? {
              generation_id: doc.generation_id,
              chunking: base.chunking,
              use_current_defaults:
                doc.status === 'unconfigured' &&
                !Object.keys(base.embedding_profile).length,
            }
          : undefined,
        csrf
      ),
    onSuccess: (_data, { action }) => {
      setConfirm(null)
      void refresh()
      toast.success(action === 'delete' ? '已删除文档' : '已加入处理队列')
    },
  })
  const keyword = search.trim().toLocaleLowerCase()
  const filtered = sortDocuments(
    (query.data ?? []).filter(
      (doc) =>
        doc.filename.toLocaleLowerCase().includes(keyword) &&
        matchesStatus(doc, status)
    ),
    sort
  )
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const items = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  )

  function resetFilters() {
    setSearch('')
    setStatus(initialStatus)
    setPage(1)
  }

  function requestChange(doc: Document, action: 'delete' | 'rebuild') {
    change.reset()
    setConfirm({ doc, action })
  }
  const latest = query.data?.find((doc) => doc.id === confirm?.doc.id)
  const changedSinceConfirmation =
    confirm?.action === 'rebuild' &&
    (!latest ||
      latest.generation_id !== confirm.doc.generation_id ||
      busy(latest.status))
  return (
    <div className='@container/documents flex min-h-0 min-w-0 flex-1 flex-col gap-3'>
      <ListToolbar
        actions={
          queue ? (
            <Button
              variant='outline'
              aria-label='刷新处理队列'
              onClick={() => void query.refetch()}
            >
              <RefreshCw data-icon='inline-start' />
              刷新
            </Button>
          ) : (
            base.can_manage && <AddDocuments baseId={base.id} />
          )
        }
      >
        <ListSearch
          className='sm:w-52 @lg/documents:w-56'
          aria-label='搜索文档'
          placeholder='搜索文件名…'
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
        />
        <Choice
          label={queue ? '任务状态' : '文档状态'}
          value={status}
          onChange={(value) => {
            setStatus(value)
            setPage(1)
          }}
          items={queue ? queueStatuses : statuses}
        />
        <Choice
          label='文档排序'
          value={sort}
          onChange={(value) => {
            setSort(value)
            setPage(1)
          }}
          items={timeOrder}
        />
      </ListToolbar>
      <div className='min-h-0 flex-1 overflow-auto pb-1'>
        {query.isPending ? (
          <LoadingState />
        ) : !query.data ? (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : (
          <div className='flex min-w-0 flex-col gap-3'>
            {query.isError && (
              <RequestError
                error={query.error}
                retry={() => void query.refetch()}
              />
            )}
            {!items.length ? (
              <Empty className='min-h-48 border'>
                <EmptyHeader>
                  <EmptyMedia variant='icon'>
                    <FileText />
                  </EmptyMedia>
                  <EmptyTitle>
                    {!query.data.length
                      ? '暂无文档'
                      : keyword || status !== initialStatus
                        ? '没有符合条件的文档'
                        : '没有待处理任务'}
                  </EmptyTitle>
                  <EmptyDescription>
                    {!query.data.length
                      ? base.can_manage && !queue
                        ? '上传资料后，可在处理队列中查看进度。'
                        : '此知识库还没有上传文档。'
                      : keyword || status !== initialStatus
                        ? '试试其他文件名或状态。'
                        : '新上传的文档和重新处理的任务将在此显示。'}
                  </EmptyDescription>
                </EmptyHeader>
                {(keyword || status !== initialStatus) && (
                  <Button variant='outline' onClick={resetFilters}>
                    清除筛选
                  </Button>
                )}
              </Empty>
            ) : (
              <div className='rounded-lg border'>
                <Table
                  aria-label={queue ? '处理队列' : '知识库文档'}
                  className='table-fixed'
                >
                  <TableHeader className='[&_[data-slot=table-head]]:h-9'>
                    <TableRow className='bg-muted/30'>
                      <TableHead className='ps-3'>文件名</TableHead>
                      {!queue && (
                        <>
                          <TableHead
                            className={cn(metadataColumn, 'w-24 text-end')}
                          >
                            字符数
                          </TableHead>
                          <TableHead
                            className={cn(metadataColumn, 'w-40 ps-4')}
                          >
                            上传时间
                          </TableHead>
                        </>
                      )}
                      <TableHead
                        className={
                          queue
                            ? 'w-28 @lg/documents:w-48'
                            : 'w-26 @lg/documents:w-32'
                        }
                      >
                        {queue ? '处理状态' : '状态'}
                      </TableHead>
                      <TableHead
                        className={cn('pe-3 text-end', queue ? 'w-19' : 'w-14')}
                      >
                        操作
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((doc) => (
                      <DocumentRow
                        key={doc.id}
                        baseId={base.id}
                        doc={doc}
                        queue={queue}
                        canManage={base.can_manage}
                        expanded={expanded === doc.id}
                        onExpand={() =>
                          setExpanded(expanded === doc.id ? undefined : doc.id)
                        }
                        onOpen={() => setOpened(doc)}
                        onChange={(action) => requestChange(doc, action)}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        )}
      </div>
      <ListPagination
        className='gap-2'
        label={queue ? '处理队列分页' : '文档分页'}
        unit={queue ? '个任务' : '份文档'}
        total={query.data ? filtered.length : undefined}
        page={currentPage}
        pageCount={pageCount}
        pageSize={pageSize}
        onPageSize={(value) => {
          setPageSize(value)
          setPage(1)
        }}
        pageSizeOptions={[10, 20, 50]}
        onPage={setPage}
        disabled={!query.data}
      />
      <DocumentDialog
        key={opened?.id ?? 'closed'}
        base={base}
        doc={opened}
        onClose={() => setOpened(null)}
      />
      <ConfirmDialog
        cancelBtnText='取消'
        open={!!confirm}
        onOpenChange={(open) => {
          if (!open && !change.isPending) setConfirm(null)
        }}
        title={confirm?.action === 'delete' ? '删除文档？' : '重新处理文档？'}
        desc={
          <div className='flex flex-col gap-2'>
            <p className='font-medium wrap-anywhere text-foreground'>
              {confirm?.doc.filename}
            </p>
            <p>
              {confirm?.action === 'delete'
                ? '删除后，此文档的检索、原文和历史引用将立即停止访问。'
                : '新版本完成前，已有的索引仍可使用。处理过程中产生的模型调用会计入知识库用量。'}
            </p>
          </div>
        }
        confirmText={
          change.isPending
            ? confirm?.action === 'delete'
              ? '正在删除…'
              : '正在提交…'
            : confirm?.action === 'delete'
              ? '删除'
              : '重新处理'
        }
        destructive={confirm?.action === 'delete'}
        disabled={changedSinceConfirmation}
        isLoading={change.isPending}
        handleConfirm={() => {
          if (confirm && !change.isPending && !changedSinceConfirmation)
            change.mutate(confirm)
        }}
      >
        {change.isError && <RequestError error={change.error} />}
        {changedSinceConfirmation && (
          <p role='status' className='text-sm text-muted-foreground'>
            处理状态已变化，请关闭后查看最新状态。
          </p>
        )}
      </ConfirmDialog>
    </div>
  )
}

function DocumentRow({
  baseId,
  doc,
  queue,
  canManage,
  expanded,
  onExpand,
  onOpen,
  onChange,
}: {
  baseId: string
  doc: Document
  queue: boolean
  canManage: boolean
  expanded: boolean
  onExpand: () => void
  onOpen: () => void
  onChange: (action: 'delete' | 'rebuild') => void
}) {
  const date = dateTime(doc.created_at)
  const oldVersionAvailable =
    doc.active_generation_id && doc.active_generation_id !== doc.generation_id
  const characterCount =
    doc.character_count == null ? '—' : formatNumber(doc.character_count)
  return (
    <>
      <TableRow>
        <TableCell className='px-3 py-1.5'>
          <div className='flex min-w-0 items-center gap-2'>
            <DocumentFileIcon doc={doc} />
            <div className='min-w-0'>
              <Button
                variant='link'
                title={`${doc.filename} · ${packageSize(doc.size)}`}
                className='block h-auto max-w-full truncate p-0 text-start'
                onClick={onOpen}
              >
                {doc.filename}
              </Button>
              <div
                className={cn(
                  'mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted-foreground',
                  !queue && '@3xl/documents:hidden'
                )}
              >
                <span>{packageSize(doc.size)}</span>
                {!queue && (
                  <>
                    {doc.character_count != null && (
                      <span>{characterCount} 字符</span>
                    )}
                    <time dateTime={doc.created_at} title={date}>
                      {new Date(doc.created_at).toLocaleDateString('zh-CN')}
                    </time>
                  </>
                )}
              </div>
            </div>
          </div>
        </TableCell>
        {!queue && (
          <>
            <TableCell
              className={cn(
                metadataColumn,
                'text-end text-muted-foreground tabular-nums'
              )}
            >
              {characterCount}
            </TableCell>
            <TableCell
              className={cn(
                metadataColumn,
                'ps-4 text-muted-foreground tabular-nums'
              )}
            >
              <time dateTime={doc.created_at} title={date}>
                {formatUploadTime(new Date(doc.created_at))}
              </time>
            </TableCell>
          </>
        )}
        <TableCell>
          <div className='flex flex-col items-start gap-1'>
            <DocumentStatus doc={doc} />
            {!queue && oldVersionAvailable && (
              <span className='text-xs text-muted-foreground'>旧版可检索</span>
            )}
            {!queue &&
              doc.status === 'unconfigured' &&
              !oldVersionAvailable &&
              doc.active_generation_id && (
                <span className='text-xs text-muted-foreground'>
                  可关键词检索
                </span>
              )}
            {queue && doc.status === 'indexing' && doc.chunk_count > 0 && (
              <div className='flex w-full max-w-36 flex-col gap-1'>
                <Progress
                  aria-label={`${doc.filename} 索引进度`}
                  value={Math.min(
                    100,
                    (doc.indexed_count / doc.chunk_count) * 100
                  )}
                />
                <span className='text-xs text-muted-foreground tabular-nums'>
                  {doc.indexed_count} / {doc.chunk_count}
                </span>
              </div>
            )}
          </div>
        </TableCell>
        <TableCell>
          <div className='flex justify-end gap-0.5'>
            {queue && (
              <Button
                size='icon-sm'
                variant='ghost'
                aria-label={`${expanded ? '收起' : '展开'} ${doc.filename} 处理详情`}
                aria-expanded={expanded}
                onClick={onExpand}
              >
                {expanded ? <ChevronUp /> : <ChevronDown />}
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size='icon-sm'
                  variant='ghost'
                  aria-label={`${doc.filename} 操作`}
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuGroup>
                  <DropdownMenuItem asChild>
                    <a
                      href={`/api/v1/knowledge/${baseId}/documents/${doc.id}/source`}
                      download={doc.filename}
                    >
                      <Download />
                      下载原件
                    </a>
                  </DropdownMenuItem>
                  {canManage && (
                    <>
                      <DropdownMenuItem
                        disabled={busy(doc.status)}
                        onSelect={() => onChange('rebuild')}
                      >
                        <RefreshCw />
                        {documentNeedsAttention(doc) ? '重试处理' : '重新处理'}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant='destructive'
                        onSelect={() => onChange('delete')}
                      >
                        <Trash2 />
                        删除文档
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </TableCell>
      </TableRow>
      {queue && expanded && (
        <TableRow>
          <TableCell
            colSpan={3}
            className='bg-muted/20 px-3 py-4 whitespace-normal'
          >
            <dl className='flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground'>
              <div className='flex gap-2'>
                <dt>上传时间</dt>
                <dd>{date}</dd>
              </div>
              <div className='flex gap-2'>
                <dt>已生成切片</dt>
                <dd>{formatNumber(doc.chunk_count)}</dd>
              </div>
              {doc.indexed_count > 0 && (
                <div className='flex gap-2'>
                  <dt>已建立向量索引</dt>
                  <dd>{formatNumber(doc.indexed_count)}</dd>
                </div>
              )}
            </dl>
            {doc.error && (
              <p className='mt-2 text-sm wrap-anywhere text-destructive'>
                {doc.error}
              </p>
            )}
            {oldVersionAvailable && (
              <p className='mt-2 text-sm text-muted-foreground'>
                上一版本仍可检索。
              </p>
            )}
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

function DocumentStatus({ doc }: { doc: Document }) {
  const status: Record<string, string> = {
    queued: '等待处理',
    parsing: '解析中',
    chunking: '切片中',
    indexing: '索引中',
    waiting: '等待服务',
    ready: '可检索',
    unconfigured: '待配置向量',
    failed: '处理失败',
    uncertain: '处理失败',
    cancelled: '已取消',
  }
  return (
    <Badge
      dot
      variant={
        doc.status === 'ready'
          ? 'success'
          : ['failed', 'uncertain'].includes(doc.status)
            ? 'destructive'
            : busy(doc.status) && !['queued', 'waiting'].includes(doc.status)
              ? 'default'
              : 'secondary'
      }
    >
      {status[doc.status] ?? '未知状态'}
    </Badge>
  )
}

const fileFormatMarks = new Map([
  [
    'pdf',
    { mark: <span className='text-[7px]'>PDF</span>, color: 'bg-destructive' },
  ],
  ['docx', { mark: 'W', color: 'bg-info' }],
  ['xlsx', { mark: 'X', color: 'bg-success' }],
  ['csv', { mark: <Table2 className='size-2.5' />, color: 'bg-success' }],
  ['md', { mark: 'M↓', color: 'bg-info' }],
])

function DocumentFileIcon({ doc }: { doc: Document }) {
  const extension = doc.filename.match(/\.([^.]+)$/)?.[1].toLowerCase() ?? ''
  const { mark, color } =
    fileFormatMarks.get(extension) ??
    (doc.media_type.startsWith('image/')
      ? { mark: <Image className='size-2.5' />, color: 'bg-warning' }
      : {
          mark: <AlignLeft className='size-2.5' />,
          color: 'bg-muted-foreground',
        })
  return (
    <span
      aria-hidden
      className={cn(
        'grid size-4 shrink-0 place-items-center rounded-[2px] pt-0.5 text-[9px] leading-none font-bold text-background [clip-path:polygon(0_0,72%_0,100%_28%,100%_100%,0_100%)]',
        color
      )}
    >
      {mark}
    </span>
  )
}
