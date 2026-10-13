import { useDeferredValue, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Archive, Ellipsis, Plus, RotateCcw, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ServerTable } from '@/components/data-table/server-table'
import { FilterSelect } from '@/components/filter-select'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { PointConversionButton } from '@/features/model-catalog/point-conversion'
import { MemberMatches } from './member-matches'
import { PolicyEditor } from './policy-editor'
import { ruleLabel, weekdays, type Policy } from './policy-form'
import { Settlements } from './settlements'

export function QuotaPoliciesPage() {
  const { organization, csrf } = useOrganization()
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const q = useDeferredValue(search)
  const [state, setState] = useState('current')
  const [page, setPage] = useState(1)
  const [editor, setEditor] = useState<Policy | 'default' | 'new' | null>(null)
  const [archive, setArchive] = useState<Policy | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const add = useRef<HTMLButtonElement>(null)
  const trigger = useRef<HTMLElement | null>(null)
  const prefix = ['organization', organization.tenant_id, 'quota']
  const params = new URLSearchParams({
    q,
    state,
    page: String(page),
  }).toString()
  const query = useQuery({
    queryKey: [...prefix, 'policies', params],
    queryFn: ({ signal }) =>
      api<Schema['QuotaPolicyPage']>(
        '/quota/policies?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  function remember() {
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
  }
  function restore() {
    if (trigger.current?.isConnected) trigger.current.focus()
    else add.current?.focus()
  }
  function refresh() {
    void client.invalidateQueries({ queryKey: prefix })
    setPage(1)
  }
  async function toggleArchive() {
    if (!archive) return
    setBusy(true)
    setError(null)
    try {
      await api(
        '/quota/policies/' + archive.id + '/archive',
        'PUT',
        { version: archive.version, archived: !archive.archived },
        csrf
      )
      refresh()
      setArchive(null)
      toast.success(archive.archived ? '策略已恢复' : '策略已归档')
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  const columns: ColumnDef<Policy>[] = [
    {
      id: 'name',
      header: '策略',
      meta: { className: 'min-w-48 py-4' },
      cell: ({ row: { original: p } }) => (
        <div className='flex min-w-32 flex-col items-start gap-1'>
          <Button
            variant='link'
            className='h-auto max-w-56 justify-start p-0'
            disabled={p.archived}
            onClick={() => {
              remember()
              setEditor(p)
            }}
          >
            <span className='truncate'>{p.name}</span>
          </Button>
          {p.priority === 0 && <Badge variant='secondary'>默认兜底</Badge>}
          {p.archived && <Badge variant='outline'>已归档</Badge>}
        </div>
      ),
    },
    { accessorKey: 'priority', header: '优先级', meta: { className: 'w-24' } },
    {
      id: 'members',
      header: '适用成员',
      meta: { className: 'w-32' },
      cell: ({ row: { original: p } }) => (
        <span className='whitespace-nowrap'>
          {p.priority === 0
            ? '全部成员'
            : `指定 ${p.member_ids?.length ?? 0} 人`}
        </span>
      ),
    },
    {
      id: 'rules',
      header: '周期额度',
      cell: ({ row: { original: p } }) => (
        <div className='flex min-w-48 flex-col gap-2 py-2'>
          {p.rules.map((r, i) => (
            <span key={i} className='tabular-nums'>
              {ruleLabel(r)}
            </span>
          ))}
        </div>
      ),
    },
    {
      id: 'reset',
      header: '重置规则',
      cell: ({ row: { original: p } }) => (
        <div className='flex min-w-48 flex-col gap-2 text-sm text-muted-foreground'>
          {p.rules.map((r, i) => (
            <span key={i}>
              {r.kind === 'fixed_hours'
                ? '首次使用起算，到期恢复'
                : `${weekdays[r.week_start]} 00:00 · ${r.timezone}`}
            </span>
          ))}
        </div>
      ),
    },
    {
      id: 'actions',
      header: () => <span className='sr-only'>操作</span>,
      cell: ({ row: { original: p } }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant='ghost'
              size='icon'
              aria-label={`${p.name}的更多操作`}
            >
              <Ellipsis />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end'>
            <DropdownMenuGroup>
              {!p.archived && (
                <DropdownMenuItem
                  onSelect={() => {
                    remember()
                    setEditor(p)
                  }}
                >
                  编辑
                </DropdownMenuItem>
              )}
              {p.priority > 0 && (
                <DropdownMenuItem
                  onSelect={() => {
                    remember()
                    setError(null)
                    setArchive(p)
                  }}
                >
                  {p.archived ? <RotateCcw /> : <Archive />}
                  {p.archived ? '恢复' : '归档'}
                </DropdownMenuItem>
              )}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ]
  return (
    <PageShell
      title='额度策略'
      action={
        <div className='flex flex-wrap gap-2'>
          <PointConversionButton />
          <Button
            ref={add}
            disabled={!query.data}
            onClick={() => {
              remember()
              setEditor(query.data?.has_default ? 'new' : 'default')
            }}
          >
            <Plus />
            {query.data?.has_default ? '新建策略' : '设置默认策略'}
          </Button>
        </div>
      }
    >
      <Tabs defaultValue='policies' className='min-w-0 gap-4'>
        <TabsList>
          <TabsTrigger value='policies'>策略</TabsTrigger>
          <TabsTrigger value='members'>成员匹配</TabsTrigger>
          <TabsTrigger value='settlements'>结算记录</TabsTrigger>
        </TabsList>
        <TabsContent value='policies' className='flex min-w-0 flex-col gap-4'>
          <div className='flex flex-wrap items-center gap-2'>
            <Input
              className='max-w-sm'
              aria-label='搜索策略'
              placeholder='搜索策略…'
              value={search}
              maxLength={100}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
            />
            <FilterSelect
              allowAll={false}
              label='状态'
              value={state}
              options={[
                { value: 'current', label: '当前策略' },
                { value: 'archived', label: '已归档' },
              ]}
              onChange={(v) => {
                setState(v || 'current')
                setPage(1)
              }}
            />
            <Button
              className='ml-auto'
              variant='outline'
              disabled={query.isFetching}
              onClick={refresh}
            >
              <RefreshCw />
              刷新
            </Button>
          </div>
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
              page={page}
              onPage={setPage}
              empty={
                !query.data.has_default ? '尚未设置默认策略' : '没有匹配的策略'
              }
            />
          )}
        </TabsContent>
        <TabsContent value='settlements'>
          <div className='mb-4 flex justify-end'>
            <Button asChild variant='outline'>
              <a href='/llm-calls'>查看调用记录</a>
            </Button>
          </div>
          <Settlements />
        </TabsContent>
        <TabsContent value='members'>
          <MemberMatches />
        </TabsContent>
      </Tabs>
      {editor && (
        <PolicyEditor
          policy={typeof editor === 'object' ? editor : undefined}
          isDefault={
            editor === 'default' ||
            (typeof editor === 'object' && editor.priority === 0)
          }
          close={() => setEditor(null)}
          saved={() => {
            setEditor(null)
            refresh()
            toast.success('策略已保存')
          }}
          restoreFocus={restore}
        />
      )}
      <ConfirmDialog
        open={!!archive}
        onOpenChange={(open) => {
          if (!open && !busy) setArchive(null)
        }}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restore()
        }}
        title={archive?.archived ? '恢复策略' : '归档策略'}
        desc={
          archive?.archived
            ? `恢复「${archive.name}」后，将重新参与成员策略匹配。`
            : `归档「${archive?.name}」后，成员将采用下一条适用策略。`
        }
        cancelBtnText='取消'
        confirmText={archive?.archived ? '恢复' : '归档'}
        isLoading={busy}
        handleConfirm={() => void toggleArchive()}
      >
        {!!error && <RequestError error={error} />}
      </ConfirmDialog>
    </PageShell>
  )
}
