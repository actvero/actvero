import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { DepartmentsPage } from '@/features/departments/page'

export const Route = createFileRoute('/_authenticated/departments')({
  component: () => (
    <AccessGate admin>
      <DepartmentsPage />
    </AccessGate>
  ),
})
