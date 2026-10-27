import { createFileRoute } from '@tanstack/react-router'
import { AccessGate } from '@/features/auth/gate'
import { GatewayPage } from '@/features/model-gateway/page'

export const Route = createFileRoute('/_authenticated/model-channels')({
  component: () => (
    <AccessGate admin>
      <GatewayPage view='channels' />
    </AccessGate>
  ),
})
