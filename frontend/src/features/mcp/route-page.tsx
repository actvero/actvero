import { useSession } from '@/features/auth/session'
import { MemberMcpPage } from './member-page'
import { McpPage } from './page'

export function McpRoutePage({ serviceId }: { serviceId?: string }) {
  const { data } = useSession()
  return data?.organization?.role === 'administrator' ? (
    <McpPage serviceId={serviceId} />
  ) : (
    <MemberMcpPage />
  )
}
