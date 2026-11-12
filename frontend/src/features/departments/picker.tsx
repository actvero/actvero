import { useId, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Field, FieldLabel } from '@/components/ui/field'
import { ScrollArea } from '@/components/ui/scroll-area'
import { LoadingState, RequestError } from '@/components/request-state'
import {
  departmentTree,
  useDepartments,
  type Department,
  type DepartmentGrant,
} from './data'

export type DepartmentSelection = {
  value: DepartmentGrant[]
  onChange: (value: DepartmentGrant[]) => void
}

export function DepartmentChoices({
  departments,
  value,
  onChange,
  disabled,
  grant = false,
}: DepartmentSelection & {
  departments: Department[]
  disabled?: boolean
  grant?: boolean
}) {
  const id = useId()
  const rows = departmentTree(departments).filter(
    ({ department }) =>
      !department.archived ||
      value.some((item) => item.department_id === department.id)
  )
  const missing = value.filter(
    (item) => !departments.some((d) => d.id === item.department_id)
  )
  if (!rows.length && !missing.length)
    return (
      <p className='text-sm text-muted-foreground'>
        请先在部门管理中创建部门。
      </p>
    )
  return (
    <ScrollArea
      viewportClassName='max-h-64'
      role='region'
      aria-label='部门列表'
    >
      <div className='flex flex-col gap-3 p-1'>
        {rows.map(({ department, path }) => {
          const selected = value.find(
            (item) => item.department_id === department.id
          )
          const key = `${id}-${department.id}`
          return (
            <div
              key={department.id}
              className='flex flex-wrap items-center justify-between gap-2'
            >
              <Field orientation='horizontal' className='w-auto'>
                <Checkbox
                  id={key}
                  checked={!!selected}
                  disabled={
                    disabled ||
                    (!selected && (department.archived || value.length >= 100))
                  }
                  onCheckedChange={(checked) =>
                    onChange(
                      checked
                        ? [
                            ...value,
                            {
                              department_id: department.id,
                              include_descendants: false,
                            },
                          ]
                        : value.filter(
                            (item) => item.department_id !== department.id
                          )
                    )
                  }
                />
                <FieldLabel htmlFor={key}>
                  {path}
                  {department.archived ? '（已归档）' : ''}
                </FieldLabel>
              </Field>
              {grant && selected && !department.archived && (
                <Field orientation='horizontal' className='w-auto'>
                  <Checkbox
                    id={`${key}-children`}
                    checked={selected.include_descendants ?? false}
                    disabled={disabled}
                    onCheckedChange={(checked) =>
                      onChange(
                        value.map((item) =>
                          item.department_id === department.id
                            ? { ...item, include_descendants: checked === true }
                            : item
                        )
                      )
                    }
                  />
                  <FieldLabel htmlFor={`${key}-children`}>包含下级</FieldLabel>
                </Field>
              )}
            </div>
          )
        })}
        {missing.map((item) => (
          <div
            key={item.department_id}
            className='flex items-center justify-between gap-2'
          >
            <span className='text-sm text-muted-foreground'>部门不可用</span>
            <Button
              type='button'
              variant='ghost'
              size='sm'
              disabled={disabled}
              onClick={() => onChange(value.filter((entry) => entry !== item))}
            >
              移除授权
            </Button>
          </div>
        ))}
      </div>
    </ScrollArea>
  )
}

export function DepartmentGrantPicker({
  value,
  onChange,
  disabled,
}: DepartmentSelection & { disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const query = useDepartments(open)
  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className='flex flex-col gap-3'
    >
      <CollapsibleTrigger asChild>
        <Button
          type='button'
          variant='outline'
          className='self-start'
          disabled={disabled}
        >
          选择部门{value.length ? `（${value.length}）` : ''}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        {query.isError ? (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : query.isPending ? (
          <LoadingState />
        ) : (
          <DepartmentChoices
            departments={query.data}
            value={value}
            onChange={onChange}
            disabled={disabled}
            grant
          />
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
