import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { LoadingState, RequestError } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { roleName } from '@/features/members/labels'
import { departmentTree, useDepartments, type Department } from './data'
import { DepartmentTree } from './tree'

type Assignment = Schema['MemberDepartments']

function AssignmentForm({
  current,
  departments,
  path,
  close,
  pending,
}: {
  current: Assignment
  departments: Department[]
  path: string
  close: () => void
  pending: (value: boolean) => void
}) {
  const { organization, csrf } = useOrganization()
  const client = useQueryClient()
  const [ids, setIds] = useState(current.department_ids ?? [])
  const [primary, setPrimary] = useState(current.primary_department_id ?? '')
  const rows = new Map(
    departmentTree(departments).map((row) => [row.department.id, row])
  )
  const dirty =
    primary !== (current.primary_department_id ?? '') ||
    ids.length !== (current.department_ids?.length ?? 0) ||
    ids.some((id) => !current.department_ids?.includes(id))
  const valid = ids.every((id) => {
    const row = rows.get(id)
    return row && !row.department.archived
  })
  const save = useMutation({
    mutationFn: () =>
      api<Assignment>(
        path,
        'PUT',
        {
          department_ids: ids,
          primary_department_id: primary || null,
          version: current.version,
        },
        csrf
      ),
    onMutate: () => pending(true),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: ['organization', organization.tenant_id],
      })
      toast.success('成员部门已保存')
      close()
    },
    onSettled: () => pending(false),
  })

  function change(next: string[]) {
    setIds(next)
    if (!next.includes(primary)) {
      setPrimary(
        next.find((id) => rows.get(id)?.department.archived === false) ?? ''
      )
    }
  }

  return (
    <form
      className='flex min-w-0 flex-col'
      onSubmit={(event) => {
        event.preventDefault()
        if (dirty && valid && !save.isPending) save.mutate()
      }}
    >
      <div className='grid min-w-0 divide-y md:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] md:divide-x md:divide-y-0'>
        <section
          className='flex min-w-0 flex-col gap-3 p-4 sm:p-6'
          aria-label='选择部门'
        >
          <h3 className='font-semibold'>选择部门</h3>
          <DepartmentTree
            departments={departments}
            selection={{ selectedIds: ids, change, disabled: save.isPending }}
          />
        </section>
        <section
          className='flex min-w-0 flex-col gap-3 p-4 sm:p-6'
          aria-label='已选部门'
        >
          <div className='flex items-center gap-2'>
            <h3 className='font-semibold'>已选部门</h3>
            <Badge variant='secondary' aria-live='polite'>
              {ids.length}
            </Badge>
          </div>
          <p className='text-sm text-muted-foreground'>
            {ids.length
              ? '从已选部门中指定一个主部门'
              : '在部门树中勾选成员所属的部门'}
          </p>
          {ids.length > 0 && (
            <ScrollArea
              role='region'
              aria-label='已选部门列表'
              viewportClassName='max-h-[min(38dvh,24rem)]'
            >
              <ul className='flex flex-col gap-2'>
                {ids.map((id) => {
                  const row = rows.get(id)
                  const label = row?.department.name ?? '部门不可用'
                  const parent = row?.department.parent_id
                  const unavailable = !row || row.department.archived
                  return (
                    <li
                      key={id}
                      className='flex flex-wrap items-center gap-2 rounded-lg bg-muted/65 px-3 py-2.5'
                    >
                      <div className='min-w-28 flex-1'>
                        <div className='text-sm font-medium break-words'>
                          {label}
                        </div>
                        {parent && (
                          <div className='text-xs break-words text-muted-foreground'>
                            {rows.get(parent)?.path}
                          </div>
                        )}
                        {unavailable && (
                          <div className='text-xs text-muted-foreground'>
                            请移除此部门
                          </div>
                        )}
                      </div>
                      {id === primary ? (
                        <Badge variant='secondary'>主部门</Badge>
                      ) : (
                        !unavailable && (
                          <Button
                            type='button'
                            size='sm'
                            variant='outline'
                            disabled={save.isPending}
                            onClick={() => setPrimary(id)}
                          >
                            设为主部门
                          </Button>
                        )
                      )}
                      <Button
                        type='button'
                        variant='ghost'
                        size='icon'
                        className='size-8'
                        aria-label={`移除 ${label}`}
                        disabled={save.isPending}
                        onClick={() =>
                          change(ids.filter((selected) => selected !== id))
                        }
                      >
                        <X />
                      </Button>
                    </li>
                  )
                })}
              </ul>
            </ScrollArea>
          )}
        </section>
      </div>
      {save.isError && (
        <div className='px-6 pb-4'>
          <RequestError error={save.error} />
        </div>
      )}
      <Separator />
      <DialogFooter className='px-4 py-4 sm:px-6'>
        <Button
          type='button'
          variant='outline'
          onClick={close}
          disabled={save.isPending}
        >
          取消
        </Button>
        <Button type='submit' disabled={!dirty || !valid || save.isPending}>
          {save.isPending ? '保存中…' : '保存'}
        </Button>
      </DialogFooter>
    </form>
  )
}

export function MemberDepartmentEditor({
  member,
  close,
}: {
  member: Schema['MemberView']
  close: () => void
}) {
  const { organization, user } = useOrganization()
  const path = `/enterprises/${organization.tenant_id}/members/${member.id}/departments`
  const [pending, setPending] = useState(false)
  const departments = useDepartments()
  const assignment = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, path],
    queryFn: ({ signal }) =>
      api<Assignment>(path, 'GET', undefined, undefined, signal),
  })
  return (
    <Dialog open onOpenChange={(open) => !open && !pending && close()}>
      <DialogContent className='max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-4xl'>
        <DialogHeader className='gap-3 px-4 py-5 sm:px-6'>
          <DialogTitle className='text-xl'>设置成员部门</DialogTitle>
          <DialogDescription className='sr-only'>
            管理成员的所属部门与主部门。
          </DialogDescription>
          <div className='flex items-center gap-2.5 text-start'>
            <UserAvatar user={member} size='md' />
            <span className='font-medium break-words'>{member.name}</span>
            <Badge variant='secondary'>{roleName(member.role)}</Badge>
          </div>
        </DialogHeader>
        <Separator />
        {departments.isError || assignment.isError ? (
          <div className='p-6'>
            <RequestError
              error={departments.error ?? assignment.error}
              retry={() =>
                void (departments.isError
                  ? departments.refetch()
                  : assignment.refetch())
              }
            />
          </div>
        ) : departments.isPending || assignment.isPending ? (
          <div className='p-6'>
            <LoadingState />
          </div>
        ) : (
          <AssignmentForm
            key={assignment.data.version}
            current={assignment.data}
            departments={departments.data}
            path={path}
            close={close}
            pending={setPending}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
