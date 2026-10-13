import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, ApiError, type Schema } from '@/lib/api'
import { loginReturnTo } from './return-to'

export const sessionOptions = queryOptions({
  queryKey: ['session'],
  queryFn: async ({ client }) => {
    const previous = client.getQueryState(['session'])?.error
    if (
      previous instanceof ApiError &&
      previous.retryAfterUntil &&
      previous.retryAfterUntil > Date.now()
    )
      throw previous
    try {
      return await api<Schema['SessionView']>('/auth/session')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401)
        return api<Schema['SessionView']>('/auth/session')
      throw error
    }
  },
  staleTime: 0,
  retry: false,
  // The error page also reads this query; mounting it must not restart a failed request.
  retryOnMount: false,
  refetchOnWindowFocus: true,
  refetchInterval: (query) => {
    const error = query.state.error
    return error instanceof ApiError && error.retryAfterUntil
      ? Math.max(60000, error.retryAfterUntil - Date.now())
      : 60000
  },
})
export function useSession() {
  return useQuery(sessionOptions)
}
export function useOrganization() {
  const { data } = useSession()
  if (!data?.organization || !data.user) throw new Error('组织会话尚未就绪')
  return {
    session: data,
    organization: data.organization,
    user: data.user,
    csrf: data.csrf,
  }
}
export function loginUrl(
  next = '/console',
  switchAccount = false,
  flow?: string
) {
  return (
    '/api/v1/auth/login?next=' +
    encodeURIComponent(loginReturnTo(next)) +
    (switchAccount ? '&switch=true' : '') +
    (flow ? '&flow=' + encodeURIComponent(flow) : '')
  )
}
