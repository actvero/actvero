import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  ArrowLeft,
  BookOpen,
  Plus,
  Search,
  Settings2,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Check,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, messageOf, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from '@/components/ui/card'
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyMedia,
} from '@/components/ui/empty'
import { Field, FieldGroup } from '@/components/ui/field'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { Choice, State } from './controls'
import { KnowledgeDefaults } from './defaults'
import { Documents, UploadButton } from './documents'
import { BaseFields, ChunkFields } from './forms'
import {
  busy,
  initial,
  locationLabel,
  useKnowledge,
  useKnowledgeData,
  type Base,
  type BaseInput,
  type Citation,
  type Document,
} from './shared'
import { SourceDialog } from './source'

type Navigation = { base?: string; view?: 'create' | 'defaults' }
export function KnowledgePage({
  baseId,
  view,
  onOpen,
}: {
  baseId?: string
  view?: Navigation['view']
  onOpen: (v: Navigation) => void
}) {
  const { admin } = useKnowledge()
  if (view === 'defaults' || view === 'create')
    return (
      <PageShell
        title={view === 'defaults' ? '知识库默认配置' : '创建知识库'}
        titleBefore={
          <Button
            variant='ghost'
            size='icon'
            aria-label='返回知识库'
            onClick={() => onOpen({})}
          >
            <ArrowLeft />
          </Button>
        }
      >
        {!admin ? (
          <Alert>
            <AlertDescription>此操作仅限组织管理员。</AlertDescription>
          </Alert>
        ) : view === 'defaults' ? (
          <KnowledgeDefaults />
        ) : (
          <CreateKnowledge onOpen={onOpen} />
        )}
      </PageShell>
    )
  if (baseId)
    return <KnowledgeDetail key={baseId} id={baseId} onOpen={onOpen} />
  return <KnowledgeList onOpen={onOpen} />
}
function KnowledgeList({ onOpen }: { onOpen: (v: Navigation) => void }) {
  const { admin } = useKnowledge()
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const query = useKnowledgeData<Schema['KnowledgePage']>(
    `/knowledge?q=${encodeURIComponent(q)}&page=${page}`,
    true
  )
  return (
    <PageShell
      title='知识库'
      fixedContent
      action={
        admin && (
          <div className='flex gap-2'>
            <Button
              variant='outline'
              onClick={() => onOpen({ view: 'defaults' })}
            >
              <Settings2 data-icon='inline-start' />
              默认配置
            </Button>
            <Button onClick={() => onOpen({ view: 'create' })}>
              <Plus data-icon='inline-start' />
              创建知识库
            </Button>
          </div>
        )
      }
    >
      <form
        className='w-full max-w-md shrink-0'
        onSubmit={(e) => {
          e.preventDefault()
          setQ(search)
          setPage(1)
        }}
      >
        <InputGroup>
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
          <InputGroupInput
            aria-label='搜索知识库'
            placeholder='搜索知识库…'
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </InputGroup>
      </form>
      <div className='min-h-0 flex-1 overflow-auto pb-2'>
        {query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : !query.data.items.length ? (
          <Empty className='min-h-64 border'>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <BookOpen />
              </EmptyMedia>
              <EmptyTitle>
                {q ? '没有找到知识库' : '创建第一个知识库'}
              </EmptyTitle>
            </EmptyHeader>
            {admin && !q && (
              <Button onClick={() => onOpen({ view: 'create' })}>
                创建知识库
              </Button>
            )}
          </Empty>
        ) : (
          <div className='grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3'>
            {query.data.items.map((base) => (
              <Card
                key={base.id}
                asChild
                interactive
                density='compact'
                className='min-h-52'
              >
                <button
                  type='button'
                  className='text-start'
                  onClick={() => onOpen({ base: base.id })}
                >
                  <CardHeader className='gap-3 px-5 pt-3'>
                    <div className='flex items-center justify-between'>
                      <BookOpen className='size-5 text-muted-foreground' />
                      <ArrowRight className='size-4 text-muted-foreground' />
                    </div>
                    <CardTitle>{base.name}</CardTitle>
                    <CardDescription className='line-clamp-1'>
                      {base.description || '\u00a0'}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className='px-5 py-3'>
                    <State value={base.status} />
                  </CardContent>
                  <CardFooter className='mt-auto flex-wrap gap-x-3 gap-y-1 px-5 pb-2 text-xs text-muted-foreground'>
                    <span>{base.document_count}份文档</span>
                    <span>{audienceLabel(base)}</span>
                    <span className='ms-auto'>
                      {new Date(base.updated_at).toLocaleDateString('zh-CN')}
                    </span>
                  </CardFooter>
                </button>
              </Card>
            ))}
          </div>
        )}
      </div>
      <footer className='mt-auto flex shrink-0 items-center justify-between border-t pt-4'>
        <span className='text-sm text-muted-foreground'>
          共 {query.data?.total ?? 0} 个知识库
        </span>
        <div className='flex items-center gap-3'>
          <Button
            variant='outline'
            size='icon'
            aria-label='上一页知识库'
            disabled={page === 1}
            onClick={() => setPage((v) => v - 1)}
          >
            <ChevronLeft />
          </Button>
          <span className='text-sm'>
            {page} / {Math.max(1, Math.ceil((query.data?.total ?? 0) / 20))}
          </span>
          <Button
            variant='outline'
            size='icon'
            aria-label='下一页知识库'
            disabled={page * 20 >= (query.data?.total ?? 0)}
            onClick={() => setPage((v) => v + 1)}
          >
            <ChevronRight />
          </Button>
        </div>
      </footer>
    </PageShell>
  )
}
function audienceLabel(base: Base) {
  return {
    administrators: '仅管理员',
    organization: '全体成员',
    selected: '指定范围',
  }[base.audience ?? 'administrators']
}
function CreateKnowledge({ onOpen }: { onOpen: (v: Navigation) => void }) {
  const { csrf, refresh } = useKnowledge()
  const [step, setStep] = useState(1)
  const [body, setBody] = useState<BaseInput>(initial)
  const [created, setCreated] = useState<Base | null>(null)
  const create = useMutation({
    mutationFn: () => api<Base>('/knowledge', 'POST', body, csrf),
    onSuccess: (base) => {
      setCreated(base)
      setStep(3)
      void refresh()
    },
    onError: (e) => toast.error(messageOf(e)),
  })
  return (
    <div className='flex flex-col gap-6'>
      <ol
        className='grid max-w-4xl grid-cols-3 gap-2 rounded-lg border bg-muted/30 p-4'
        aria-label='创建进度'
      >
        {['基本信息', '切片设置', '上传文档'].map((label, i) => (
          <li
            key={label}
            aria-current={step === i + 1 ? 'step' : undefined}
            className='flex items-center gap-3'
          >
            <span
              className={cn(
                'flex size-7 shrink-0 items-center justify-center rounded-full text-sm',
                step >= i + 1
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground'
              )}
            >
              {step > i + 1 ? <Check className='size-4' /> : i + 1}
            </span>
            <span
              className={cn(
                'text-sm',
                step === i + 1 ? 'font-semibold' : 'text-muted-foreground'
              )}
            >
              {label}
            </span>
            {i < 2 && (
              <span className='ms-1 hidden h-px flex-1 bg-border sm:block' />
            )}
          </li>
        ))}
      </ol>
      {step < 3 ? (
        <Card className='max-w-4xl'>
          <CardHeader>
            <CardTitle>{step === 1 ? '基本信息' : '切片设置'}</CardTitle>
          </CardHeader>
          <CardContent>
            {step === 1 ? (
              <BaseFields value={body} onChange={setBody} />
            ) : (
              <ChunkFields
                value={body.chunking ?? initial.chunking!}
                onChange={(v) => setBody({ ...body, chunking: v })}
              />
            )}
          </CardContent>
          <CardFooter className='justify-end gap-2'>
            {step === 2 && (
              <Button
                variant='outline'
                disabled={create.isPending}
                onClick={() => setStep(1)}
              >
                上一步
              </Button>
            )}
            <Button
              disabled={!body.name.trim() || create.isPending}
              onClick={() => (step === 1 ? setStep(2) : create.mutate())}
            >
              {step === 1 ? '下一步' : '创建并上传文档'}
            </Button>
          </CardFooter>
        </Card>
      ) : (
        created && (
          <>
            <div className='flex items-center justify-between gap-3'>
              <span className='font-medium'>{created.name}</span>
              <UploadButton baseId={created.id} />
            </div>
            <Documents base={created} />
            <div className='flex justify-end'>
              <Button onClick={() => onOpen({ base: created.id })}>
                完成，进入知识库
              </Button>
            </div>
          </>
        )
      )}
    </div>
  )
}
function KnowledgeDetail({
  id,
  onOpen,
}: {
  id: string
  onOpen: (v: Navigation) => void
}) {
  const query = useKnowledgeData<Base>(`/knowledge/${id}`, true)
  const documents = useKnowledgeData<Document[]>(
    `/knowledge/${id}/documents`,
    true
  )
  const [tab, setTab] = useState('documents')
  if (query.isPending)
    return (
      <PageShell>
        <LoadingState />
      </PageShell>
    )
  if (query.isError)
    return (
      <PageShell title='知识库'>
        <RequestError error={query.error} />
        <Button variant='outline' onClick={() => onOpen({})}>
          返回知识库
        </Button>
      </PageShell>
    )
  const base = query.data
  const queueCount = (documents.data ?? []).filter(
    (doc) => busy(doc.status) || ['failed', 'uncertain'].includes(doc.status)
  ).length
  return (
    <PageShell
      fixedContent
      title={base.name}
      titleBefore={
        <Button
          variant='ghost'
          size='icon'
          aria-label='返回全部知识库'
          onClick={() => onOpen({})}
        >
          <ArrowLeft />
        </Button>
      }
      titleAfter={
        <span className='text-sm text-muted-foreground'>
          {audienceLabel(base)}
        </span>
      }
      action={
        base.can_manage && (
          <UploadButton baseId={base.id} onComplete={() => setTab('queue')} />
        )
      }
    >
      <Tabs className='min-h-0 flex-1' value={tab} onValueChange={setTab}>
        <TabsList variant='line' className='shrink-0 overflow-x-auto'>
          <TabsTrigger value='documents'>
            文档
            <Badge variant='secondary'>
              {documents.data?.length ?? base.document_count}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value='queue'>
            处理队列
            {queueCount > 0 && <Badge variant='secondary'>{queueCount}</Badge>}
          </TabsTrigger>
          <TabsTrigger value='search'>检索测试</TabsTrigger>
          {base.can_manage && <TabsTrigger value='settings'>设置</TabsTrigger>}
        </TabsList>
        <TabsContent value='documents' className='flex min-h-0 flex-col pt-4'>
          <Documents base={base} />
        </TabsContent>
        <TabsContent value='queue' className='flex min-h-0 flex-col pt-4'>
          <Documents base={base} queue />
        </TabsContent>
        <TabsContent value='search' className='min-h-0 overflow-auto pt-4'>
          <SearchKnowledge base={base} />
        </TabsContent>
        {base.can_manage && (
          <TabsContent value='settings' className='min-h-0 overflow-auto pt-4'>
            <BaseSettings
              key={base.version}
              base={base}
              onArchived={() => onOpen({})}
            />
          </TabsContent>
        )}
      </Tabs>
    </PageShell>
  )
}
function SearchKnowledge({ base }: { base: Base }) {
  const { csrf } = useKnowledge()
  const [query, setQuery] = useState('')
  const [count, setCount] = useState('5')
  const [citation, setCitation] = useState<Citation | null>(null)
  const search = useMutation({
    mutationFn: () =>
      api<Schema['RetrievalView']>(
        `/knowledge/${base.id}/search`,
        'POST',
        { query, limit: Number(count) },
        csrf
      ),
  })
  return (
    <div className='flex flex-col gap-6'>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!search.isPending && query.trim()) search.mutate()
        }}
      >
        <FieldGroup className='gap-3 sm:flex-row sm:items-center'>
          <Field className='min-w-0 flex-1'>
            <InputGroup>
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
              <InputGroupInput
                aria-label='检索问题'
                required
                maxLength={2000}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder='想查找什么？'
              />
            </InputGroup>
          </Field>
          <Field className='sm:w-auto'>
            <Choice
              label='返回数量'
              value={count}
              onChange={setCount}
              items={['3', '5', '10', '20'].map((v) => ({
                value: v,
                label: `返回 ${v} 条`,
              }))}
            />
          </Field>
          <Field className='sm:w-auto'>
            <Button disabled={search.isPending || !query.trim()} type='submit'>
              {search.isPending ? '检索中…' : '开始检索'}
            </Button>
          </Field>
        </FieldGroup>
      </form>
      <div className='flex min-w-0 flex-col gap-4'>
        {search.isError ? (
          <RequestError error={search.error} />
        ) : search.isPending ? (
          <LoadingState />
        ) : search.data ? (
          <>
            <p className='text-sm text-muted-foreground'>
              {search.data.mode === 'hybrid' ? '混合检索' : '关键词检索'}
              {search.data.reranked ? ' · 已重排序' : ''} ·{' '}
              {search.data.items.length} 条结果
            </p>
            {search.data.items.map((hit, i) => (
              <Card key={hit.id}>
                <CardHeader>
                  <CardTitle className='flex items-center gap-2'>
                    <Badge variant='outline'>{i + 1}</Badge>
                    {hit.filename}
                  </CardTitle>
                  <CardDescription>
                    {locationLabel(hit.sources[0])} · {hit.sources.length}{' '}
                    处来源
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className='text-sm leading-7 whitespace-pre-wrap'>
                    {hit.content}
                  </p>
                </CardContent>
                <CardFooter className='justify-end'>
                  <Button
                    variant='outline'
                    size='sm'
                    onClick={() => setCitation(hit)}
                  >
                    查看原文 ↗
                  </Button>
                </CardFooter>
              </Card>
            ))}
            {!search.data.items.length && (
              <Empty>
                <EmptyHeader>
                  <EmptyTitle>未找到相关内容</EmptyTitle>
                  <EmptyDescription>
                    换个关键词，或检查文档是否已完成处理。
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            )}
          </>
        ) : (
          <Empty className='min-h-48'>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <Search />
              </EmptyMedia>
              <EmptyTitle>输入关键词开始检索</EmptyTitle>
            </EmptyHeader>
          </Empty>
        )}
      </div>
      <SourceDialog citation={citation} onClose={() => setCitation(null)} />
    </div>
  )
}
function BaseSettings({
  base,
  onArchived,
}: {
  base: Base
  onArchived: () => void
}) {
  const { csrf, refresh } = useKnowledge()
  const [body, setBody] = useState<BaseInput>({
    name: base.name,
    description: base.description,
    audience: base.audience,
    member_ids: base.member_ids,
    department_grants: base.department_grants,
    chunking: base.chunking,
  })
  const [confirm, setConfirm] = useState(false)
  const save = useMutation({
    mutationFn: () =>
      api(
        `/knowledge/${base.id}`,
        'PUT',
        { ...body, version: base.version },
        csrf
      ),
    onSuccess: () => {
      void refresh()
      toast.success('设置已保存')
    },
    onError: (e) => toast.error(messageOf(e)),
  })
  const archive = useMutation({
    mutationFn: () => api(`/knowledge/${base.id}`, 'DELETE', undefined, csrf),
    onSuccess: () => {
      void refresh()
      onArchived()
    },
    onError: (e) => toast.error(messageOf(e)),
  })
  return (
    <div className='flex max-w-3xl flex-col gap-6'>
      <Card>
        <CardHeader>
          <CardTitle>知识库设置</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-6'>
          <BaseFields value={body} onChange={setBody} />
          <ChunkFields
            value={body.chunking ?? initial.chunking!}
            onChange={(v) => setBody({ ...body, chunking: v })}
          />
          <p className='text-sm text-muted-foreground'>
            切片设置影响后续上传。已有文档可在文档列表中重新处理。
          </p>
        </CardContent>
        <CardFooter className='justify-end'>
          <Button
            disabled={save.isPending || !body.name.trim()}
            onClick={() => save.mutate()}
          >
            保存设置
          </Button>
        </CardFooter>
      </Card>
      <div>
        <Button variant='outline' onClick={() => setConfirm(true)}>
          归档知识库
        </Button>
      </div>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title='归档知识库？'
        desc='归档后，成员无法检索资料或打开已有引用。'
        confirmText='归档'
        cancelBtnText='取消'
        isLoading={archive.isPending}
        handleConfirm={() => archive.mutate()}
      />
    </div>
  )
}
