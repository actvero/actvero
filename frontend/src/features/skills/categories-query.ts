import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { useSkills } from './shared'

export type Category = Schema['ManagedSkillCategory']
export function useCategories() {
  const { key } = useSkills()
  return useQuery({
    queryKey: [...key, 'categories'],
    queryFn: ({ signal }) =>
      api<Category[]>(
        '/skills/categories',
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
}
