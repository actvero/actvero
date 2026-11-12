import { z } from 'zod'
import type { DepartmentGrant } from './data'

export const departmentGrantSchema = z.object({
  department_id: z.string(),
  include_descendants: z.boolean(),
})

export function sameDepartmentGrants(
  a: DepartmentGrant[],
  b: DepartmentGrant[]
) {
  return (
    a.length === b.length &&
    a.every((grant) =>
      b.some(
        (other) =>
          grant.department_id === other.department_id &&
          Boolean(grant.include_descendants) ===
            Boolean(other.include_descendants)
      )
    )
  )
}
