import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { WorkbenchesPage } from '@/features/workbenches/page'

export const Route = createFileRoute('/_authenticated/workbenches/')({
  component: () => (
    <AccessGate admin>
      <WorkbenchesPage />
    </AccessGate>
  ),
})
