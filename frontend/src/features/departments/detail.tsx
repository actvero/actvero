import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  Archive,
  Layers,
  MoreHorizontal,
  Pencil,
  UserRoundPlus,
  Users,
} from 'lucide-react'
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
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { LoadingState, RequestError } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { roleName } from '@/features/members/labels'
import { memberSearch } from '@/features/members/search'
import type { Department } from './data'
import { ListPager } from './list-pager'
import { MemberDepartmentEditor } from './member-editor'

export function DepartmentDetail({
  department,
  parentPath,
  childrenCount,
  edit,
  archive,
}: {
  department: Department
  parentPath?: string
  childrenCount: number
  edit: () => void
  archive: () => void
}) {
  const { organization, user } = useOrganization()
  const [page, setPage] = useState(1)
  const [member, setMember] = useState<Schema['MemberView']>()
  const path = `/enterprises/${organization.tenant_id}/departments/${department.id}/members?page=${page}`
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, path],
    queryFn: ({ signal }) =>
      api<Schema['DepartmentMemberPage']>(
        path,
        'GET',
        undefined,
        undefined,
        signal
      ),
    enabled: !department.archived,
  })

  return (
    <section className='flex min-w-0 flex-col gap-5'>
      <div className='flex flex-col gap-3'>
        {parentPath && (
          <div className='text-sm break-words text-muted-foreground'>
            {parentPath} / {department.name}
          </div>
        )}
        <div className='flex flex-wrap items-center justify-between gap-3'>
          <div className='flex min-w-0 flex-wrap items-center gap-2'>
            <h2 className='text-2xl font-semibold tracking-tight break-words'>
              {department.name}
            </h2>
            {department.archived && <Badge variant='outline'>已归档</Badge>}
          </div>
          <div className='flex gap-2'>
            <Button variant='outline' size='sm' onClick={edit}>
              <Pencil data-icon='inline-start' />{' '}
              {department.archived ? '恢复部门' : '编辑部门'}
            </Button>
            {!department.archived && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant='outline'
                    size='icon'
                    className='size-8'
                    aria-label='更多部门操作'
                  >
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align='end'>
                  <DropdownMenuGroup>
                    <DropdownMenuItem variant='destructive' onSelect={archive}>
                      <Archive /> 归档部门
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
        {!department.archived && (
          <div className='flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground'>
            <span className='inline-flex items-center gap-2'>
              <Users className='size-4' aria-hidden='true' />
              直属成员
              {query.data && (
                <span className='font-medium text-foreground'>
                  {query.data.total} 人
                </span>
              )}
            </span>
            <span className='inline-flex items-center gap-2'>
              <Layers className='size-4' aria-hidden='true' /> 下级部门
              <span className='font-medium text-foreground'>
                {childrenCount} 个
              </span>
            </span>
          </div>
        )}
      </div>
      {!department.archived && (
        <>
          <Separator />
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h3 className='text-lg font-semibold'>直属成员</h3>
            <Button asChild variant='ghost' size='sm'>
              <Link to='/users' search={memberSearch.parse({})}>
                <UserRoundPlus data-icon='inline-start' /> 管理成员
              </Link>
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
            <>
              {query.data.items.length > 0 ? (
                <div className='overflow-hidden rounded-lg border'>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>成员</TableHead>
                        <TableHead>角色</TableHead>
                        <TableHead>归属</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {query.data.items.map(({ member: row, is_primary }) => (
                        <TableRow key={row.id}>
                          <TableCell>
                            <Button
                              variant='ghost'
                              size='sm'
                              className='h-auto max-w-full justify-start text-start whitespace-normal'
                              onClick={() => setMember(row)}
                            >
                              <UserAvatar user={row} />
                              <span className='break-words'>{row.name}</span>
                            </Button>
                            {row.status === 'paused' && (
                              <Badge variant='outline'>已暂停</Badge>
                            )}
                          </TableCell>
                          <TableCell>{roleName(row.role)}</TableCell>
                          <TableCell>
                            {is_primary ? '主部门' : '兼属部门'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <Empty className='py-8'>
                  <EmptyHeader>
                    <EmptyTitle>暂无直属成员</EmptyTitle>
                  </EmptyHeader>
                </Empty>
              )}
              <ListPager
                page={page}
                total={query.data.total}
                onChange={setPage}
              />
            </>
          )}
        </>
      )}
      {member && (
        <MemberDepartmentEditor
          member={member}
          close={() => setMember(undefined)}
        />
      )}
    </section>
  )
}
