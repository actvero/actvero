import { createFileRoute } from '@tanstack/react-router'
import { AuthenticatedLayout } from '@/components/layout/authenticated-layout'
import { AccessGate } from '@/features/auth/gate'

export const Route = createFileRoute('/_authenticated')({
  component: () => (
    <AccessGate>
      <AuthenticatedLayout />
    </AccessGate>
  ),
})
