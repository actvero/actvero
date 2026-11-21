import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, ApiError, type Schema } from '@/lib/api'
import { loginReturnTo } from './return-to'

type BrowserSession = Schema['SessionView'] & { sessionEnded: boolean }

export const sessionOptions = queryOptions({
  queryKey: ['session'],
  queryFn: async ({ client }): Promise<BrowserSession> => {
    const previous = client.getQueryState<BrowserSession>(['session'])
    const error = previous?.error
    if (
      error instanceof ApiError &&
      error.retryAfterUntil &&
      error.retryAfterUntil > Date.now()
    )
      throw error
    let session: Schema['SessionView']
    try {
      session = await api<Schema['SessionView']>('/auth/session')
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error
      session = await api<Schema['SessionView']>('/auth/session')
    }
    return {
      ...session,
      sessionEnded:
        !session.authenticated &&
        Boolean(previous?.data?.authenticated || previous?.data?.sessionEnded),
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
