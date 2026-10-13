import { createFileRoute } from '@tanstack/react-router'
import { AccessKeysPage } from '@/features/access-keys/page'
import { AccessGate } from '@/features/auth/gate'

export const Route = createFileRoute('/_authenticated/access-keys')({
  component: () => (
    <AccessGate admin>
      <AccessKeysPage admin />
    </AccessGate>
  ),
})
