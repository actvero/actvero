import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type Department = Schema['DepartmentView']
export type DepartmentGrant = Schema['DepartmentGrant']

export function useDepartments(enabled = true) {
  const { organization, user } = useOrganization()
  const path = `/enterprises/${organization.tenant_id}/departments`
  return useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, path],
    queryFn: ({ signal }) =>
      api<Department[]>(path, 'GET', undefined, undefined, signal),
    enabled,
  })
}

export function departmentTree(departments: Department[]) {
  const children = new Map<string | null, Department[]>()
  for (const department of departments) {
    const parent = department.parent_id ?? null
    const siblings = children.get(parent) ?? []
    siblings.push(department)
    children.set(parent, siblings)
  }
  const rows: { department: Department; path: string; depth: number }[] = []
  function append(parent: string | null, path: string, depth: number) {
    for (const department of children.get(parent) ?? []) {
      const name = path ? `${path} / ${department.name}` : department.name
      rows.push({ department, path: name, depth })
      append(department.id, name, depth + 1)
    }
  }
  append(null, '', 0)
  return rows
}
