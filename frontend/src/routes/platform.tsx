import { createFileRoute } from '@tanstack/react-router'
import { AuthenticatedLayout } from '@/components/layout/authenticated-layout'
import { PlatformAccessGate } from '@/features/auth/gate'

export const Route = createFileRoute('/platform')({
  component: () => (
    <PlatformAccessGate>
      <AuthenticatedLayout />
    </PlatformAccessGate>
  ),
})
