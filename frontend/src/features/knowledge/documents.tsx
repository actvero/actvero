import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  LoaderCircle,
  MoreHorizontal,
  Search,
  Upload,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, dateTime, messageOf } from '@/lib/api'
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
  EmptyHeader,
  EmptyTitle,
  EmptyMedia,
} from '@/components/ui/empty'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import { Progress } from '@/components/ui/progress'
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from '@/components/ui/table'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { packageSize } from '@/features/workbenches/shared'
import { Choice, State } from './controls'
import { DocumentDialog } from './document-reader'
import {
  busy,
  useKnowledge,
  useKnowledgeData,
  type Base,
  type Document,
} from './shared'

export { DocumentDialog } from './document-reader'

export const accept = '.pdf,.png,.jpg,.jpeg,.txt,.md,.csv,.docx,.xlsx'
export function UploadButton({
  baseId,
  onComplete,
}: {
  baseId: string
  onComplete?: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const { csrf, refresh } = useKnowledge()
  const [failure, setFailure] = useState<{ file: File; id: string }[]>([])
  const upload = useMutation({
    mutationFn: async (files: { file: File; id: string }[]) => {
      const failed: typeof files = []
      for (const item of files) {
        try {
          await api(
            `/knowledge/${baseId}/documents?filename=${encodeURIComponent(item.file.name)}&upload_id=${item.id}`,
            'POST',
            item.file,
            csrf
          )
        } catch (e) {
          failed.push(item)
          toast.error(`${item.file.name}：${messageOf(e)}`)
        }
      }
      setFailure(failed)
    },
    onSuccess: () => {
      void refresh()
      onComplete?.()
    },
  })
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <input
        ref={input}
        className='sr-only'
        type='file'
        accept={accept}
        multiple
        aria-label='上传知识库文档'
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ''
          upload.mutate(
            files.map((file) => ({ file, id: crypto.randomUUID() }))
          )
        }}
      />
      <Button
        disabled={upload.isPending}
        onClick={() => input.current?.click()}
      >
        <Upload data-icon='inline-start' />
        {upload.isPending ? '正在上传…' : '上传文档'}
      </Button>
      {failure.length > 0 && (
        <Button
          disabled={upload.isPending}
          variant='outline'
          onClick={() => upload.mutate(failure)}
        >
          重试 {failure.length} 个上传
        </Button>
      )}
    </div>
  )
}
export function Documents({
  base,
  queue = false,
}: {
  base: Base
  queue?: boolean
}) {
  const query = useKnowledgeData<Document[]>(
    `/knowledge/${base.id}/documents`,
    true
  )
  const { csrf, refresh } = useKnowledge()
  const [opened, setOpened] = useState<Document | null>(null)
  const [expanded, setExpanded] = useState<string>()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [confirm, setConfirm] = useState<{
    doc: Document
    action: 'delete' | 'rebuild'
  } | null>(null)
  const mutation = useMutation({
    mutationFn: async () => {
      if (!confirm) return
      const { doc, action } = confirm
      return api(
        `/knowledge/${base.id}/documents/${doc.id}${action === 'rebuild' ? '/rebuild' : ''}`,
        action === 'delete' ? 'DELETE' : 'POST',
        action === 'rebuild'
          ? {
              generation_id: doc.generation_id,
              chunking: base.chunking,
              use_current_defaults: !Object.keys(base.embedding_profile).length,
            }
          : undefined,
        csrf
      )
    },
    onSuccess: () => {
      setConfirm(null)
      void refresh()
      toast.success('操作已完成')
    },
    onError: (e) => toast.error(messageOf(e)),
  })
  const filtered = (query.data ?? []).filter(
    (doc) =>
      (!queue ||
        status === 'completed' ||
        !['ready', 'unconfigured'].includes(doc.status)) &&
      doc.filename.toLocaleLowerCase().includes(search.toLocaleLowerCase()) &&
      (status === 'all' ||
        (status === 'processing' &&
          busy(doc.status) &&
          doc.status !== 'queued') ||
        (status === 'failed' && ['failed', 'uncertain'].includes(doc.status)) ||
        (status === 'completed' &&
          ['ready', 'unconfigured'].includes(doc.status)) ||
        doc.status === status)
  )
  const currentPage = Math.min(
    page,
    Math.max(1, Math.ceil(filtered.length / 20))
  )
  const items = filtered.slice((currentPage - 1) * 20, currentPage * 20)
  return (
    <div className='flex min-h-0 flex-1 flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-3'>
        <InputGroup className='max-w-sm'>
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
          <InputGroupInput
            aria-label='搜索文档'
            placeholder='搜索文档…'
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
          />
        </InputGroup>
        <div className='w-40'>
          <Choice
            label='文档状态'
            value={status}
            onChange={(v) => {
              setStatus(v)
              setPage(1)
            }}
            items={[
              { value: 'all', label: '全部状态' },
              { value: 'processing', label: '处理中' },
              { value: 'queued', label: '排队中' },
              { value: 'failed', label: '处理失败' },
              { value: 'waiting', label: '等待服务' },
              { value: 'completed', label: '已完成' },
            ]}
          />
        </div>
        {queue && (
          <Button
            variant='ghost'
            size='icon'
            aria-label='刷新队列'
            className='ms-auto'
            onClick={() => void query.refetch()}
          >
            <RefreshCw />
          </Button>
        )}
      </div>
      <div className='min-h-0 flex-1 overflow-auto'>
        {query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <RequestError error={query.error} />
        ) : !items.length ? (
          <Empty className='min-h-64 border'>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <FileText />
              </EmptyMedia>
              <EmptyTitle>
                {query.data.length ? '没有符合条件的文档' : '添加第一份资料'}
              </EmptyTitle>
            </EmptyHeader>
            {!query.data.length && base.can_manage && (
              <UploadButton baseId={base.id} />
            )}
          </Empty>
        ) : (
          <div className='overflow-hidden rounded-lg border'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>文档</TableHead>
                  <TableHead>{queue ? '当前阶段' : '状态'}</TableHead>
                  <TableHead>{queue ? '进度' : '切片'}</TableHead>
                  <TableHead>{queue ? '详情' : '上传时间'}</TableHead>
                  <TableHead className='text-right'>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((doc) => (
                  <DocumentRow
                    key={doc.id}
                    doc={doc}
                    queue={queue}
                    expanded={expanded === doc.id}
                    onExpand={() =>
                      setExpanded(expanded === doc.id ? undefined : doc.id)
                    }
                    onOpen={() => setOpened(doc)}
                  >
                    {base.can_manage && (
                      <div className='flex items-center justify-end gap-1'>
                        {['failed', 'uncertain', 'unconfigured'].includes(
                          doc.status
                        ) && (
                          <Button
                            size='sm'
                            variant='ghost'
                            onClick={() =>
                              setConfirm({ doc, action: 'rebuild' })
                            }
                          >
                            重试
                          </Button>
                        )}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              size='icon'
                              variant='ghost'
                              aria-label={`${doc.filename} 操作`}
                            >
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align='end'>
                            <DropdownMenuGroup>
                              <DropdownMenuItem onSelect={() => setOpened(doc)}>
                                <FileText />
                                打开文档
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                disabled={busy(doc.status)}
                                onSelect={() =>
                                  setConfirm({ doc, action: 'rebuild' })
                                }
                              >
                                <RefreshCw />
                                重新处理
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() =>
                                  setConfirm({ doc, action: 'delete' })
                                }
                              >
                                <Trash2 />
                                删除文档
                              </DropdownMenuItem>
                            </DropdownMenuGroup>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    )}
                  </DocumentRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
      <footer className='mt-auto flex shrink-0 items-center justify-between gap-3 pt-3'>
        <span className='text-sm text-muted-foreground'>
          共 {filtered.length} {queue ? '个任务' : '份文档'}
        </span>
        <div className='flex items-center gap-3'>
          <Button
            size='icon'
            variant='outline'
            aria-label='上一页文档'
            disabled={currentPage === 1}
            onClick={() => setPage(currentPage - 1)}
          >
            <ChevronLeft />
          </Button>
          <span className='text-sm'>
            {currentPage} / {Math.max(1, Math.ceil(filtered.length / 20))}
          </span>
          <Button
            size='icon'
            variant='outline'
            aria-label='下一页文档'
            disabled={currentPage * 20 >= filtered.length}
            onClick={() => setPage(currentPage + 1)}
          >
            <ChevronRight />
          </Button>
        </div>
      </footer>
      <DocumentDialog
        key={opened?.id ?? 'closed'}
        base={base}
        doc={opened}
        onClose={() => setOpened(null)}
      />
      <ConfirmDialog
        cancelBtnText='取消'
        open={!!confirm}
        onOpenChange={(v) => {
          if (!v) setConfirm(null)
        }}
        title={confirm?.action === 'delete' ? '删除文档？' : '重新处理文档？'}
        desc={
          confirm?.action === 'delete'
            ? '删除后，此文档的检索和历史引用将立即停止访问。'
            : '生成新的处理版本，旧索引在新版本完成前继续可用。模型调用计入现有用量。'
        }
        confirmText={confirm?.action === 'delete' ? '删除' : '重新处理'}
        isLoading={mutation.isPending}
        handleConfirm={() => mutation.mutate()}
      />
    </div>
  )
}

function DocumentRow({
  doc,
  queue,
  expanded,
  onExpand,
  onOpen,
  children,
}: {
  doc: Document
  queue: boolean
  expanded: boolean
  onExpand: () => void
  onOpen: () => void
  children: React.ReactNode
}) {
  const stage = ['queued', 'parsing', 'chunking', 'indexing', 'ready'].indexOf(
    doc.status
  )
  return (
    <>
      <TableRow>
        <TableCell>
          <div className='flex items-center gap-3'>
            <FileText className='size-5 shrink-0 text-muted-foreground' />
            <div className='min-w-0'>
              <Button
                variant='link'
                className='h-auto max-w-72 justify-start p-0 text-left whitespace-normal'
                onClick={onOpen}
              >
                {doc.filename}
              </Button>
              <p className='mt-1 text-xs text-muted-foreground'>
                {packageSize(doc.size)}
              </p>
            </div>
          </div>
        </TableCell>
        <TableCell>
          <State value={doc.status} />
        </TableCell>
        <TableCell>
          {queue ? (
            <div className='flex min-w-32 flex-col gap-2'>
              {doc.status === 'indexing' && doc.chunk_count > 0 ? (
                <>
                  <Progress
                    aria-label='索引进度'
                    value={(doc.indexed_count / doc.chunk_count) * 100}
                  />
                  <span className='text-xs text-muted-foreground'>
                    {doc.indexed_count} / {doc.chunk_count} 个切片
                  </span>
                </>
              ) : busy(doc.status) && doc.status !== 'queued' ? (
                <LoaderCircle
                  className='size-4 animate-spin text-muted-foreground'
                  aria-label='处理中'
                />
              ) : (
                <span className='text-sm text-muted-foreground'>
                  {doc.status === 'queued'
                    ? '等待处理'
                    : doc.indexed_count
                      ? `${doc.indexed_count} 个已索引`
                      : '—'}
                </span>
              )}
            </div>
          ) : (
            doc.chunk_count || '—'
          )}
        </TableCell>
        <TableCell>
          {queue ? (
            <Button
              size='sm'
              variant='ghost'
              aria-expanded={expanded}
              onClick={onExpand}
            >
              处理详情
              <ChevronDown data-icon='inline-end' />
            </Button>
          ) : (
            <span className='whitespace-nowrap text-muted-foreground'>
              {dateTime(doc.created_at)}
            </span>
          )}
        </TableCell>
        <TableCell>{children}</TableCell>
      </TableRow>
      {queue && expanded && (
        <TableRow>
          <TableCell colSpan={5} className='bg-muted/30 px-6 py-5'>
            <div className='flex flex-col gap-4'>
              <ol className='flex flex-wrap items-center gap-6'>
                {['已上传', '解析', '切片', '索引'].map((label, i) => (
                  <li
                    key={label}
                    className={cn(
                      'flex items-center gap-2 text-sm text-muted-foreground',
                      stage >= i && 'text-foreground'
                    )}
                  >
                    {stage > i || i === 0 ? (
                      <Check className='size-4 text-success' />
                    ) : (
                      <Badge variant='outline'>{i + 1}</Badge>
                    )}
                    {label}
                  </li>
                ))}
              </ol>
              {doc.error && (
                <p className='text-sm text-destructive'>{doc.error}</p>
              )}
              <Button
                className='self-start'
                variant='outline'
                size='sm'
                disabled={!doc.chunk_count}
                onClick={onOpen}
              >
                查看已生成切片
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
