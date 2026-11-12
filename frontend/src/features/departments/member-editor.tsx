import { useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import {
  departmentTree,
  useDepartments,
  type Department,
  type DepartmentGrant,
} from './data'
import { DepartmentChoices } from './picker'

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
  const id = useId()
  const { organization, csrf } = useOrganization()
  const client = useQueryClient()
  const [selection, setSelection] = useState<DepartmentGrant[]>(
    (current.department_ids ?? []).map((department_id) => ({
      department_id,
      include_descendants: false,
    }))
  )
  const [primary, setPrimary] = useState(current.primary_department_id ?? '')
  const ids = selection.map((item) => item.department_id)
  const dirty =
    primary !== (current.primary_department_id ?? '') ||
    ids.slice().sort().join(',') !==
      [...(current.department_ids ?? [])].sort().join(',')
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
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (dirty && !save.isPending) save.mutate()
      }}
    >
      <FieldGroup>
        <Field>
          <FieldLabel>所属部门</FieldLabel>
          <DepartmentChoices
            departments={departments}
            value={selection}
            disabled={save.isPending}
            onChange={(next) => {
              setSelection(next)
              if (!next.some((item) => item.department_id === primary))
                setPrimary(next[0]?.department_id ?? '')
            }}
          />
        </Field>
        {!!selection.length && (
          <Field>
            <FieldLabel htmlFor={id}>主部门</FieldLabel>
            <Select
              value={primary}
              onValueChange={setPrimary}
              disabled={save.isPending}
            >
              <SelectTrigger id={id} className='w-full'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {departmentTree(departments)
                    .filter(({ department }) => ids.includes(department.id))
                    .map(({ department, path: label }) => (
                      <SelectItem key={department.id} value={department.id}>
                        {label}
                      </SelectItem>
                    ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        )}
        {save.isError && <RequestError error={save.error} />}
        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            onClick={close}
            disabled={save.isPending}
          >
            取消
          </Button>
          <Button type='submit' disabled={!dirty || save.isPending}>
            {save.isPending ? '保存中…' : '保存部门'}
          </Button>
        </DialogFooter>
      </FieldGroup>
    </form>
  )
}

export function MemberDepartmentEditor({
  memberId,
  close,
}: {
  memberId: string
  close: () => void
}) {
  const { organization, user } = useOrganization()
  const path = `/enterprises/${organization.tenant_id}/members/${memberId}/departments`
  const [pending, setPending] = useState(false)
  const departments = useDepartments()
  const assignment = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, path],
    queryFn: ({ signal }) =>
      api<Assignment>(path, 'GET', undefined, undefined, signal),
  })
  return (
    <Dialog open onOpenChange={(open) => !open && !pending && close()}>
      <DialogContent className='max-h-[90dvh] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>设置成员部门</DialogTitle>
          <DialogDescription>
            可以选择多个所属部门，并指定一个主部门。
          </DialogDescription>
        </DialogHeader>
        {departments.isError ? (
          <RequestError
            error={departments.error}
            retry={() => void departments.refetch()}
          />
        ) : assignment.isError ? (
          <RequestError
            error={assignment.error}
            retry={() => void assignment.refetch()}
          />
        ) : departments.isPending || assignment.isPending ? (
          <LoadingState />
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
