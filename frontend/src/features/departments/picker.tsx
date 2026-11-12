import { useId, useState } from 'react'
import { Folder, Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Switch } from '@/components/ui/switch'
import { LoadingState, RequestError } from '@/components/request-state'
import {
  departmentTree,
  useDepartments,
  type Department,
  type DepartmentGrant,
} from './data'
import { DepartmentTree } from './tree'

export type DepartmentSelection = {
  value: DepartmentGrant[]
  onChange: (value: DepartmentGrant[]) => void
}

function DepartmentSelectionDialog({
  departments,
  value,
  onChange,
  close,
  disabled,
}: DepartmentSelection & {
  departments: Department[]
  close: () => void
  disabled?: boolean
}) {
  const [ids, setIds] = useState(value.map((grant) => grant.department_id))
  return (
    <>
      <DepartmentTree
        departments={departments}
        selection={{ selectedIds: ids, change: setIds, disabled }}
        emptyText='请先在部门管理中创建部门'
      />
      <DialogFooter>
        <Button type='button' variant='outline' onClick={close}>
          取消
        </Button>
        <Button
          type='button'
          disabled={disabled}
          onClick={() => {
            onChange(
              ids.map(
                (id) =>
                  value.find((grant) => grant.department_id === id) ?? {
                    department_id: id,
                    include_descendants: false,
                  }
              )
            )
            close()
          }}
        >
          应用选择
        </Button>
      </DialogFooter>
    </>
  )
}

export function DepartmentGrantPicker({
  value,
  onChange,
  disabled,
}: DepartmentSelection & { disabled?: boolean }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const query = useDepartments(open || value.length > 0)
  const rows = new Map(
    departmentTree(query.data ?? []).map((row) => [row.department.id, row])
  )
  const close = () => setOpen(false)
  return (
    <section className='flex min-w-0 flex-col gap-2' aria-label='部门授权规则'>
      <div className='flex flex-wrap items-center gap-x-2'>
        <h3 className='text-sm font-semibold'>部门</h3>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button type='button' variant='ghost' size='sm' disabled={disabled}>
              <Plus data-icon='inline-start' /> 添加部门
            </Button>
          </DialogTrigger>
          <DialogContent className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg'>
            <DialogHeader>
              <DialogTitle>选择部门</DialogTitle>
              <DialogDescription>
                勾选要授权的部门，应用后可设置是否包含下级。
              </DialogDescription>
            </DialogHeader>
            {query.isError ? (
              <RequestError
                error={query.error}
                retry={() => void query.refetch()}
              />
            ) : query.isPending ? (
              <LoadingState />
            ) : (
              <DepartmentSelectionDialog
                departments={query.data}
                value={value}
                onChange={onChange}
                close={close}
                disabled={disabled}
              />
            )}
          </DialogContent>
        </Dialog>
      </div>
      {value.length === 0 ? (
        <p className='text-sm text-muted-foreground'>未添加部门</p>
      ) : query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <ScrollArea
          role='region'
          aria-label='已授权部门'
          viewportClassName='max-h-64'
        >
          <ul className='flex flex-col gap-2'>
            {value.map((grant) => {
              const row = rows.get(grant.department_id)
              const department = row?.department
              const parentId = department?.parent_id
              const label = department?.name ?? '部门不可用'
              const switchId = `${id}-${grant.department_id}`
              return (
                <li
                  key={grant.department_id}
                  className='flex min-w-0 flex-wrap items-center gap-2 rounded-md border px-3 py-2'
                >
                  <Folder
                    className='size-4 shrink-0 text-muted-foreground'
                    aria-hidden='true'
                  />
                  <div className='min-w-24 flex-1'>
                    <div className='text-sm font-medium break-words'>
                      {label}
                    </div>
                    {parentId && (
                      <div className='text-xs break-words text-muted-foreground'>
                        {rows.get(parentId)?.path}
                      </div>
                    )}
                    {department?.archived && (
                      <p className='text-xs text-muted-foreground'>已归档</p>
                    )}
                  </div>
                  {department && !department.archived && (
                    <div className='flex items-center gap-2'>
                      <label htmlFor={switchId} className='text-xs'>
                        包含下级部门
                      </label>
                      <Switch
                        id={switchId}
                        checked={grant.include_descendants ?? false}
                        disabled={disabled}
                        onCheckedChange={(checked) =>
                          onChange(
                            value.map((item) =>
                              item.department_id === grant.department_id
                                ? { ...item, include_descendants: checked }
                                : item
                            )
                          )
                        }
                      />
                    </div>
                  )}
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    className='size-8'
                    aria-label={`移除 ${label}`}
                    disabled={disabled}
                    onClick={() =>
                      onChange(
                        value.filter(
                          (item) => item.department_id !== grant.department_id
                        )
                      )
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
  )
}
