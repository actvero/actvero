import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { departmentTree, useDepartments, type DepartmentGrant } from './data'

export function DepartmentScopePreview({
  members,
  grants,
  disabled,
}: {
  members: string[]
  grants: DepartmentGrant[]
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const { organization, user, csrf } = useOrganization()
  const path = `/enterprises/${organization.tenant_id}/departments/scope-preview`
  const departments = useDepartments(open && grants.length > 0)
  const body: Schema['DepartmentScopePreview'] = {
    member_ids: members,
    department_grants: grants,
    page,
  }
  // The token authenticates this read and is excluded from cache identity.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const preview = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, path, body],
    queryFn: ({ signal }) =>
      api<Schema['DepartmentScopePage']>(path, 'POST', body, csrf, signal),
    enabled: open,
  })
  const names = new Map(
    departmentTree(departments.data ?? []).map(
      ({ department, path: label }) => [department.id, label]
    )
  )
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value)
        if (value) setPage(1)
      }}
    >
      <DialogTrigger asChild>
        <Button
          type='button'
          variant='outline'
          disabled={disabled || (!members.length && !grants.length)}
        >
          查看授权成员
        </Button>
      </DialogTrigger>
      <DialogContent className='max-h-[90dvh] overflow-y-auto sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>授权成员预览</DialogTitle>
          <DialogDescription>
            按当前选中的部门和成员计算，显示每个人的授权来源。
          </DialogDescription>
        </DialogHeader>
        {preview.isError ? (
          <RequestError
            error={preview.error}
            retry={() => void preview.refetch()}
          />
        ) : preview.isPending ||
          (grants.length > 0 && departments.isPending) ? (
          <LoadingState />
        ) : (
          <>
            {departments.isError && (
              <RequestError
                error={departments.error}
                retry={() => void departments.refetch()}
              />
            )}
            {preview.data.items.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>成员</TableHead>
                    <TableHead>授权来源</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.data.items.map((member) => (
                    <TableRow key={member.id}>
                      <TableCell>{member.name}</TableCell>
                      <TableCell className='whitespace-normal'>
                        {[
                          ...(member.direct ? ['单独授权'] : []),
                          ...member.department_ids.map(
                            (id) => names.get(id) ?? '部门授权'
                          ),
                        ].join('、')}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className='text-sm text-muted-foreground'>
                此页没有获授权的成员。
              </p>
            )}
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <span className='text-sm text-muted-foreground'>
                共 {preview.data.total} 人
              </span>
              <div className='flex gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  上一页
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={page * 20 >= preview.data.total}
                  onClick={() => setPage(page + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
