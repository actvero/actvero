import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { ArrowUpRight, LayoutGrid, List, Plus } from 'lucide-react'
import { api, dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ServerTable } from '@/components/data-table/server-table'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceIcon } from '@/components/resource-icon'
import { CategoriesDialog } from './categories-dialog'
import { useCategories } from './categories-query'
import { CategoryPicker } from './category-picker'
import { categoryLabel, scopeLabels, useSkills, type Skill } from './shared'
import { SkillStatusBadge } from './status-badge'

function activeVersion(skill: Skill) {
  return skill.versions.find(
    (v) => v.id === skill.default_version_id && v.status === 'published'
  )
}

function SkillBadges({ skill }: { skill: Skill }) {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <SkillStatusBadge
        status={activeVersion(skill) ? 'published' : 'inactive'}
      />
      {skill.versions.some((v) => v.status === 'draft') && (
        <Badge variant='outline'>有草稿</Badge>
      )}
    </div>
  )
}

function SkillCards({ items, empty }: { items: Skill[]; empty: string }) {
  if (!items.length)
    return (
      <Card>
        <CardContent className='py-8 text-center'>{empty}</CardContent>
      </Card>
    )
  return (
    <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
      {items.map((skill) => (
        <Card key={skill.id} asChild interactive className='min-w-0'>
          <Link
            to='/skills/$skillId'
            params={{ skillId: skill.id }}
            aria-label={`查看技能：${skill.display_name}`}
          >
            <CardHeader className='gap-3'>
              <div className='flex items-center justify-between gap-3'>
                <ResourceIcon
                  image={skill.icon?.image}
                  name={skill.display_name}
                />
                <SkillBadges skill={skill} />
              </div>
              <CardTitle className='flex min-w-0 items-start justify-between gap-3'>
                <span className='min-w-0 break-all'>{skill.display_name}</span>
                <ArrowUpRight className='size-4 shrink-0' aria-hidden='true' />
              </CardTitle>
              {skill.name !== skill.display_name && (
                <CardDescription className='truncate'>
                  {skill.name}
                </CardDescription>
              )}
            </CardHeader>
            <CardContent className='flex flex-1 flex-col gap-5'>
              <p className='line-clamp-3 text-sm leading-6 break-words text-muted-foreground'>
                {skill.description}
              </p>
              <div>
                <Badge variant='outline'>{categoryLabel(skill)}</Badge>
              </div>
              <dl className='mt-auto grid grid-cols-2 gap-4 text-sm'>
                <div className='flex min-w-0 flex-col gap-1'>
                  <dt className='text-muted-foreground'>生效版本</dt>
                  <dd className='break-all'>
                    {activeVersion(skill)
                      ? `v${activeVersion(skill)!.version}`
                      : '暂无生效版本'}
                  </dd>
                </div>
                <div className='flex min-w-0 flex-col gap-1'>
                  <dt className='text-muted-foreground'>使用范围</dt>
                  <dd>{scopeLabels[skill.audience]}</dd>
                </div>
              </dl>
            </CardContent>
            <CardFooter>
              <p className='text-xs text-muted-foreground'>
                创建于 {dateTime(skill.created_at)}
              </p>
            </CardFooter>
          </Link>
        </Card>
      ))}
    </div>
  )
}

