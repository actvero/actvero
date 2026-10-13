import { useEffect, useRef, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Navigate, useLocation } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { RequestError, LoadingState } from '@/components/request-state'
import { AuthLayout } from './auth-layout'
import { loginReturnTo } from './return-to'
import { useSession, loginUrl } from './session'

export function SessionBoundary({ children }: { children: ReactNode }) {
  const isPublicHome = useLocation({
    select: (location) =>
      location.pathname === '/' || location.pathname === '/download',
  })
  const session = useSession()
  const client = useQueryClient()
  const previous = useRef<string | undefined>(undefined)
  const identity = session.data
    ? JSON.stringify([session.data.user?.id, session.data.organization])
    : undefined
  useEffect(() => {
    if (previous.current !== undefined && previous.current !== identity) {
      void client
        .cancelQueries({ queryKey: ['organization'] })
        .then(() => client.removeQueries({ queryKey: ['organization'] }))
    }
    previous.current = identity
  }, [client, identity])
  if (isPublicHome) return children
  if (session.isPending) return <LoadingState />
  if (session.isError)
    return (
      <AuthLayout title='连接服务' description='请确认服务可用后重试。'>
        <RequestError
          error={session.error}
          retry={() => void session.refetch()}
        />
      </AuthLayout>
    )
  return children
}
export function AccessGate({
  children,
  admin = false,
}: {
  children: ReactNode
  admin?: boolean
}) {
  const { data } = useSession()
  const location = useLocation()
  const next = loginReturnTo(location.href)
  if (!data) return <LoadingState />
  if (!data?.setup_complete) return <Navigate to='/setup' replace />
  if (!data.authenticated)
    // The old match may render once more while the login route is loading.
    // Do not overwrite its destination with the login page's own address.
    return location.pathname === '/login' ? (
      <LoadingState />
    ) : (
      <Navigate to='/login' search={{ next }} replace />
    )
  const organization = data.organization
  if (!organization && data.platform_operator)
    return <Navigate to='/platform/organizations' replace />
  if (
    !organization ||
    organization.status !== 'active' ||
    organization.needs_login
  )
    return (
      <AuthLayout
        title='暂时无法进入组织'
        description={
          organization?.needs_login
            ? '访问权限已更新，请重新登录。'
            : '你尚未加入组织，或访问已暂停。请联系管理员。'
        }
      >
        <Button asChild>
          <a href={loginUrl(next, true)}>重新登录 / 切换账号</a>
        </Button>
      </AuthLayout>
    )
  if (admin && organization.role !== 'administrator')
    return <Navigate to='/account' replace />
  return children
}

export function PlatformAccessGate({ children }: { children: ReactNode }) {
  const { data } = useSession()
  if (!data?.setup_complete) return <Navigate to='/setup' replace />
  if (!data.authenticated) return <Navigate to='/login' replace />
  if (!data.platform_operator) return <Navigate to='/' replace />
  return children
}

export function HomeRedirect() {
  const { data } = useSession()
  if (!data?.setup_complete) return <Navigate to='/setup' replace />
  if (!data.authenticated)
    return <Navigate to='/login' search={{ next: '/console' }} replace />
  if (
    !data.organization &&
    !data.platform_operator &&
    data.platform_edition === 'saas'
  )
    return <Navigate to='/organization-onboarding' replace />
  if (data.platform_operator && !data.organization)
    return <Navigate to='/platform/organizations' replace />
  return (
    <AccessGate>
      <Navigate to='/overview' replace />
    </AccessGate>
  )
}
