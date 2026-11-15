import { useState, useSyncExternalStore } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  ArrowLeft,
  BookOpen,
  FileText,
  ListTodo,
  Plus,
  Search,
  Settings2,
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
  Collapsible,
  CollapsibleContent,
  CollapsibleSection,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
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
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { PageBack, PageHeader } from '@/components/layout/page-header'
import { PageShell } from '@/components/layout/page-shell'
import { ListPagination } from '@/components/list-pagination'
import { ListSearch, ListToolbar } from '@/components/list-toolbar'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceCard } from '@/components/resource-card'
import { Choice, State } from './controls'
import { CreateKnowledge } from './create'
import { KnowledgeDefaults } from './defaults'
import { documentNeedsProcessing, useDocuments } from './document-data'
import { Documents } from './documents'
import { BaseFields, ChunkFields } from './forms'
import { KnowledgeAvatar, SavedKnowledgeIcon } from './icon'
import { RetrievalFields } from './retrieval-fields'
import {
  chunkingError,
  defaultsPath,
  initial,
  locationLabel,
  retrievalError,
  retrievalLabels,
  useKnowledge,
  useKnowledgeData,
  type Base,
  type BaseInput,
  type Citation,
  type Defaults,
  type RetrievalPolicy,
} from './shared'
import { SourceDialog } from './source'

type Navigation = {
  base?: string
  view?: 'create' | 'defaults'
  tab?: 'queue' | 'search' | 'settings'
}

