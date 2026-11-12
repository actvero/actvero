import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { ScrollArea } from '@/components/ui/scroll-area'
import { LoadingState, RequestError } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { departmentTree, useDepartments, type DepartmentGrant } from './data'
import { ListPager } from './list-pager'

export function DepartmentScopePreview({
  members,
  grants,
}: {
  members: string[]
  grants: DepartmentGrant[]
}) {
  const [page, setPage] = useState(1)
  const { organization, user, csrf } = useOrganization()
  const path = `/enterprises/${organization.tenant_id}/departments/scope-preview`
  const departments = useDepartments(grants.length > 0)
  const body: Schema['DepartmentScopePreview'] = {
    member_ids: members,
    department_grants: grants,
    page,
  }
  const hasRules = members.length > 0 || grants.length > 0
  // CSRF authenticates this read and is excluded from cache identity.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const preview = useQuery({
    queryKey: ['organization', organization.tenant_id, user.id, path, body],
    queryFn: ({ signal }) =>
      api<Schema['DepartmentScopePage']>(path, 'POST', body, csrf, signal),
    enabled: hasRules,
  })
  const names = new Map(
    departmentTree(departments.data ?? []).map(
      ({ department, path: label }) => [department.id, label]
    )
  )
  const descendants = new Set(
    grants
      .filter((grant) => grant.include_descendants)
      .map((grant) => grant.department_id)
  )
  return (
    <aside
      aria-label='授权预览'
      className='flex min-w-0 flex-col gap-3 self-start rounded-lg bg-muted/65 p-4'
    >
      <div className='flex flex-wrap items-baseline gap-3'>
        <h3 className='font-semibold'>授权预览</h3>
        {preview.data && (
          <span className='text-sm text-muted-foreground' aria-live='polite'>
            共 {preview.data.total} 人
          </span>
        )}
      </div>
      {!hasRules ? (
        <p className='text-sm text-muted-foreground'>
          添加部门或成员后可查看授权名单。
        </p>
      ) : preview.isError || departments.isError ? (
        <RequestError
          error={preview.error ?? departments.error}
          retry={() =>
            void (preview.isError ? preview.refetch() : departments.refetch())
          }
        />
      ) : preview.isPending || (grants.length > 0 && departments.isPending) ? (
        <LoadingState />
      ) : !preview.data.total ? (
        <p className='text-sm text-muted-foreground'>
          当前规则未匹配到有效成员。
        </p>
      ) : (
        <>
          <ScrollArea
            role='region'
            aria-label='获授权成员'
            viewportClassName='max-h-64'
          >
            <ul className='divide-y'>
              {preview.data.items.map((member) => {
                const sources = [
                  ...(member.direct ? ['单独授权'] : []),
                  ...member.department_ids.map((id) => {
                    const label = names.get(id) ?? '部门授权'
                    return descendants.has(id) ? label + '（含下级）' : label
                  }),
                ]
                return (
                  <li
                    key={member.id}
                    className='flex items-center gap-3 py-2.5'
                  >
                    <UserAvatar user={member} />
                    <div className='min-w-0'>
                      <div className='text-sm font-medium break-words'>
                        {member.name}
                      </div>
                      <div className='text-xs break-words text-muted-foreground'>
                        {sources.join('、')}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </ScrollArea>
          <ListPager
            page={page}
            total={preview.data.total}
            onChange={setPage}
          />
        </>
      )}
    </aside>
  )
}
