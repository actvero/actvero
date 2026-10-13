import { useSession } from '@/features/auth/session'
import { MemberMcpPage } from './member-page'
import { McpPage } from './page'

export function McpRoutePage() {
  const { data } = useSession()
  return data?.organization?.role === 'administrator' ? (
    <McpPage />
  ) : (
    <MemberMcpPage />
  )
}
