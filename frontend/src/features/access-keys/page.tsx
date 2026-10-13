import { PageShell } from '@/components/layout/page-shell'
import { useOrganization } from '@/features/auth/session'
import { KeyList } from './key-list'

export function AccessKeysPage({ admin = false }: { admin?: boolean }) {
  const { organization, user, csrf } = useOrganization()
  return (
    <PageShell title={admin ? '密钥管理' : '访问密钥'}>
      <KeyList
        identity={organization.tenant_id + ':' + user.id}
        csrf={csrf}
        admin={admin}
      />
    </PageShell>
  )
}
