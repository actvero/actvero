import { useId, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
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
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { departmentTree, useDepartments, type Department } from './data'

function DepartmentEditor({
  current,
  departments,
  close,
}: {
  current: Department | null
  departments: Department[]
  close: () => void
}) {
  const id = useId()
  const { organization, csrf } = useOrganization()
  const client = useQueryClient()
  const [name, setName] = useState(current?.name ?? '')
  const [parent, setParent] = useState(current?.parent_id ?? 'root')
  const [order, setOrder] = useState(current?.sort_order ?? 0)
  const [confirmMove, setConfirmMove] = useState(false)
  const path = `/enterprises/${organization.tenant_id}/departments`
  const save = useMutation({
    mutationFn: () => {
      const fields: Schema['DepartmentInput'] = {
        name: name.trim(),
        parent_id: parent === 'root' ? null : parent,
        sort_order: order,
      }
      return current
        ? api<Department>(
            `${path}/${current.id}`,
            'PUT',
            {
              ...fields,
              version: current.version,
              archived: false,
            },
            csrf
          )
        : api<Department>(path, 'POST', fields, csrf)
    },
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: ['organization', organization.tenant_id],
      })
      toast.success(current?.archived ? '部门已恢复' : '部门已保存')
      close()
    },
  })
  const excluded = new Set(current ? [current.id] : [])
  const options = departmentTree(departments).filter(({ department }) => {
    if (department.parent_id && excluded.has(department.parent_id))
      excluded.add(department.id)
    return !department.archived && !excluded.has(department.id)
  })
  return (
    <Dialog open onOpenChange={(open) => !open && !save.isPending && close()}>
      <DialogContent className='max-h-[90dvh] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>
            {current?.archived ? '恢复部门' : current ? '编辑部门' : '新增部门'}
          </DialogTitle>
          <DialogDescription>选择上级部门和同级显示顺序。</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (current && (current.parent_id ?? 'root') !== parent)
              setConfirmMove(true)
            else save.mutate()
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={`${id}-name`}>部门名称</FieldLabel>
              <Input
                id={`${id}-name`}
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={100}
                required
                disabled={save.isPending}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor={`${id}-parent`}>上级部门</FieldLabel>
              <Select
                value={parent}
                onValueChange={setParent}
                disabled={save.isPending}
              >
                <SelectTrigger id={`${id}-parent`} className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value='root'>组织根级</SelectItem>
                    {options.map(({ department, path: label }) => (
                      <SelectItem key={department.id} value={department.id}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={`${id}-order`}>排序</FieldLabel>
              <Input
                id={`${id}-order`}
                type='number'
                min={0}
                max={1000000}
                step={1}
                value={order}
                onChange={(event) => setOrder(Number(event.target.value))}
                disabled={save.isPending}
              />
            </Field>
            {save.isError && !confirmMove && (
              <RequestError error={save.error} />
            )}
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                onClick={close}
                disabled={save.isPending}
              >
                取消
              </Button>
              <Button type='submit' disabled={!name.trim() || save.isPending}>
                {save.isPending ? '保存中…' : '保存'}
              </Button>
            </DialogFooter>
          </FieldGroup>
        </form>
        <ConfirmDialog
          open={confirmMove}
          onOpenChange={(open) => !save.isPending && setConfirmMove(open)}
          title='移动部门'
          desc='移动后，部门成员将按新的层级获得资源权限。'
          confirmText='确认移动'
          cancelBtnText='取消'
          isLoading={save.isPending}
          handleConfirm={() => save.mutate()}
        >
          {save.isError && <RequestError error={save.error} />}
        </ConfirmDialog>
      </DialogContent>
    </Dialog>
  )
}

export function DepartmentsPage() {
  const { organization, csrf } = useOrganization()
  const query = useDepartments()
  const [editing, setEditing] = useState<Department | null | undefined>(
    undefined
  )
  const [archiving, setArchiving] = useState<Department | null>(null)
  const archive = useMutation({
    mutationFn: (department: Department) =>
      api<Department>(
        `/enterprises/${organization.tenant_id}/departments/${department.id}`,
        'PUT',
        {
          name: department.name,
          parent_id: department.parent_id,
          sort_order: department.sort_order,
          archived: true,
          version: department.version,
        },
        csrf
      ),
    onSuccess: async () => {
      await query.refetch()
      setArchiving(null)
      toast.success('部门已归档')
    },
  })
  const departments = query.data ?? []
  const rows = departmentTree(departments)
  return (
    <PageShell
      title='部门管理'
      action={
        <Button disabled={!query.isSuccess} onClick={() => setEditing(null)}>
          <Plus data-icon='inline-start' /> 新增部门
        </Button>
      }
    >
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : !rows.length ? (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>暂无部门</EmptyTitle>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className='overflow-hidden rounded-lg border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>部门</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='text-right'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ department, path, depth }) => (
                <TableRow key={department.id}>
                  <TableCell
                    title={path}
                    style={{
                      paddingInlineStart: (Math.min(depth, 6) + 1) * 12,
                    }}
                  >
                    {department.name}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={department.archived ? 'outline' : 'secondary'}
                    >
                      {department.archived ? '已归档' : '正常'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className='flex flex-wrap justify-end gap-1'>
                      <Button
                        variant='ghost'
                        size='sm'
                        onClick={() => setEditing(department)}
                      >
                        {department.archived ? '恢复' : '编辑'}
                      </Button>
                      {!department.archived && (
                        <Button
                          variant='ghost'
                          size='sm'
                          onClick={() => {
                            archive.reset()
                            setArchiving(department)
                          }}
                        >
                          归档
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {editing !== undefined && (
        <DepartmentEditor
          current={editing}
          departments={departments}
          close={() => setEditing(undefined)}
        />
      )}
      {archiving && (
        <ConfirmDialog
          open
          onOpenChange={(open) =>
            !open && !archive.isPending && setArchiving(null)
          }
          title={`归档 ${archiving.name}`}
          desc='请先移走直属成员和下级部门。归档后该部门不再出现在新增授权选项中。'
          confirmText='归档'
          cancelBtnText='取消'
          isLoading={archive.isPending}
          handleConfirm={() => archive.mutate(archiving)}
        >
          {archive.isError && <RequestError error={archive.error} />}
        </ConfirmDialog>
      )}
    </PageShell>
  )
}
