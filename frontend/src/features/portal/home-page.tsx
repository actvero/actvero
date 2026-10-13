import { useQuery } from '@tanstack/react-query'
import { Navigate } from '@tanstack/react-router'
import { LoadingState, RequestError } from '@/components/request-state'
import { AuthLayout } from '@/features/auth/auth-layout'
import { PortalPage } from './page'
import { siteSettingsOptions } from './site-settings'

export function HomePage() {
  const settings = useQuery(siteSettingsOptions)
  if (settings.isPending || settings.isFetching) return <LoadingState />
  if (settings.isError)
    return (
      <AuthLayout title='无法加载首页' description=''>
        <RequestError
          error={settings.error}
          retry={() => void settings.refetch()}
        />
      </AuthLayout>
    )
  return settings.data.portal_enabled ? (
    <PortalPage />
  ) : (
    <Navigate to='/console' replace />
  )
}