const knowledgeRailQuery = '(min-width: 70rem)'
function subscribeKnowledgeLayout(onChange: () => void) {
  const media = window.matchMedia(knowledgeRailQuery)
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}
export function KnowledgePage({
  baseId,
  view,
  initialTab,
  onOpen,
}: {
  baseId?: string
  view?: Navigation['view']
  initialTab?: Navigation['tab']
  onOpen: (v: Navigation) => void
}) {
  const { admin } = useKnowledge()
  if (view === 'defaults' || view === 'create')
    return (
      <PageShell
        title={view === 'defaults' ? '知识库默认配置' : '创建知识库'}
        titleBefore={<PageBack label='返回知识库' onClick={() => onOpen({})} />}
      >
        {!admin ? (
          <Alert>
            <AlertDescription>此操作仅限组织管理员。</AlertDescription>
          </Alert>
        ) : view === 'defaults' ? (
          <KnowledgeDefaults />
        ) : (
          <CreateKnowledge onCreated={(base) => onOpen({ base })} />
        )}
      </PageShell>
    )
  if (baseId)
    return (
      <KnowledgeDetail
        key={baseId}
        id={baseId}
        onOpen={onOpen}
        initialTab={initialTab}
      />
    )
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
        className='shrink-0'
        onSubmit={(e) => {
          e.preventDefault()
          setQ(search)
          setPage(1)
        }}
      >
        <ListToolbar>
          <ListSearch
            aria-label='搜索知识库'
            placeholder='搜索知识库…'
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </ListToolbar>
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
          <div className='grid grid-cols-[repeat(auto-fill,minmax(min(100%,15rem),1fr))] gap-3'>
            {query.data.items.map((base) => (
              <ResourceCard
                key={base.id}
                name={base.name}
                description={base.description}
                icon={
                  base.icon?.image ? (
                    <KnowledgeAvatar image={base.icon.image} size='sm' />
                  ) : (
                    <BookOpen aria-hidden />
                  )
                }
                status={
                  base.status !== 'empty' && <State value={base.status} />
                }
                onOpen={() => onOpen({ base: base.id })}
                metadata={`${base.document_count} 份文档`}
              />
            ))}
          </div>
        )}
      </div>
      <ListPagination
        label='知识库分页'
        unit='个知识库'
        total={query.data?.total}
        page={page}
        pageCount={Math.ceil((query.data?.total ?? 0) / 20)}
        onPage={setPage}
        disabled={!query.isSuccess || query.isFetching}
      />
    </PageShell>
  )
}
function audienceLabel(base: Base) {
  return {
    administrators: '仅管理员',
    organization: '组织全员',
    selected: '指定范围',
  }[base.audience ?? 'administrators']
}
function KnowledgeDetail({
  id,
  onOpen,
  initialTab,
}: {
  id: string
  onOpen: (v: Navigation) => void
  initialTab?: Navigation['tab']
}) {
  const query = useKnowledgeData<Base>(`/knowledge/${id}`)
  const documents = useDocuments(id, query.isSuccess)
  const showRail = useSyncExternalStore(
    subscribeKnowledgeLayout,
    () => window.matchMedia(knowledgeRailQuery).matches,
    () => false
  )
  if (query.isPending)
    return (
      <PageShell>
        <LoadingState />
      </PageShell>
    )
  if (query.isError)
    return (
      <PageShell
        title='知识库'
        titleBefore={
          <PageBack label='返回全部知识库' onClick={() => onOpen({})} />
        }
      >
        <RequestError error={query.error} retry={() => void query.refetch()} />
      </PageShell>
    )
  const base = query.data
  const tab =
    initialTab === 'settings' && !base.can_manage
      ? 'documents'
      : (initialTab ?? 'documents')
  const queueCount = documents.data?.filter(documentNeedsProcessing).length ?? 0
  const audience = <Badge variant='outline'>{audienceLabel(base)}</Badge>
  const avatar = (
    <SavedKnowledgeIcon
      base={base}
      editable={base.can_manage && tab !== 'settings'}
      size='sm'
      showCamera={false}
    />
  )
  const back = () => onOpen({})
  const tabClassName = showRail
    ? 'min-h-9 rounded-lg px-3 py-2 md:gap-2 md:px-3'
    : 'px-2'
  return (
    <PageShell fixedContent>
      <Tabs
        className={cn(
          'min-h-0 min-w-0 flex-1 gap-3',
          showRail && 'flex-row gap-5'
        )}
        orientation={showRail ? 'vertical' : 'horizontal'}
        value={tab}
        onValueChange={(value) =>
          onOpen({
            base: id,
            tab:
              value === 'queue' || value === 'search' || value === 'settings'
                ? value
                : undefined,
          })
        }
      >
        <div
          className={cn(
            'flex min-w-0 shrink-0',
            showRail
              ? 'w-44 flex-col gap-3 overflow-y-auto border-e pe-3'
              : 'flex-col gap-4'
          )}
        >
          {showRail ? (
            <>
              <Button
                size='sm'
                variant='ghost'
                className='self-start'
                onClick={back}
              >
                <ArrowLeft data-icon='inline-start' />
                全部知识库
              </Button>
              <div className='flex min-w-0 flex-col gap-1.5'>
                <PageHeader
                  title={base.name}
                  titleBefore={avatar}
                  truncateTitle
                />
                {audience}
              </div>
            </>
          ) : (
            <div className='min-w-0'>
              <PageHeader
                title={base.name}
                truncateTitle
                titleBefore={
                  <>
                    <PageBack label='返回全部知识库' onClick={back} />
                    {avatar}
                  </>
                }
                titleAfter={audience}
              />
            </div>
          )}
          <TabsList
            variant={showRail ? 'navigation' : 'line'}
            aria-label='知识库导航'
            className={cn('gap-1', !showRail && 'h-9')}
          >
            <TabsTrigger value='documents' className={tabClassName}>
              <FileText className='hidden @lg/content:block' aria-hidden />
              文档
              <Badge variant='secondary' className={cn(showRail && 'ms-auto')}>
                {documents.data?.length ?? base.document_count}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value='queue' className={tabClassName}>
              <ListTodo className='hidden @lg/content:block' aria-hidden />
              处理队列
              {queueCount > 0 && (
                <Badge
                  variant='secondary'
                  title='当前队列任务'
                  className={cn(showRail && 'ms-auto')}
                >
                  {queueCount}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value='search' className={tabClassName}>
              <Search className='hidden @lg/content:block' aria-hidden />
              检索测试
            </TabsTrigger>
            {base.can_manage && (
              <TabsTrigger value='settings' className={tabClassName}>
                <Settings2 className='hidden @lg/content:block' aria-hidden />
                设置
              </TabsTrigger>
            )}
          </TabsList>
        </div>
        <div className='flex min-h-0 min-w-0 flex-1 flex-col gap-3'>
          {showRail && (tab === 'search' || tab === 'settings') && (
            <h2 className='shrink-0 text-lg font-semibold'>
              {tab === 'search' ? '检索测试' : '知识库设置'}
            </h2>
          )}
          <TabsContent value='documents' className='flex min-h-0 flex-col'>
            <Documents base={base} query={documents} />
          </TabsContent>
          <TabsContent value='queue' className='flex min-h-0 flex-col'>
            <Documents base={base} query={documents} queue />
          </TabsContent>
          <TabsContent value='search' className='-m-1 min-h-0 overflow-auto p-1'>
            <SearchKnowledge base={base} />
          </TabsContent>
          {base.can_manage && (
            <TabsContent value='settings' className='min-h-0 overflow-auto'>
              <BaseSettings key={base.version} base={base} onArchived={back} />
            </TabsContent>
          )}
        </div>
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
              {retrievalLabels[search.data.mode]}
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
                    {hit.sources.length > 0
                      ? `${locationLabel(hit.sources[0])} · ${hit.sources.length} 处来源`
                      : '无可用原文位置'}
                  </CardDescription>
                </CardHeader>
                <CardContent className='flex flex-col gap-4'>
                  <p className='text-sm leading-7 whitespace-pre-wrap'>
                    {hit.content}
                  </p>
                  {hit.parent_context && (
                    <CollapsibleSection title='父片上下文'>
                      <p className='text-sm leading-7 whitespace-pre-wrap'>
                        {hit.parent_context.content}
                      </p>
                    </CollapsibleSection>
                  )}
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
  const defaults = useKnowledgeData<Defaults>(defaultsPath)
  const [policy, setPolicy] = useState<RetrievalPolicy | null>(null)
  const fixedEmbeddingId =
    base.document_count && typeof base.embedding_profile.model_id === 'string'
      ? base.embedding_profile.model_id
      : undefined
  const invalidPolicy =
    policy && defaults.data ? retrievalError(policy, defaults.data) : undefined
  const save = useMutation({
    mutationFn: () =>
      api(
        `/knowledge/${base.id}`,
        'PUT',
        {
          ...body,
          ...(policy ? { retrieval: policy } : {}),
          version: base.version,
        },
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
        <CardContent className='flex flex-col gap-6'>
          <BaseFields value={body} onChange={setBody} icon={base.icon} />
          <Separator />
          <ChunkFields
            value={body.chunking ?? initial.chunking!}
            onChange={(v) => setBody({ ...body, chunking: v })}
          />
          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button variant='outline'>
                检索配置 ·{' '}
                {retrievalLabels[(policy ?? base.retrieval).mode ?? 'keyword']}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className='pt-4'>
              {defaults.isPending ? (
                <LoadingState />
              ) : defaults.isError ? (
                <RequestError
                  error={defaults.error}
                  retry={() => void defaults.refetch()}
                />
              ) : (
                <RetrievalFields
                  data={defaults.data}
                  value={policy ?? base.retrieval}
                  onChange={setPolicy}
                  fixedEmbeddingId={fixedEmbeddingId}
                />
              )}
              {fixedEmbeddingId && (
                <p className='mt-3 text-sm text-muted-foreground'>
                  已有文档使用固定向量模型。更换模型请新建知识库。
                </p>
              )}
              {base.retrieval.mode === 'keyword' &&
                policy?.mode &&
                policy.mode !== 'keyword' &&
                base.document_count > 0 && (
                  <p className='mt-3 text-sm text-muted-foreground'>
                    保存后，可在文档列表中重新处理已有文档以建立向量索引。
                  </p>
                )}
              {invalidPolicy && (
                <p role='alert' className='mt-3 text-sm text-destructive'>
                  {invalidPolicy}
                </p>
              )}
            </CollapsibleContent>
          </Collapsible>
        </CardContent>
        <CardFooter className='justify-end'>
          <Button
            disabled={
              save.isPending ||
              !body.name.trim() ||
              Boolean(invalidPolicy) ||
              Boolean(chunkingError(body.chunking ?? initial.chunking!))
            }
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