const columns: ColumnDef<Skill>[] = [
  {
    accessorKey: 'display_name',
    header: '技能',
    cell: ({ row: { original: skill } }) => (
      <div className='flex max-w-sm items-center gap-3'>
        <ResourceIcon image={skill.icon?.image} name={skill.display_name} />
        <div className='flex min-w-0 flex-col gap-1'>
          <Link
            className='font-medium'
            to='/skills/$skillId'
            params={{ skillId: skill.id }}
          >
            {skill.display_name}
          </Link>
          <p className='truncate text-xs text-muted-foreground'>
            {skill.name !== skill.display_name && `${skill.name} · `}
            {skill.description}
          </p>
        </div>
      </div>
    ),
  },
  {
    accessorKey: 'category',
    header: '类别',
    cell: ({ row }) => (
      <Badge variant='outline'>{categoryLabel(row.original)}</Badge>
    ),
  },
  {
    id: 'version',
    header: '生效版本',
    cell: ({ row }) => activeVersion(row.original)?.version ?? '暂无生效版本',
  },
  {
    id: 'status',
    header: '状态',
    cell: ({ row }) => <SkillBadges skill={row.original} />,
  },
  {
    accessorKey: 'audience',
    header: '使用范围',
    cell: ({ row }) => scopeLabels[row.original.audience],
  },
  {
    accessorKey: 'created_at',
    header: '创建时间',
    cell: ({ row }) => dateTime(row.original.created_at),
  },
]
export function SkillsPage() {
  const navigate = useNavigate()
  const { key } = useSkills()
  const [categoriesOpen, setCategoriesOpen] = useState(false)
  const [view, setView] = useState('list')
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [audience, setAudience] = useState('all')
  const [status, setStatus] = useState('all')
  const [category, setCategory] = useState('all')
  const categories = useCategories()
  const selectedCategory =
    categories.data &&
    category !== 'all' &&
    !categories.data.some((item) => item.id === category)
      ? 'all'
      : category
  const currentPage = selectedCategory === category ? page : 1
  useEffect(() => {
    const id = setTimeout(() => {
      setQ(search.trim())
      setPage(1)
    }, 250)
    return () => clearTimeout(id)
  }, [search])
  const query = useQuery({
    queryKey: [
      ...key,
      'list',
      q,
      currentPage,
      audience,
      status,
      selectedCategory,
    ],
    queryFn: ({ signal }) =>
      api<Schema['SkillPage']>(
        `/skills?${new URLSearchParams({ q, page: String(currentPage), ...(audience === 'all' ? {} : { audience }), ...(status === 'all' ? {} : { status }), ...(selectedCategory === 'all' ? {} : { category: selectedCategory }) })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const empty =
    q || audience !== 'all' || status !== 'all' || category !== 'all'
      ? '没有符合条件的技能，请尝试清空筛选'
      : '还没有技能，点击“上传技能”从 ZIP 或文件夹开始'
  return (
    <PageShell
      title='技能管理'
      description='维护团队共享的技能，发布经过确认的版本。'
      action={
        <div className='flex flex-wrap gap-2'>
          <Button variant='outline' onClick={() => setCategoriesOpen(true)}>
            类别管理
          </Button>
          <Button asChild>
            <Link to='/skills/upload'>
              <Plus />
              上传技能
            </Link>
          </Button>
        </div>
      }
    >
      <Tabs value={view} onValueChange={setView} className='min-w-0 gap-6'>
        <div className='flex flex-wrap items-center gap-3'>
          <Input
            className='sm:max-w-sm'
            aria-label='搜索技能'
            placeholder='搜索技能名称或简介…'
            value={search}
            maxLength={100}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Select
            value={status}
            onValueChange={(v) => {
              setStatus(v)
              setPage(1)
            }}
          >
            <SelectTrigger className='w-32' aria-label='发布状态'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value='all'>全部状态</SelectItem>
                <SelectItem value='published'>生效中</SelectItem>
                <SelectItem value='unpublished'>未生效</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Select
            value={audience}
            onValueChange={(v) => {
              setAudience(v)
              setPage(1)
            }}
          >
            <SelectTrigger className='w-32' aria-label='使用范围'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value='all'>全部范围</SelectItem>
                {Object.entries(scopeLabels).map(([v, label]) => (
                  <SelectItem key={v} value={v}>
                    {label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <CategoryPicker
            includeAll
            value={selectedCategory}
            onValueChange={(v) => {
              setCategory(v)
              setPage(1)
            }}
            className='w-40'
            aria-label='技能类别'
          />
          {(search ||
            audience !== 'all' ||
            status !== 'all' ||
            category !== 'all') && (
            <Button
              variant='ghost'
              onClick={() => {
                setSearch('')
                setAudience('all')
                setStatus('all')
                setCategory('all')
                setPage(1)
              }}
            >
              清空筛选
            </Button>
          )}
          <TabsList aria-label='技能视图' className='ms-auto'>
            <TabsTrigger value='list'>
              <List aria-hidden='true' />
              列表
            </TabsTrigger>
            <TabsTrigger value='cards'>
              <LayoutGrid aria-hidden='true' />
              卡片
            </TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value={view}>
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : (
            <ServerTable
              items={query.data.items}
              columns={columns}
              total={query.data.total}
              page={currentPage}
              onPage={setPage}
              empty={empty}
              onRowClick={(skill) =>
                void navigate({
                  to: '/skills/$skillId',
                  params: { skillId: skill.id },
                })
              }
              renderItems={
                view === 'cards'
                  ? (items) => <SkillCards items={items} empty={empty} />
                  : undefined
              }
            />
          )}
        </TabsContent>
      </Tabs>
      {categoriesOpen && (
        <CategoriesDialog close={() => setCategoriesOpen(false)} />
      )}
    </PageShell>
  )
}
