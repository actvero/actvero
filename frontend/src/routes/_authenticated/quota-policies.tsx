import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { QuotaPoliciesPage } from '@/features/quota-policies/page'

export const Route = createFileRoute('/_authenticated/quota-policies')({
  component: () => (
    <AccessGate admin>
      <QuotaPoliciesPage />
    </AccessGate>
  ),
})
