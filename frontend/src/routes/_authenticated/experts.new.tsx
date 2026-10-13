import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { ExpertEditor } from '@/features/experts/editor'

export const Route = createFileRoute('/_authenticated/experts/new')({
  component: () => (
    <AccessGate admin>
      <ExpertEditor />
    </AccessGate>
  ),
})
