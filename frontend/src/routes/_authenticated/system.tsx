import { createFileRoute, Outlet } from '@tanstack/react-router'
import { SystemAccessGate } from '@/features/auth/gate'

export const Route = createFileRoute('/_authenticated/system')({
  component: () => (
    <SystemAccessGate>
      <Outlet />
    </SystemAccessGate>
  ),
})
