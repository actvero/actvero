import { useEffect, useRef } from 'react'
import { Navigate, useSearch } from '@tanstack/react-router'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { LoadingState, RequestError } from '@/components/request-state'
import { useBranding } from '@/features/branding/data'
import { AuthLayout } from './auth-layout'
import { loginUrl, useSession } from './session'

export function LoginPage() {
  const brand = useBranding()
  const query = useSession()
  const { data } = query
  const { error, next } = useSearch({ from: '/login' })
  const started = useRef(false)
  const ready = data && (data.setup_complete || data.setup_account_created)
  useEffect(() => {
    if (
      ready &&
      data.registration_mode === 'invite' &&
      !data.authenticated &&
      !error &&
      !started.current
    ) {
      started.current = true
      window.location.replace(loginUrl(next))
    }
  }, [ready, data, error, next])
  if (query.isError)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  if (!data) return <LoadingState />
  if (!ready) return <Navigate to='/setup' replace />
  // A revisited/duplicate callback can show an old error after login has
  // succeeded. Only the validated session API can authorize this recovery.
  if (data.authenticated && error === 'callback' && query.isFetching)
    return <LoadingState />
  if (data.authenticated && (!error || error === 'callback'))
    return <Navigate to={next} href={next} replace />
  if (!error && data.registration_mode !== 'invite')
    return (
      <AuthLayout title={`登录 ${data.platform_name}`} description=''>
        <Button asChild>
          <a href={loginUrl(next)}>登录</a>
        </Button>
        <Button asChild variant='outline'>
          <a href='/organization-onboarding'>
            {data.registration_mode === 'approval'
              ? '申请开通组织'
              : '创建组织'}
          </a>
        </Button>
      </AuthLayout>
    )
  if (!error) return <LoadingState />
  return (
    <AuthLayout
      title='登录未完成'
      description={`请重新登录，继续使用 ${brand.name}。`}
    >
      <Alert variant='destructive'>
        <AlertDescription>
          {error === 'cancelled' ? '登录已取消。' : '登录验证未完成或已过期。'}
        </AlertDescription>
      </Alert>
      <Button asChild>
        <a href={loginUrl(next, true)}>重新登录</a>
      </Button>
    </AuthLayout>
  )
}
