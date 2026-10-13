import { z } from 'zod'
import { queryOptions } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'

export const portalSchema = z.object({ portal_enabled: z.boolean() })

export const siteSettingsOptions = queryOptions({
  queryKey: ['public', 'site'],
  queryFn: async ({ signal }) => {
    const value = await api<Schema['PortalSettings']>(
      '/platform/site',
      'GET',
      undefined,
      undefined,
      signal
    )
    if (!portalSchema.safeParse(value).success)
      throw new Error('首页设置暂时不可用，请重试')
    return value
  },
  staleTime: 0,
  retry: false,
})
