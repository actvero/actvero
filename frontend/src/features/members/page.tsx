import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { MailPlus, UserPlus } from 'lucide-react'
import { api, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ServerTable } from '@/components/data-table/server-table'
import { FilterSelect } from '@/components/filter-select'
import { PageShell } from '@/components/layout/page-shell'
import { RequestError, LoadingState } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { AddMemberDialog } from './add-member-dialog'
import { InviteDialog, InvitationAction } from './invitation-dialog'
import { roleName, roleOptions, states } from './labels'
import { MemberDetails } from './member-details'

const route = getRouteApi('/_authenticated/users')
type Member = Schema['MemberView']
type Invitation = Schema['InvitationView']
export function MembersPage() {
  const { organization, user, session } = useOrganization()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const [invite, setInvite] = useState(false)
  const [add, setAdd] = useState(false)
  const addButton = useRef<HTMLButtonElement>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const update = (change: Partial<typeof search>) =>
    void navigate({
      search: (previous) => ({ ...previous, page: 1, ...change }),
      replace: true,
    })
  const path = '/enterprises/' + organization.tenant_id
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, path, search],
    queryFn: ({ signal }) =>
      api<Schema['MemberPage'] | Schema['InvitationPage']>(
        path +
          '/' +
          search.tab +
          '?' +
          new URLSearchParams({
            page: String(search.page),
            q: search.q,
            role: search.role,
            status: search.status,
          }),
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const lastPage = query.data
    ? Math.max(1, Math.ceil(query.data.total / 20))
    : undefined
  useEffect(() => {
    if (lastPage !== undefined && search.page > lastPage)
      void navigate({
        search: (previous) => ({ ...previous, page: lastPage }),
        replace: true,
      })
  }, [lastPage, navigate, search.page])
  const members: ColumnDef<Member>[] = [
    {
      accessorKey: 'name',
      header: '成员',
      cell: ({ row }) => (
        <div className='flex items-center gap-3'>
          <UserAvatar user={row.original} />
          <Button
            variant='link'
            size='sm'
            onClick={() => setSelected(row.original.id)}
            className='max-w-60 justify-start px-0'
          >
            <span className='truncate'>
              {row.original.name}
              {row.original.is_self ? '（你）' : ''}
            </span>
          </Button>
        </div>
      ),
    },
    {
      accessorKey: 'email',
      header: '邮箱',
      cell: ({ row }) => (
        <span
          className='block max-w-60 truncate'
          title={row.original.email ?? undefined}
        >
          {row.original.email ?? '未设置邮箱'}
        </span>
      ),
    },
    {
      accessorKey: 'role',
      header: '角色',
      cell: ({ row }) => roleName(row.original.role),
    },
    {
      accessorKey: 'status',
      header: '状态',
      cell: ({ row }) => (
        <Badge
          variant={row.original.status === 'active' ? 'secondary' : 'outline'}
        >
          {states[row.original.status]}
        </Badge>
      ),
    },
    {
      accessorKey: 'joined_at',
      header: '加入时间',
      meta: { className: 'hidden lg:table-cell' },
      cell: ({ row }) => dateTime(row.original.joined_at),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <Button
          variant='ghost'
          size='sm'
          onClick={() => setSelected(row.original.id)}
          aria-label={'编辑成员 ' + row.original.name}
        >
          编辑
        </Button>
      ),
    },
  ]
  // TanStack renders cell callbacks as components. Preserve their identities
  // across session/list refreshes so open invitation actions remain mounted.
  const invitations = useMemo<ColumnDef<Invitation>[]>(
    () => [
      {
        accessorKey: 'email',
        header: '受邀成员',
        cell: ({ row }) => (
          <div>
            <p className='max-w-60 truncate'>{row.original.email}</p>
            <p className='text-sm text-muted-foreground'>
              {row.original.name || '—'}
            </p>
          </div>
        ),
      },
      {
        accessorKey: 'status',
        header: '邀请状态',
        cell: ({ row }) => (
          <Badge variant='outline'>{states[row.original.status]}</Badge>
        ),
      },
      {
        accessorKey: 'mail_status',
        header: '邮件状态',
        cell: ({ row }) =>
          row.original.mail_status === 'pending'
            ? '待发送'
            : states[row.original.mail_status],
      },
      {
        accessorKey: 'expires_at',
        header: '到期时间',
        meta: { className: 'hidden lg:table-cell' },
        cell: ({ row }) => dateTime(row.original.expires_at),
      },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) => (
          <InvitationAction invitation={row.original} path={path} />
        ),
      },
    ],
    [path]
  )
  return (
    <PageShell
      title='成员管理'
      action={
        <div className='flex flex-wrap gap-2'>
          <Button
            variant='outline'
            disabled={!session.invitations_enabled}
            onClick={() => setInvite(true)}
          >
            <MailPlus data-icon='inline-start' />
            邀请成员
          </Button>
          <Button ref={addButton} onClick={() => setAdd(true)}>
            <UserPlus data-icon='inline-start' />
            添加成员
          </Button>
        </div>
      }
    >
      {!session.invitations_enabled && (
        <Alert>
          <AlertDescription>
            邀请功能尚未配置完成。请先配置邮件服务和邀请有效期。
          </AlertDescription>
        </Alert>
      )}
      <Tabs
        value={search.tab}
        onValueChange={(value) =>
          update({
            tab: value as typeof search.tab,
            status: '',
            q: '',
            role: '',
          })
        }
      >
        <TabsList>
          <TabsTrigger value='members'>成员</TabsTrigger>
          <TabsTrigger value='invitations'>邀请记录</TabsTrigger>
        </TabsList>
      </Tabs>
      <div className='flex flex-wrap items-center gap-3'>
        <Input
          aria-label='搜索姓名或邮箱'
          placeholder='搜索姓名或邮箱…'
          value={search.q}
          onChange={(event) => update({ q: event.target.value })}
          className='w-full sm:w-64'
        />
        <FilterSelect
          label='状态'
          value={search.status}
          onChange={(status) => update({ status })}
          options={(search.tab === 'members'
            ? ['active', 'paused', 'removed']
            : ['pending', 'accepted', 'expired', 'revoked']
          ).map((value) => ({ value, label: states[value] }))}
        />
        {search.tab === 'members' && (
          <FilterSelect
            label='角色'
            value={search.role}
            onChange={(role) => update({ role: role as typeof search.role })}
            options={roleOptions}
          />
        )}
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : search.tab === 'members' ? (
        <ServerTable
          items={query.data.items as Member[]}
          columns={members}
          total={query.data.total}
          page={search.page}
          onPage={(page) => update({ page })}
          empty={
            search.q || search.status || search.role
              ? '没有符合条件的成员'
              : '暂无成员'
          }
        />
      ) : (
        <ServerTable
          items={query.data.items as Invitation[]}
          columns={invitations}
          getRowId={(invitation) => invitation.id}
          total={query.data.total}
          page={search.page}
          onPage={(page) => update({ page })}
          empty='暂无符合条件的邀请记录'
        />
      )}
      {add && (
        <AddMemberDialog
          returnFocus={() => addButton.current?.focus()}
          path={path}
          onClose={() => setAdd(false)}
          onCreated={() =>
            update({ tab: 'members', q: '', role: '', status: '' })
          }
        />
      )}
      <InviteDialog open={invite} onOpenChange={setInvite} path={path} />
      {selected && (
        <MemberDetails
          key={selected}
          id={selected}
          path={path}
          onClose={() => setSelected(null)}
        />
      )}
    </PageShell>
  )
}
