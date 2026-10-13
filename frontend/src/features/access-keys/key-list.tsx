import { useDeferredValue, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Ellipsis, Eye, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ServerTable } from '@/components/data-table/server-table'
import { LoadingState, RequestError } from '@/components/request-state'
import { KeyEditor } from './key-editor'
import { KeyPolicyEditor } from './key-policy'
import { KeySecretDialog } from './key-secret'

type Key = Schema['KeyView']
type Action = Schema['KeyAction']['action']
const statuses = {
  active: '有效',
  disabled: '已停用',
  revoked: '已撤销',
  expired: '已过期',
  blocked: '受限',
}
const actions = {
  disable: '停用',
  enable: '启用',
  revoke: '撤销',
  delete: '删除',
}
export function KeyList({
  identity,
  csrf,
  admin = false,
}: {
  identity: string
  csrf: string
  admin?: boolean
}) {
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [editor, setEditor] = useState(false)
  const [reveal, setReveal] = useState<Key | null>(null)
  const [policyOpen, setPolicyOpen] = useState(false)
  const [action, setAction] = useState<{ item: Key; action: Action } | null>(
    null
  )
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const q = useDeferredValue(search)
  const path = admin ? '/access-keys' : '/account/access-keys'
  const prefix = ['access-keys', identity]
  const trigger = useRef<HTMLElement | null>(null)
  const refreshButton = useRef<HTMLButtonElement>(null)
  const query = useQuery({
    queryKey: [...prefix, path, page, q],
    queryFn: ({ signal }) =>
      api<Schema['KeyPage']>(
        path + '?' + new URLSearchParams({ page: String(page), q }),
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const rules = useQuery({
    queryKey: [...prefix, path, 'policy'],
    queryFn: ({ signal }) =>
      api<Schema['KeyPolicyView']>(
        path + '/policy',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  function refresh() {
    void client.invalidateQueries({ queryKey: prefix })
  }
  function remember() {
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
  }
  function restore() {
    const target = trigger.current?.id
      ? document.getElementById(trigger.current.id)
      : trigger.current
    if (target?.isConnected && !target.hasAttribute('disabled')) target.focus()
    else refreshButton.current?.focus()
  }
  function choose(item: Key, action: Action) {
    setError(null)
    setAction({ item, action })
  }
  async function change() {
    if (!action || busy) return
    setBusy(true)
    setError(null)
    try {
      await api(
        path + '/' + action.item.id,
        'PATCH',
        { version: action.item.version, action: action.action },
        csrf
      )
      refresh()
      setAction(null)
      toast.success('密钥已' + actions[action.action])
    } catch (e) {
      setError(e)
      refresh()
    } finally {
      setBusy(false)
    }
  }
  const columns: ColumnDef<Key>[] = [
    {
      accessorKey: 'name',
      header: '名称',
      cell: ({ row }) => (
        <span className='block max-w-44 truncate'>{row.original.name}</span>
      ),
    },
    {
      accessorKey: 'hint',
      header: '密钥',
      cell: ({ row }) => (
        <div className='flex items-center gap-2'>
          <span className='font-mono'>{row.original.hint}</span>
          {row.original.can_reveal && (
            <Button
              id={`reveal-key-${admin ? 'admin' : 'personal'}-${row.original.id}`}
              variant='ghost'
              size='icon'
              aria-label={'查看密钥 ' + row.original.name}
              onClick={() => {
                remember()
                setReveal(row.original)
              }}
            >
              <Eye />
            </Button>
          )}
        </div>
      ),
    },
    ...(admin ? [{ accessorKey: 'member_name', header: '成员' }] : []),
    {
      accessorKey: 'status',
      header: '状态',
      cell: ({ row }) => (
        <Badge
          variant={row.original.status === 'active' ? 'secondary' : 'outline'}
        >
          {statuses[row.original.status]}
        </Badge>
      ),
    },
    {
      id: 'actions',
      header: '操作',
      cell: ({ row: { original: item } }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant='ghost'
              size='icon'
              aria-label={'管理 ' + item.name}
              onClick={remember}
            >
              <Ellipsis />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end'>
            <DropdownMenuGroup>
              {item.status === 'active' && (
                <DropdownMenuItem onSelect={() => choose(item, 'disable')}>
                  停用
                </DropdownMenuItem>
              )}
              {item.status === 'disabled' &&
                (!item.managed_disabled || admin) && (
                  <DropdownMenuItem onSelect={() => choose(item, 'enable')}>
                    启用
                  </DropdownMenuItem>
                )}
              {item.status !== 'revoked' && (
                <DropdownMenuItem
                  variant='destructive'
                  onSelect={() => choose(item, 'revoke')}
                >
                  撤销
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                variant='destructive'
                onSelect={() => choose(item, 'delete')}
              >
                删除
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ]
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <Input
          className='w-full sm:w-64'
          aria-label='搜索密钥'
          placeholder={admin ? '搜索名称或成员' : '搜索名称'}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        <div className='flex flex-wrap gap-2'>
          <Button
            ref={refreshButton}
            variant='outline'
            disabled={query.isFetching}
            onClick={refresh}
          >
            刷新
          </Button>
          {admin ? (
            <Button
              variant='outline'
              disabled={!rules.data}
              onClick={() => {
                remember()
                setPolicyOpen(true)
              }}
            >
              密钥规则
            </Button>
          ) : (
            <Button
              disabled={!rules.data?.enabled}
              onClick={() => {
                remember()
                setEditor(true)
              }}
            >
              <Plus />
              创建密钥
            </Button>
          )}
        </div>
      </div>
      {rules.isError && (
        <RequestError error={rules.error} retry={() => void rules.refetch()} />
      )}
      {rules.data?.enabled === false && (
        <Alert>
          <AlertDescription>组织已关闭个人访问密钥。</AlertDescription>
        </Alert>
      )}
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
          empty='尚无访问密钥'
        />
      )}
      {editor && rules.data && (
        <KeyEditor
          csrf={csrf}
          rules={rules.data}
          onClose={() => setEditor(false)}
          onCreated={refresh}
          restore={restore}
        />
      )}
      {policyOpen && rules.data && (
        <KeyPolicyEditor
          rules={rules.data}
          csrf={csrf}
          onClose={() => setPolicyOpen(false)}
          onSaved={refresh}
          restore={restore}
        />
      )}
      {reveal && (
        <KeySecretDialog
          key={`${reveal.id}:${reveal.version}`}
          item={reveal}
          path={path}
          csrf={csrf}
          onClose={() => setReveal(null)}
          restore={restore}
        />
      )}
      <ConfirmDialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setAction(null)
        }}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restore()
        }}
        title={action ? actions[action.action] + '访问密钥？' : ''}
        desc={
          action?.action === 'delete'
            ? '删除后密钥立即失效并从列表移除，无法恢复。已产生的用量记录保留。'
            : action?.action === 'revoke'
              ? '撤销后无法恢复。使用此密钥的客户端将无法继续访问。'
              : action?.action === 'disable'
                ? '使用此密钥的客户端将暂停访问。'
                : '恢复后仍受当前成员权限、有效期和组织规则约束。'
        }
        cancelBtnText='取消'
        confirmText={
          busy ? '正在处理…' : action ? actions[action.action] : '确认'
        }
        isLoading={busy}
        handleConfirm={() => void change()}
      >
        {error != null && <RequestError error={error} />}
      </ConfirmDialog>
    </div>
  )
}
