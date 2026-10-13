import { createFileRoute } from '@tanstack/react-router'
import { AuditPage } from '@/features/audit/page'
import { AccessGate } from '@/features/auth/gate'

export const Route = createFileRoute('/_authenticated/audit')({
  component: () => (
    <AccessGate admin>
      <AuditPage />
    </AccessGate>
  ),
})
