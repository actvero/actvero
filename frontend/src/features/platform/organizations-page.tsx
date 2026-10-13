import { useMemo, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Building2, Search } from 'lucide-react'
import { api, dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import { OrganizationForm } from './organization-form'

export function OrganizationsPage() {
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<
    Schema['PlatformOrganization'] | null | undefined
  >(undefined)
  const { data: session } = useSession()
  const enter = useMutation({
    mutationFn: (id: string) =>
      api('/auth/workspace', 'POST', { tenant_id: id }, session?.csrf),
    onSuccess: () => window.location.assign('/'),
  })
  const organizations = useQuery({
    queryKey: ['platform', 'organizations'],
    queryFn: () =>
      api<Schema['PlatformOrganizationPage']>('/platform/organizations'),
  })
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    const items = organizations.data?.items ?? []
    return query
      ? items.filter((item) =>
          [item.name, item.administrator_email ?? '']
            .join(' ')
            .toLowerCase()
            .includes(query)
        )
      : items
  }, [organizations.data?.items, search])
  return (
    <PageShell
      title='组织管理'
      action={
        <div className='flex gap-2'>
          <Button onClick={() => setEditing(null)}>创建组织</Button>
          <Button asChild variant='outline'>
            <Link to='/platform/invitations'>开通邀请</Link>
          </Button>
        </div>
      }
    >
      {editing !== undefined && (
        <OrganizationForm
          organization={editing}
          onClose={() => setEditing(undefined)}
        />
      )}
      {enter.isError && <RequestError error={enter.error} />}
      <div className='flex flex-col gap-4'>
        <div className='relative w-full sm:w-64'>
          <Search
            className='absolute top-2.5 left-3 size-4 text-muted-foreground'
            aria-hidden='true'
          />
          <Input
            className='ps-9'
            aria-label='搜索组织'
            placeholder='搜索组织或管理员'
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className='overflow-hidden rounded-md border'>
          {organizations.isPending ? (
            <LoadingState />
          ) : organizations.isError ? (
            <div className='p-6'>
              <RequestError
                error={organizations.error}
                retry={() => void organizations.refetch()}
              />
            </div>
          ) : (
            <div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className='px-6'>组织</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>首位管理员</TableHead>
                    <TableHead>成员</TableHead>
                    <TableHead className='px-6'>创建时间</TableHead>
                    <TableHead className='text-end'>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((organization) => (
                    <TableRow key={organization.id}>
                      <TableCell className='px-6 py-4'>
                        <div className='flex items-center gap-3'>
                          <div className='flex size-9 items-center justify-center rounded-lg border bg-muted/40'>
                            <Building2 aria-hidden='true' />
                          </div>
                          <div>
                            <p className='font-medium'>{organization.name}</p>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className='py-4'>
                        <Badge
                          variant={
                            organization.active ? 'success' : 'secondary'
                          }
                        >
                          {organization.active ? '正常' : '已暂停'}
                        </Badge>
                      </TableCell>
                      <TableCell className='py-4'>
                        {organization.administrator_email ?? (
                          <span className='text-muted-foreground'>
                            {organization.administrator_status === 'pending'
                              ? '等待接受邀请'
                              : '未设置'}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className='py-4'>
                        {organization.member_count}
                      </TableCell>
                      <TableCell className='px-6 py-4 text-muted-foreground'>
                        {dateTime(organization.created_at)}
                      </TableCell>
                      <TableCell>
                        <div className='flex justify-end gap-2'>
                          <Button
                            size='sm'
                            variant='ghost'
                            onClick={() => setEditing(organization)}
                          >
                            编辑
                          </Button>
                          <Button
                            size='sm'
                            variant='outline'
                            disabled={enter.isPending}
                            onClick={() => enter.mutate(organization.id)}
                          >
                            进入管理
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {!filtered.length && (
                <div className='p-10 text-center text-sm text-muted-foreground'>
                  {search.trim() ? '没有匹配的组织。' : '暂无组织'}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </PageShell>
  )
}
