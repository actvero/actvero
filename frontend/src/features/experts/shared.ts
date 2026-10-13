import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type Expert = Schema['ExpertView']
export type ExpertSummary = Schema['ExpertSummary']
export type Content = Required<Schema['ExpertContent']>
export type Category = Schema['ManagedExpertCategory']
export const scopeLabels = {
  administrators: '仅管理员',
  selected: '指定成员',
  organization: '组织全员',
}
export const statusLabels = {
  draft: '草稿',
  published: '已发布',
  withdrawn: '已下架',
}
export function useExperts() {
  const { organization, user, csrf } = useOrganization()
  const client = useQueryClient()
  const key = ['organization', organization.tenant_id, user.id, 'experts']
  return {
    key,
    csrf,
    refresh: () => client.invalidateQueries({ queryKey: key }),
  }
}
export function useCategories() {
  const { key } = useExperts()
  return useQuery({
    queryKey: [...key, 'categories'],
    queryFn: ({ signal }) =>
      api<Category[]>(
        '/experts/categories',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
}
