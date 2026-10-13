import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { ExpertsPage } from '@/features/experts/page'

export const Route = createFileRoute('/_authenticated/experts/')({
  component: () => (
    <AccessGate admin>
      <ExpertsPage />
    </AccessGate>
  ),
})
