import { useId, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
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
import { Separator } from '@/components/ui/separator'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { departmentTree, useDepartments, type Department } from './data'
import { DepartmentDetail } from './detail'
import { DepartmentTree } from './tree'

function DepartmentEditor({
  current,
  departments,
  close,
  saved,
}: {
  current: Department | null
  departments: Department[]
  close: () => void
  saved: (id: string) => void
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
    onSuccess: async (department) => {
      await client.invalidateQueries({
        queryKey: ['organization', organization.tenant_id],
      })
      toast.success(current?.archived ? '部门已恢复' : '部门已保存')
      saved(department.id)
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
  const [selectedId, setSelectedId] = useState<string>()
  const [showArchived, setShowArchived] = useState(false)
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
  const selected =
    rows.find(
      ({ department }) =>
        department.id === selectedId && (showArchived || !department.archived)
    ) ?? rows.find(({ department }) => showArchived || !department.archived)
  const parentId = selected?.department.parent_id
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
      ) : (
        <div className='grid min-w-0 divide-y lg:min-h-[min(70dvh,45rem)] lg:grid-cols-[minmax(14rem,19rem)_minmax(0,1fr)] lg:divide-x lg:divide-y-0'>
          <aside className='flex min-w-0 flex-col gap-3 pb-5 lg:pe-5 lg:pb-0'>
            <h2 className='font-semibold'>部门结构</h2>
            <DepartmentTree
              departments={departments}
              selection={{
                selectedId: selected?.department.id,
                select: setSelectedId,
              }}
              showArchived={showArchived}
              emptyText='暂无有效部门'
            />
            {departments.some((department) => department.archived) && (
              <div className='mt-auto flex flex-col gap-2 pt-4'>
                <Separator />
                <Button
                  type='button'
                  variant='ghost'
                  size='sm'
                  className='self-start'
                  aria-pressed={showArchived}
                  onClick={() => setShowArchived(!showArchived)}
                >
                  <Archive data-icon='inline-start' />
                  {showArchived ? '隐藏已归档部门' : '查看已归档部门'}
                </Button>
              </div>
            )}
          </aside>
          <div className='min-w-0 pt-5 lg:ps-6 lg:pt-0'>
            {selected ? (
              <DepartmentDetail
                key={selected.department.id}
                department={selected.department}
                parentPath={
                  rows.find(({ department }) => department.id === parentId)
                    ?.path
                }
                childrenCount={
                  departments.filter(
                    (department) =>
                      department.parent_id === selected.department.id &&
                      !department.archived
                  ).length
                }
                edit={() => setEditing(selected.department)}
                archive={() => {
                  archive.reset()
                  setArchiving(selected.department)
                }}
              />
            ) : (
              <Empty>
                <EmptyHeader>
                  <EmptyTitle>暂无部门</EmptyTitle>
                </EmptyHeader>
              </Empty>
            )}
          </div>
        </div>
      )}
      {editing !== undefined && (
        <DepartmentEditor
          current={editing}
          departments={departments}
          close={() => setEditing(undefined)}
          saved={(id) => {
            setSelectedId(id)
            setEditing(undefined)
          }}
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
